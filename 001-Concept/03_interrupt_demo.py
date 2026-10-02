# 001-Concept/03_interrupt_demo.py
"""
[interrupt / Command(resume) 動作検証デモ]
教授からの質問に対するコア概念の証明:
1. 途中のノードで interrupt() を呼び出すと、グラフの実行が一時停止する
2. 呼び出し元(invoke)に制御が戻り、状態が保存(Checkpoint)される
3. 再度 Command(resume=値) を与えて invoke すると、停止した場所から再開する
"""
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver


# 1. State の定義
class DemoState(TypedDict):
    status: str
    user_approval: bool


# 2. ノード関数の定義
def step_1_node(state: DemoState) -> dict:
    print("\n[Node 1] シフト初案を作成中...")
    return {"status": "S1_作成完了"}

def step_2_node(state: DemoState) -> dict:
    print("\n[Node 2] 店長の確認待ちに入ります。")
    print(" ⏸️  [interrupt] ここで LangGraph の実行が一時停止します！")
    
    # interrupt: 人間の介入（承認）を待つために一時停止
    # 引数の辞書は画面側に渡すメッセージ等のデータ
    approved = interrupt({
        "message": "このシフト案を承認しますか？ (True/False)"
    })
    
    # resume されると、ここから処理が再開されます！
    print(f"\n ➡️  [resume] 再開されました！ 受け取った入力値: {approved}")
    return {"user_approval": approved, "status": "S5_確認完了"}


def step_3_node(state: DemoState) -> dict:
    print("\n[Node 3] DBに保存してシフト確定。")
    return {"status": "S6_確定"}


# 3. グラフ構築
builder = StateGraph(DemoState)
builder.add_node("step_1", step_1_node)
builder.add_node("step_2", step_2_node)
builder.add_node("step_3", step_3_node)

builder.set_entry_point("step_1")
builder.add_edge("step_1", "step_2")
builder.add_edge("step_2", "step_3")
builder.add_edge("step_3", END)


# チェックポインター（状態の永続化領域）の登録
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)


# 4. 実行デモ
if __name__ == "__main__":
    # セッション識別用の thread_id を設定
    config = {"configurable": {"thread_id": "demo-session-1"}}
    
    print("==================================================")
    print(" 1回目の呼び出し: 処理スタート")
    print("==================================================")
    res_1 = graph.invoke({"status": "S0", "user_approval": False}, config)
    print("\n[1回目終了] 現在のステータス:", res_1.get("status"))
    
    print("\n--------------------------------------------------")
    print(" ⏸️ (プログラムは一時停止中。店長が画面で承認を押すのを待ちます)")
    print("--------------------------------------------------\n")
    
    print("==================================================")
    print(" 2回目の呼び出し: 中断場所から再開 (Command で resume)")
    print("==================================================")
    # Command(resume=True) を渡すことで、interrupt() の戻り値として True が入って再開する
    res_2 = graph.invoke(Command(resume=True), config)
    
    print("\n==================================================")
    print(" 【最終結果】")
    print("最終ステータス:", res_2.get("status"))
    print("承認結果:", res_2.get("user_approval"))
    print("==================================================")