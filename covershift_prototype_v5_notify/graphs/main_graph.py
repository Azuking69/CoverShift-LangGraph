from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from covershift_prototype_V3_listen_notify.config import settings
from covershift_prototype_V3_listen_notify.main_solver import solve_shift

class ShiftState(TypedDict):
    store_id: str
    period: str
    staff_data: list
    shift_requirements: list
    weights: dict
    draft_shift: Optional[dict]
    status: str
    error: Optional[str]

def load_data_node(state: ShiftState) -> ShiftState:
    """ステップ1: スタッフ希望・必要人数の取得"""
    print(f"[Graph] データロード開始: 店舗 {state['store_id']}")
    
    # ダミーサンプルデータ
    staff_data = [
        {"id": "S01", "name": "Aさん", "unpreferred_days": [1]},
        {"id": "S02", "name": "Bさん", "unpreferred_days": []},
        {"id": "S03", "name": "Cさん", "unpreferred_days": [0]}
    ]
    shift_reqs = [
        {"早番": 1, "遅番": 1},
        {"早番": 1, "遅番": 1}
    ]
    
    return {
        **state,
        "staff_data": staff_data,
        "shift_requirements": shift_reqs,
        "weights": state.get("weights") or settings.DEFAULT_WEIGHTS,
        "status": "DATA_LOADED"
    }

def run_solver_node(state: ShiftState) -> ShiftState:
    """ステップ2: ソルバーで案を作成"""
    print("[Graph] シフト解決ソルバー実行")
    result = solve_shift(state["staff_data"], state["shift_requirements"], state["weights"])
    
    if result["status"] == "SUCCESS":
        return {
            **state,
            "draft_shift": result["schedule"],
            "status": "PAUSED_FOR_APPROVAL"
        }
    else:
        return {
            **state,
            "error": result["reason"],
            "status": "FAILED"
        }

# グラフ構築
workflow = StateGraph(ShiftState)
workflow.add_node("load_data", load_data_node)
workflow.add_node("run_solver", run_solver_node)

workflow.set_entry_point("load_data")
workflow.add_edge("load_data", "run_solver")
workflow.add_edge("run_solver", END)

graph_app = workflow.compile()