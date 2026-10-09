"""重い計算の代わり(試験専用)。CP-SATで、わざと時間のかかる問題を解く。"""
import random
import time
from ortools.sat.python import cp_model


def heavy_solve(max_sec: float = 8.0, n_staff: int = 60, n_days: int = 30, seed: int = 1) -> float:
    rnd = random.Random(seed)
    m = cp_model.CpModel()
    x = {(s, d, k): m.new_bool_var(f"x{s}_{d}_{k}") for s in range(n_staff) for d in range(n_days) for k in range(2)}
    for s in range(n_staff):
        for d in range(n_days):
            m.add(sum(x[s, d, k] for k in range(2)) <= 1)
        for d in range(n_days - 6):  # 7日のうち働くのは5日まで
            m.add(sum(x[s, dd, k] for dd in range(d, d + 7) for k in range(2)) <= 5)
        for d in range(n_days - 1):  # 遅番の翌日に早番は入れない
            m.add(x[s, d, 1] + x[s, d + 1, 0] <= 1)
    for d in range(n_days):
        for k in range(2):
            m.add(sum(x[s, d, k] for s in range(n_staff)) >= n_staff // 5)
    m.minimize(sum(rnd.randint(1, 100) * v for v in x.values()))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = max_sec
    sv.parameters.num_workers = 1
    t = time.time()
    sv.solve(m)
    return time.time() - t


if __name__ == "__main__":
    print(round(heavy_solve(), 2), "秒")
