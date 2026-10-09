"""
V1(初期プロトタイプ)の中身だけで、本物のCP-SATソルバーを試す。(あなたのPCで実行する)

やること:
  A. ソルバーだけの計算時間(人数×日数を変えて、各3回)
  B. V1のAPI(/start → /resume)に本物のソルバーを差し込んで、動くか・何秒かかるか
     ※ V1のファイルは1つも書き換えない(実行中だけ、メモリ上で差し替える)

使い方(PowerShell):
  pip install ortools httpx            # 無ければ
  python run_v1_solver_real.py "V1の親フォルダ"
     「V1の親フォルダ」= covershift_prototype フォルダが入っているフォルダ
     (省略すると、このファイルがあるフォルダ・その親から探す)
  このファイルと real_solver.py は、同じフォルダに置く。
結果: v1_solver_real_result.json
"""
import json, os, platform, statistics, sys, time
from typing import Any
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = os.getenv("PKG1", "covershift_prototype")


def find_root():
    cands = [Path(sys.argv[1])] if len(sys.argv) > 1 else [HERE, HERE.parent, Path.cwd()]
    for c in cands:
        if (c / PKG / "graphs" / "main_graph.py").is_file():
            return c.resolve()
    raise SystemExit(f"[エラー] '{PKG}' フォルダが見つかりません。引数にV1の親フォルダを指定してください。")


ROOT = find_root()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import ortools  # noqa: E402
import real_solver  # noqa: E402

res: dict[str, Any] = {"env": {"os": platform.platform(), "python": platform.python_version(), "ortools": ortools.__version__,
               "cpu_count": os.cpu_count(), "v1_root": str(ROOT)}}
print("--- V1 + 本物のCP-SAT ---")
print("環境:", res["env"])

# A. ソルバーだけ
print("\n[A] ソルバーだけの計算時間(各3回。秒)")
rows = []
for n, d in [(5, 7), (10, 14), (10, 30), (15, 30), (20, 30), (30, 30)]:
    staff, reqs = real_solver.sample_input(n, d)
    ts, st = [], None
    for _ in range(3):
        t = time.perf_counter()
        r = real_solver.solve_shift(staff, reqs, {"respect_wishes": 0.3}, 10.0)
        ts.append(time.perf_counter() - t)
        st = r["status"]
    row = {"staff": n, "days": d, "status": st, "min": round(min(ts), 3), "median": round(statistics.median(ts), 3), "max": round(max(ts), 3)}
    rows.append(row)
    print(" ", row)
res["A_solver_only"] = rows

# B. V1のAPIに差し込む
print("\n[B] V1のAPI(/start → /resume)に差し込む")
from fastapi.testclient import TestClient  # noqa: E402
import covershift_prototype.graphs.main_graph as g  # noqa: E402
from covershift_prototype.main import app  # noqa: E402

orig = g.generate_shift_schedule
g.generate_shift_schedule = real_solver.generate_shift_schedule  # メモリ上だけの差し替え
c = TestClient(app)
b = []
try:
    for n, d in [(5, 7), (20, 30)]:
        os.environ["SOLVER_STAFF"], os.environ["SOLVER_DAYS"] = str(n), str(d)
        for rep in range(3):
            tid = f"pc-{n}x{d}-{rep}"
            t = time.perf_counter(); r1 = c.post("/api/v1/shift/start", json={"store_id": tid}); s_sec = time.perf_counter() - t
            js = r1.json()
            t = time.perf_counter(); r2 = c.post("/api/v1/shift/resume", json={"thread_id": js.get("thread_id", tid + "-session"), "approved": True}); r_sec = time.perf_counter() - t
            row = {"staff": n, "days": d, "rep": rep, "start_http": r1.status_code, "start_sec": round(s_sec, 3),
                   "start_status": js.get("status"), "draft_head": str(js.get("draft_shift"))[:60],
                   "resume_http": r2.status_code, "resume_sec": round(r_sec, 3), "resume_status": r2.json().get("status")}
            b.append(row)
            print(" ", row)
finally:
    g.generate_shift_schedule = orig
res["B_v1_api"] = b

out = HERE / "v1_solver_real_result.json"
out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n結果:", out)
print("注意: 入力は試験用の自動生成(必要人数は仮の値)。実店舗のデータ・実際の制約ではない。")