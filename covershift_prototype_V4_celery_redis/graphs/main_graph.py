from typing import Dict, Any, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver

# solver から関数をインポート
from covershift_prototype_V4_celery_redis.solver.main_solver import solve_shift_optimization

class ShiftState(TypedDict):
    thread_id: str
    store_id: str
    target_month: str
    shift_plan: Dict[str, Any]
    approved: bool
    status: str

def generate_shift_node(state: ShiftState) -> Dict[str, Any]:
    print(f"📊 [LangGraph] CP-SAT最適化計算開始 (Thread={state['thread_id']})")
    result = solve_shift_optimization(state.get("store_id", "store001"), state.get("target_month", "2026-10"))
    return {
        "shift_plan": result,
        "status": "DRAFTED"
    }

def approval_interrupt_node(state: ShiftState) -> Dict[str, Any]:
    print(f"⏸️ [LangGraph] 店長承認待ち (HITL Interrupt) で停止中...")
    approval_data = interrupt({"message": "店長承認が必要です", "plan": state.get("shift_plan")})
    is_approved = approval_data.get("approved", False)
    return {
        "approved": is_approved,
        "status": "APPROVED" if is_approved else "REJECTED"
    }

def finalize_node(state: ShiftState) -> Dict[str, Any]:
    final_status = "COMPLETED" if state.get("approved") else "REJECTED"
    print(f"✅ [LangGraph] 確定処理完了: 最終ステータス={final_status}")
    return {"status": final_status}

builder = StateGraph(ShiftState)
builder.add_node("generate_shift", generate_shift_node)
builder.add_node("approval_interrupt", approval_interrupt_node)
builder.add_node("finalize", finalize_node)

builder.add_edge(START, "generate_shift")
builder.add_edge("generate_shift", "approval_interrupt")
builder.add_edge("approval_interrupt", "finalize")
builder.add_edge("finalize", END)

# チェックポインターを指定してコンパイル
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)