# 001-Concept/02_llm_pipeline.py
"""
[サブグラフ② LLM生成・検証パイプラインデモ]
仮名化 -> LLM生成 -> フォーマット検証 -> 整合性検証 -> 実名復元
検証失敗時はリトライし、上限(3回)を超えた場合は show_raw (フォールバック) へ進む
"""
import json
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END


# ----------------------------------------------------
# 1. State (状態) の定義
# ----------------------------------------------------
class LLMPipelineState(TypedDict):
    raw_input_names: dict       # マッピング用実名データ {"スタッフA": "山田太郎", "スタッフB": "佐藤花子"}
    prompt_input: str           # 仮名化された入力データ
    llm_output_raw: str         # LLMからの生の出力テキスト
    parsed_json: Optional[dict] # パース後のJSONデータ
    final_result: str           # 最終出力結果
    retry_count: int            # リトライカウンター (上限3回)


# ----------------------------------------------------
# 2. 各ノード (Node) 関数の定義
# ----------------------------------------------------
# ノード 1: 仮名化 (個人情報保護)
def node_pseudonymize(state: LLMPipelineState) -> dict:
    print("\n--- [Node 1: Pseudonymize] 実名を仮名ID(スタッフA等)に置き換えます ---")
    # 実名マッピングを保持し、入力テキストを仮名化
    mapping = {"山田太郎": "スタッフA", "佐藤花子": "スタッフB"}
    pseudonymized_text = "スタッフA: 遅番希望, スタッフB: 休業希望"
    print(f"  仮名化後のテキスト: '{pseudonymized_text}'")
    
    return {
        "raw_input_names": {"スタッフA": "山田太郎", "スタッフB": "佐藤花子"},
        "prompt_input": pseudonymized_text,
        "retry_count": 0
    }


# ノード 2: LLM呼び出し
def node_call_llm(state: LLMPipelineState) -> dict:
    current_retry = state.get("retry_count", 0) + 1
    print(f"\n--- [Node 2: Call LLM] (試行回数: {current_retry}/3) ---")
    
    # デモ用モック: リトライ回数に応じて疑似レスポンスを変更
    if current_retry == 1:
        # 1度目: フォーマットエラーになる不完全なJSONを模倣
        mock_output = '{"explanation": "スタッフAのシフトを調整しました", options: [INVALID_JSON]}'
    elif current_retry == 2:
        # 2度目: JSONは正しいが、内容（データ）が矛盾している
        mock_output = json.dumps({
            "explanation": "存在しないスタッフCを配置しました", # 整合性エラー
            "options": ["案1: スタッフC追加"]
        }, ensure_ascii=False)
    else:
        # 3度目: 完全で正しいJSON
        mock_output = json.dumps({
            "explanation": "スタッフAを遅番に配置し、人件費を最適化しました",
            "options": ["案1: スタッフA 遅番"]
        }, ensure_ascii=False)

    print(f"  LLM出力 (RAW): {mock_output}")

    return {
        "llm_output_raw": mock_output,
        "retry_count": current_retry
    }

# ノード 3: フォーマット検証 (JSONパース)
def node_check_format(state: LLMPipelineState) -> dict:
    print("--- [Node 3: Check Format] JSON構文チェック中... ---")
    raw_text = state["llm_output_raw"]

    # JSONパースを試みる
    try:
        parsed = json.loads(raw_text)
        print("  -> SUCCESS: 正しいJSON構造です")
        return {"parsed_json": parsed}
    
    except json.JSONDecodeError:
        print("  -> ERROR: JSON構文エラーを検知しました")
        return {"parsed_json": None}


# ノード 4: 整合性検証 (ハルシネーション・データ矛盾の検出)
def node_check_consistency(state: LLMPipelineState) -> dict:
    print("--- [Node 4: Check Consistency] データ整合性チェック中... ---")
    parsed = state.get("parsed_json", {})
    explanation = parsed.get("explanation", "")

    # 入力にない「スタッフC」が含まれていたら不整合とみなす
    if "スタッフC" in explanation:
        print("  -> ERROR: 入力データに存在しない「スタッフC」が含まれています (不整合)")
        return {"parsed_json": None} # 不整合の場合は parsed_json をクリア
    
    print("  -> SUCCESS: データ整合性チェックに合格しました")

    return {}


# ノード 5: 実名復元 (合格時)
def node_restore_names(state: LLMPipelineState) -> dict:
    print("\n--- [Node 5: Restore Names] 仮名を実名に復元して最終結果を作成します ---")
    parsed = state["parsed_json"]
    result_str = json.dumps(parsed, ensure_ascii=False)
    
    # 仮名を実名に置換
    for pseudo_id, real_name in state["raw_input_names"].items():
        result_str = result_str.replace(pseudo_id, real_name)
        
    print("  -> 復元完了！")
    return {"final_result": result_str}


# ノード 6: フォールバック (リトライ上限・失敗時)
def node_show_raw(state: LLMPipelineState) -> dict:
    print("\n--- [Node: Show RAW] 検証リトライ上限に達したため、元の生データを返します ---")
    fallback_data = f"【ソルバー生データ】{state['prompt_input']} (AI生成に失敗したため生データを表示中)"
    return {"final_result": fallback_data}


# ----------------------------------------------------
# 3. ルーティング関数 (Conditional Edges)
# ----------------------------------------------------
# フォーマット判定後の分岐
def route_after_format_check(state: LLMPipelineState) -> str:

    if state.get("parsed_json") is not None:
        return "check_consistency" # 成功したら整合性チェックへ
    
    if state["retry_count"] >= 3:
        return "show_raw" # 上限に達していたらフォールバック
    else:
        return "call_llm" # 失敗したらリトライ



# 整合性判定後の分岐
def route_after_consistency_check(state: LLMPipelineState) -> str:

    if state.get("parsed_json") is not None:
        return "restore_names" # 成功したら実名復元へ
    
    if state["retry_count"] >= 3:
        return "show_raw" # 上限に達していたらフォールバック
    else:
        return "call_llm" # 失敗したらリトライ


# ----------------------------------------------------
# 4. グラフの構築
# ----------------------------------------------------
builder = StateGraph(LLMPipelineState)

# ノード登録
builder.add_node("pseudonymize", node_pseudonymize)
builder.add_node("call_llm", node_call_llm)
builder.add_node("check_format", node_check_format)
builder.add_node("check_consistency", node_check_consistency)
builder.add_node("restore_names", node_restore_names)
builder.add_node("show_raw", node_show_raw)

# エッジ登録
builder.set_entry_point("pseudonymize")
builder.add_edge("pseudonymize", "call_llm")
builder.add_edge("call_llm", "check_format")

# 条件付きエッジ
builder.add_conditional_edges(
    "check_format",
    route_after_format_check,
    {
        "check_consistency": "check_consistency",
        "call_llm": "call_llm",
        "show_raw": "show_raw"
    }
)

builder.add_conditional_edges(
    "check_consistency",
    route_after_consistency_check,
    {
        "restore_names": "restore_names",
        "call_llm": "call_llm",
        "show_raw": "show_raw"
    }
)

builder.add_edge("restore_names", END)
builder.add_edge("show_raw", END)

# グラフコンパイル
pipeline_graph = builder.compile()


# ----------------------------------------------------
# 5. 実行
# ----------------------------------------------------
if __name__ == "__main__":
    print("==================================================")
    print(" [実行デモ] LLMパイプライン (リトライ & ガードレール)")
    print("==================================================")
    
    initial_state = {
        "raw_input_names": {},
        "prompt_input": "",
        "llm_output_raw": "",
        "parsed_json": None,
        "final_result": "",
        "retry_count": 0
    }
    
    final_output = pipeline_graph.invoke(initial_state)
    
    print("\n==================================================")
    print(" 【最終出力結果】")
    print(final_output["final_result"])
    print("==================================================")