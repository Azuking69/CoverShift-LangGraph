from typing import Dict, List, Any
from ortools.sat.python import cp_model

def solve_shift(staff_list: List[Dict], shift_requirements: List[Dict], weights: Dict[str, float]) -> Dict[str, Any]:
    """
    CP-SAT ソルバーを使用したシフト最適化計算処理
    """
    model = cp_model.CpModel()
    
    days = list(range(len(shift_requirements)))
    shift_types = ["早番", "遅番"]

    # 決定変数 shifts[(staff_id, day, shift_type)]
    shifts = {}
    for staff in staff_list:
        for d in days:
            for s in shift_types:
                shifts[(staff["id"], d, s)] = model.NewBoolVar(f"shift_{staff['id']}_d{d}_{s}")

    # 制約1: 1人1日1シフトまで
    for staff in staff_list:
        for d in days:
            model.Add(sum(shifts[(staff["id"], d, s)] for s in shift_types) <= 1)

    # 制約2: 各シフトに必要な最低人数の確保
    for d, req in enumerate(shift_requirements):
        for s in shift_types:
            min_needed = req.get(s, 0)
            model.Add(sum(shifts[(staff["id"], d, s)] for staff in staff_list) >= min_needed)

    # 目的関数（ソフト制約の最大化ペナルティ）
    objective_terms = []
    w_wishes = int(weights.get("respect_wishes", 0.3) * 100)
    
    for staff in staff_list:
        for d in staff.get("unpreferred_days", []):
            if d < len(days):
                for s in shift_types:
                    # 不可希望日に割り当てられた場合のペナルティ
                    objective_terms.append(-w_wishes * shifts[(staff["id"], d, s)])

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = []
        for d in days:
            day_info = {"day": d + 1, "assignments": {}}
            for s in shift_types:
                workers = [staff["name"] for staff in staff_list if solver.Value(shifts[(staff["id"], d, s)]) == 1]
                day_info["assignments"][s] = workers
            schedule.append(day_info)
        return {"status": "SUCCESS", "schedule": schedule}
    else:
        return {"status": "FAILED", "reason": "条件を満たすシフト案を作成できませんでした"}