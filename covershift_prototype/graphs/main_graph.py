# covershift_prototype/graphs/main_graph.py
"""
役割: シフト生成やAI解説、承認フローといった「核心的な処理(ワークフロー)」を担当する「作業場」
やること: ノード間の遷移、interrupt() による承認制御、状態(State)の更新など、LangGraph のロジックそのものを保持
"""
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
from covershift_prototype.schemas import CoverShiftState
from covershift_prototype.solver.mock_solver import generate_shift_schedule

# S1: ソルバーでシフト計算
def node_solver(state: CoverShiftState) -> dict:
    res = generate_shift_schedule(state["store_id"])
    
    return {
        "status": "S1_生成完了",
        "draft_shift": res["draft_shift"],
        "raw_input_names": res["raw_input_names"]
    }

# S2-S4: AI解説文生成
def node_explain(state: CoverShiftState) -> dict:
    raw_names = state.get("raw_input_names", {})
    explanation = "人件費最適化のため、スタッフAを早番に配置しました。"
    
    # 仮名から実名への置換復元
    for pseudo_id, real_name in raw_names.items():
        explanation = explanation.replace(pseudo_id, real_name)
        
    return {
        "status": "S4_説明生成完了",
        "llm_explanation": explanation
    }

# S5: 店長承認待ち (interrupt)
def node_manager_review(state: CoverShiftState) -> dict:
    approved = interrupt({
        "message": "シフト案とAI解説を確認し、承認してください。",
        "draft": state["draft_shift"],
        "explanation": state.get("llm_explanation")
    })

    return {
        "manager_approved": approved,
        "status": "S5_確認完了"
    }


# S6: シフト確定保存
def node_finalize(state: CoverShiftState) -> dict:
    return {"status": "S6_確定済み"}


# 承認/拒否によるルーティング関数
def route_after_review(state: CoverShiftState) -> str:
    if state.get("manager_approved"):
        return "finalize"
    
    return "solver" # 拒否された場合は再計算(solver)へ


# グラフ構築
builder = StateGraph(CoverShiftState)
builder.add_node("solver", node_solver)
builder.add_node("explain", node_explain)
builder.add_node("manager_review", node_manager_review)
builder.add_node("finalize", node_finalize)
builder.set_entry_point("solver")
builder.add_edge("solver", "explain")
builder.add_edge("explain", "manager_review")

builder.add_conditional_edges(
    "manager_review",
    route_after_review,
    {
        "finalize": "finalize",
        "solver": "solver"
    }
)
builder.add_edge("finalize", END)


# チェックポインターの登録
checkpointer = MemorySaver()
covershift_graph = builder.compile(checkpointer=checkpointer)