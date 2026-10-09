"""
本物のCP-SAT(OR-Tools)のソルバー。V2の元の solve_shift と同じ中身。
mock_solver.py と同じ generate_shift_schedule(store_id) を持つので、main_graph.py の import を切り替えるだけで使える。
入力(人数・日数)は試験用の自動生成。環境変数 SOLVER_STAFF / SOLVER_DAYS / SOLVER_MAX_SEC で変える。
※必要人数は仮の値で、実店舗のデータ・実際の制約ではない。
"""
import os, time
from typing import Dict, List, Any
from ortools.sat.python import cp_model


def solve_shift(staff_list: List[Dict], shift_requirements: List[Dict], weights: Dict[str, float], max_sec: float = 5.0) -> Dict[str, Any]:
    model = cp_model.CpModel()
    days = list(range(len(shift_requirements)))
    shift_types = ["早番", "遅番"]
    shifts = {}
    for staff in staff_list:
        for d in days:
            for s in shift_types:
                shifts[(staff["id"], d, s)] = model.new_bool_var(f"shift_{staff['id']}_d{d}_{s}")
    for staff in staff_list:
        for d in days:
            model.add(sum(shifts[(staff["id"], d, s)] for s in shift_types) <= 1)
    for d, req in enumerate(shift_requirements):
        for s in shift_types:
            model.add(sum(shifts[(st["id"], d, s)] for st in staff_list) >= req.get(s, 0))
    w = int(weights.get("respect_wishes", 0.3) * 100)
    terms = []
    for staff in staff_list:
        for d in staff.get("unpreferred_days", []):
            if d < len(days):
                for s in shift_types:
                    terms.append(-w * shifts[(staff["id"], d, s)])
    model.maximize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_sec
    status = solver.solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = []
        for d in days:
            info = {"day": d + 1, "assignments": {}}
            for s in shift_types:
                info["assignments"][s] = [st["name"] for st in staff_list if solver.value(shifts[(st["id"], d, s)]) == 1]
            schedule.append(info)
        return {"status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE", "schedule": schedule, "wall": solver.wall_time}
    return {"status": "INFEASIBLE" if status == cp_model.INFEASIBLE else "TIMEOUT_NO_SOLUTION", "schedule": [], "wall": solver.wall_time}


def sample_input(n_staff: int, n_days: int):
    """試験用の入力。人数・日数だけを変える。必要人数は『出勤可能人数の約4割』を早番・遅番に半分ずつ(推測の設定。実店舗の値ではない)。"""
    staff = [{"id": f"s{i}", "name": f"スタッフ{i}", "unpreferred_days": [d for d in range(n_days) if (i + d) % 5 == 0]} for i in range(n_staff)]
    need = max(1, int(n_staff * 0.4) // 2)
    reqs = [{"早番": need, "遅番": need} for _ in range(n_days)]
    return staff, reqs


def generate_shift_schedule(store_id: str) -> Dict[str, Any]:
    n_staff = int(os.getenv("SOLVER_STAFF", "10"))
    n_days = int(os.getenv("SOLVER_DAYS", "14"))
    staff, reqs = sample_input(n_staff, n_days)
    res = solve_shift(staff, reqs, {"respect_wishes": 0.3}, float(os.getenv("SOLVER_MAX_SEC", "5")))
    first = res["schedule"][0]["assignments"] if res["schedule"] else {}
    text = f"[{res['status']}] day1 早番:{','.join(first.get('早番', []))} 遅番:{','.join(first.get('遅番', []))}"
    return {"draft_shift": text, "raw_input_names": {}}