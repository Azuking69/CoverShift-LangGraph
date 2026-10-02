# 001-Concept/01_simple_graph.py
"""
[LangGraph の最小基本構造]
1. State(状態）を定義する
2. Node(処理を行う関数）を定義する
   普通のPython関数と同じだが、「LangGraphのグラフ構造に組み込まれて動作する」という役割とルールを持っている
3. Edge(遷移や条件分岐）をつないでグラフを作る
   データをチェックして「次に行く道（ノード）」を決める
"""
from typing import TypedDict
from langgraph.graph import StateGraph, END


# 1. 状態(State)の定義: ノード間で受け渡すデータ構造
class State(TypedDict):
    input_text: str
    processed_text: str
    count: int


# 2. ノード(Node)の定義: 実際の処理を行うPython関数
# 受け取り関数
def start_node(state: State) -> dict:
    print("\n--- [Node 1: Start] 入力を受け取りました ---")
    print(f"  入力文字: {state['input_text']}")

    return {"processed_text": state["input_text"].upper(), "count": 1}

# 文字数チェック関数
def check_length_node(state: State) -> dict:
    print("--- [Node 2: Check] 文字数をチェック中... ---")
    length = len(state["processed_text"])
    print(f"  変換後文字列: {state['processed_text']} (長さ: {length})")

    return {"count": state["count"] + 1}
    # 1) 処理が終わったら、LangGraph が自動的に route_next(state) を実行


# 3. 条件分岐(Conditional Edge)のルーティング関数
def route_next(state: State) -> str:
    # 2) 文字数が 5文字以上なら Finish へ、それ未満なら Warning へ
    if len(state["processed_text"]) >= 5:
        print("  -> 判定: 5文字以上なので完了ノードへ進みます")
        return "finish"
    else:
        print("  -> 判定: 5文字未満なので警告ノードへ進みます")
        return "warning"

def warning_node(state: State) -> dict:
    print("--- [Node 3: Warning] 文字数が短すぎます ---")
    return {"processed_text": state["processed_text"] + "_SHORT"}

def finish_node(state: State) -> dict:
    print("--- [Node 4: Finish] 処理が正常に完了しました ---")
    return {"processed_text": state["processed_text"] + "_OK"}


# 4. グラフの構築
builder = StateGraph(State)

# ノードの追加
builder.add_node("start", start_node)
builder.add_node("check", check_length_node)
builder.add_node("warning", warning_node)
builder.add_node("finish", finish_node)

# エッジの接続
builder.set_entry_point("start")
builder.add_edge("start", "check")

# 条件付きエッジの追加
# 3) LangGraph がマップ辞書 { "finish": "finish", "warning": "warning" } を参照
builder.add_conditional_edges(
    "check",
    route_next,
    {
        # 4)返ってきた "warning" というキーに対応する warning ノード へ自動的に遷移
        "finish": "finish", 
        "warning": "warning"
    }
)

builder.add_edge("warning", END)
builder.add_edge("finish", END)

# グラフのコンパイル
graph = builder.compile()

# 5. 実行テスト
if __name__ == "__main__":
    print("================ テスト 1: 長い文字列 ================")
    result1 = graph.invoke({"input_text": "hello_world", "processed_text": "", "count": 0})
    print("最終結果 1:", result1)

    print("\n================ テスト 2: 短い文字列 ================")
    result2 = graph.invoke({"input_text": "hi", "processed_text": "", "count": 0})
    print("最終結果 2:", result2)