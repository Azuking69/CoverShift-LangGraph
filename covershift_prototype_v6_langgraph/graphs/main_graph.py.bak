"""
役割: シフト生成・AI解説・承認フローという「核心的な処理(ワークフロー)」を持つ。
v2の変更:
  - グラフを build_graph(checkpointer) で組み立てる形にした。
    (v1は import した瞬間に MemorySaver で組み立てていた → 再起動で消える・APIと同じプロセスになる)
  - 却下の回数を retry_count に数え、MAX_REJECTS で打ち切る。
    (v1は却下すると無限に solver に戻れた)
"""
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt

from ..config import MAX_REJECTS
from ..schemas import CoverShiftState
from ..solver.mock_solver import generate_shift_schedule


def node_solver(state: CoverShiftState) -> dict:
    result = generate_shift_schedule(state["store_id"])
    return {
        "status": "S1_生成完了",
        "draft_shift": result["draft_shift"],
        "raw_input_names": result["raw_input_names"],
    }


def node_explain(state: CoverShiftState) -> dict:
    # 本物ではここで名前を記号に替えてAIを呼び、あとで実名に戻す(今はダミー文)。
    text = "人件費最適化のため、スタッフAを早番に配置しました。"
    for pseudo, real in state.get("raw_input_names", {}).items():
        text = text.replace(pseudo, real)
    return {"status": "S4_説明生成完了", "llm_explanation": text}


def node_manager_review(state: CoverShiftState) -> dict:
    # 注意: 再開のとき、このノードは最初から実行し直される。
    # interrupt() より前に「副作用のあること(送信・保存)」を書かないこと。
    approved = interrupt(
        {
            "message": "シフト案とAI解説を確認し、承認してください。",
            "draft": state.get("draft_shift"),
            "explanation": state.get("llm_explanation"),
        }
    )
    retry = state.get("retry_count", 0) + (0 if approved else 1)
    return {"manager_approved": bool(approved), "status": "S5_確認完了", "retry_count": retry}


def node_finalize(state: CoverShiftState) -> dict:
    return {"status": "S6_確定済み"}


def route_after_review(state: CoverShiftState) -> str:
    if state.get("manager_approved"):
        return "finalize"
    if state.get("retry_count", 0) >= MAX_REJECTS:
        return "give_up"
    return "solver"


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
    {"finalize": "finalize", "solver": "solver", "give_up": END},
)
builder.add_edge("finalize", END)


def build_graph(checkpointer):
    """チェックポイント保存先(PostgresSaver)を渡して、実行できるグラフを返す。"""
    return builder.compile(checkpointer=checkpointer)
