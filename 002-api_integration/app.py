# 002-api_integration/app.py
"""
[FastAPI × LangGraph 連携サーバー]
教授からの質問に対する実装解答:
- /api/shift/start  : HTTPリクエストを受けて LangGraph を起動。S5 (店長確認) で interrupt して停止
- /api/shift/resume : 店長が画面で承認ボタンを押すと、Command(resume=...) で途中から再開
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

# app: FastAPI インスタンスの作成
app = FastAPI(title="CoverShift LangGraph API Demo")

# ----------------------------------------------------
# 1. LangGraph の定義
# ----------------------------------------------------
class ShiftState(dict):
    """シフト作成状態"""
    store_id: str
    status: str
    draft_shift: str
    manager_approved: Optional[bool]

# S1: シフト案の自動生成 (CP-SATソルバー等のモック)
def node_generate_shift(state: ShiftState) -> dict:
    print(f"\n[Graph] 店舗 {state['store_id']} のシフト初案を生成中...")

    return {
        "status": "S1_生成完了",
        "draft_shift": "10/02(金) Aさん: 早番, Bさん: 遅番"
    }

# S5: 店長承認待ち (interrupt で一時停止)
def node_manager_review(state: ShiftState) -> dict:
    print("\n[Graph] 店長確認待ち(S5)に入りました。")
    print(" ⏸️ [interrupt()] グラフ実行を一時停止し、FastAPI に制御を戻します。")
    
    # 承認待ちで一時停止
    user_approval = interrupt({
        "message": "作成されたシフト案を確認し、承認(True)または拒否(False)を選択してください",
        "draft": state["draft_shift"]
    })
    
    print(f"\n ➡️ [resume] 再開されました！ 店長の入力値: {user_approval}")

    return {
        "manager_approved": user_approval,
        "status": "S5_確認完了"
    }


# S6: 最終確定 (承認済みなら確定、拒否なら再生成)
def node_finalize_shift(state: ShiftState) -> dict:
    print("\n[Graph] シフトを確定保存し、全員に通知を送信します。")

    return {"status": "S6_確定済み"}


# グラフ構築
builder = StateGraph(ShiftState)
builder.add_node("generate_shift", node_generate_shift)
builder.add_node("manager_review", node_manager_review)
builder.add_node("finalize_shift", node_finalize_shift)

builder.set_entry_point("generate_shift")
builder.add_edge("generate_shift", "manager_review")
builder.add_edge("manager_review", "finalize_shift")
builder.add_edge("finalize_shift", END)

# チェックポインター（状態の保存領域）
# 本番では PostgreSQL (PostgresSaver) を使いますが、デモ用には MemorySaver を使用
checkpointer = MemorySaver()
shift_graph = builder.compile(checkpointer=checkpointer)


# ----------------------------------------------------
# 2. FastAPI リクエスト / レスポンスの型定義
# ----------------------------------------------------
class StartRequest(BaseModel):
    store_id: str

class ResumeRequest(BaseModel):
    thread_id: str
    approved: bool


# ----------------------------------------------------
# 3. API エンドポイント
# ----------------------------------------------------

"""
【1回目のリクエスト】
シフト生成を開始し、S5 (店長確認 waiting) の interrupt で一時停止した状態でレスポンスを返す
"""
@app.post("/api/shift/start")
def start_shift_process(req: StartRequest):

    # スレッドID（セッションID）を生成（例: store-001-thread）
    thread_id = f"{req.store_id}-session"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "store_id": req.store_id,
        "status": "S0_開始",
        "draft_shift": "",
        "manager_approved": None
    }

    # グラフ実行 (interrupt() の地点で一時停止して invoke が終了する)
    current_state = shift_graph.invoke(initial_state, config)

    # 現在のチェックポイント状態を取得して、interrupt 情報を取得
    state_snapshot = shift_graph.get_state(config)
    
    return {
        "status": "PAUSED_FOR_APPROVAL",
        "thread_id": thread_id,
        "current_status": current_state.get("status"),
        "draft_shift": current_state.get("draft_shift"),
        "next_step": state_snapshot.next, # 次に実行される予定のノード
        "interrupt_info": state_snapshot.tasks[0].interrupts[0].value if state_snapshot.tasks else None
    }


"""
【2回目のリクエスト】
店長が画面で承認/拒否ボタンを押した時に叩くAPI。
Command(resume=...) で中断した LangGraph を途中から再開する
"""
@app.post("/api/shift/resume")
def resume_shift_process(req: ResumeRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    # 指定されたスレッドIDの状態が存在するか確認
    state_snapshot = shift_graph.get_state(config)
    if not state_snapshot.next:
        raise HTTPException(status_code=400, detail="指定された thread_id の停止中プロセスが存在しないか、既に完了しています。")

    # Command(resume=店長の選択結果) を与えて途中から再開！
    final_state = shift_graph.invoke(Command(resume=req.approved), config)

    return {
        "status": "COMPLETED",
        "thread_id": req.thread_id,
        "final_status": final_state.get("status"),
        "manager_approved": final_state.get("manager_approved"),
        "draft_shift": final_state.get("draft_shift")
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)