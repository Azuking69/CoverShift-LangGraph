from ortools.sat.python import cp_model

def solve_shift_optimization(store_id: str, target_month: str) -> dict:
    """
    OR-Tools CP-SAT を使用したシフト最適化計算エンジン
    """
    model = cp_model.CpModel()
    
    employees = ["Alice", "Bob", "Charlie", "David"]
    days = 7
    shifts = {}
    
    for e in employees:
        for d in range(days):
            shifts[(e, d)] = model.NewBoolVar(f"shift_{e}_{d}")
            
    # 制約: 各日最低2名の出勤が必要
    for d in range(days):
        model.Add(sum(shifts[(e, d)] for e in employees) >= 2)
        
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    status = solver.Solve(model)
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = {}
        for e in employees:
            schedule[e] = [bool(solver.Value(shifts[(e, d)])) for d in range(days)]
        return {
            "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
            "schedule": schedule,
            "assigned_total": sum(solver.Value(shifts[(e, d)]) for e in employees for d in range(days))
        }
    else:
        return {"status": "INFEASIBLE", "schedule": {}}