"""
V1(初期プロトタイプ)を実際に起動して、ダミーのソルバーと本物のCP-SATを比べる。
  - V1のAPIを uvicorn で起動 → /start → /resume をHTTPで10回ずつ叩き、秒数を記録
  - 同時に「待たされている間、別の要求(GET /)が通るか」も見る(計算中にAPIが固まるかの確認)
  - 設定 SOLVER=mock(ダミー) と SOLVER=cpsat(本物)を、順に試す
V1のフォルダの中だけで完結する(V1に real_solver.py を置き、main_graph.py の import を切り替え式にした前提)。

使い方(PowerShell。LangGraphフォルダで):
    pip install ortools requests uvicorn
    python harness\\run_v1_http.py ["V1の親フォルダ"]     (約1分)
結果: harness\\v1_http_result.json
"""
import json, os, platform, statistics, subprocess, sys, threading, time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
PKG = os.getenv("PKG1", "covershift_prototype")
PORT = int(os.getenv("V1_PORT", "8201"))
BASE = f"http://127.0.0.1:{PORT}"


def find_root():
    cands = [Path(sys.argv[1])] if len(sys.argv) > 1 else [HERE, HERE.parent, Path.cwd()]
    for c in cands:
        if (c / PKG / "graphs" / "main_graph.py").is_file():
            return c.resolve()
    raise SystemExit(f"[エラー] '{PKG}' フォルダが見つかりません。引数にV1の親フォルダを指定してください。")


ROOT = find_root()
if not (ROOT / PKG / "solver" / "real_solver.py").is_file():
    raise SystemExit("[エラー] V1の solver フォルダに real_solver.py がありません。")
if "SOLVER" not in (ROOT / PKG / "graphs" / "main_graph.py").read_text(encoding="utf-8"):
    raise SystemExit("[エラー] main_graph.py の import が、まだ切り替え式になっていません(SOLVER の記述なし)。")


def kill(p):
    if p.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        else:
            p.kill()


def start_server(env_extra):
    env = os.environ.copy()
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT)})
    env.update({k: str(v) for k, v in env_extra.items()})
    log = open(HERE / "v1_http_server.log", "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", f"{PKG}.main:app", "--port", str(PORT)],
                         cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(160):
        try:
            requests.get(BASE + "/", timeout=1)
            return p
        except Exception:
            time.sleep(0.25)
    kill(p)
    raise SystemExit("[エラー] V1のAPIが起動しません。harness\\v1_http_server.log を見てください。")


def summarize(xs):
    xs = sorted(xs)
    return {"n": len(xs), "min": round(xs[0], 3), "median": round(statistics.median(xs), 3), "max": round(xs[-1], 3)}


def run_case(label, env_extra, reps=10):
    p = start_server(env_extra)
    try:
        starts, resumes, codes = [], [], []
        # 計算中に別の要求が通るかを見る監視(1回目の /start の間、GET / を繰り返す)
        gets = []
        stop = threading.Event()

        def watcher():
            while not stop.is_set():
                t = time.perf_counter()
                try:
                    requests.get(BASE + "/", timeout=20)
                    gets.append(time.perf_counter() - t)
                except Exception:
                    gets.append(float("inf"))
                time.sleep(0.02)

        th = threading.Thread(target=watcher, daemon=True)
        th.start()
        for i in range(reps):
            tid = f"{label}-{int(time.time())}-{i}"
            t = time.perf_counter(); r = requests.post(f"{BASE}/api/v1/shift/start", json={"store_id": tid}, timeout=120); starts.append(time.perf_counter() - t)
            js = r.json()
            t = time.perf_counter(); r2 = requests.post(f"{BASE}/api/v1/shift/resume", json={"thread_id": js.get("thread_id", tid + "-session"), "approved": True}, timeout=120); resumes.append(time.perf_counter() - t)
            codes.append([r.status_code, r2.status_code, js.get("status"), r2.json().get("status")])
        stop.set(); th.join(timeout=3)
        finite = [g for g in gets if g != float("inf")]
        out = {"start_sec": summarize(starts), "resume_sec": summarize(resumes),
               "http_codes_ok": all(c[0] == 200 and c[1] == 200 for c in codes),
               "last": codes[-1], "draft_example": js.get("draft_shift", "")[:60],
               "GET_during": {"n": len(gets), "max_sec": round(max(finite), 3) if finite else None, "failed": len(gets) - len(finite)}}
        print(f"[{label}] /start {out['start_sec']} / /resume {out['resume_sec']} / 全部200: {out['http_codes_ok']}")
        print(f"        計算中のGET /: {out['GET_during']}")
        return out
    finally:
        kill(p)
        time.sleep(1)


res = {"env": {"os": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(), "v1_root": str(ROOT)}}
try:
    import ortools
    res["env"]["ortools"] = ortools.__version__
except Exception as e:
    raise SystemExit(f"[エラー] ortools が入っていません: pip install ortools ({e})")
print("--- V1(初期プロトタイプ) ダミー vs 本物のCP-SAT ---")
print("環境:", res["env"])
res["cases"] = {}
res["cases"]["mock(ダミー)"] = run_case("mock", {"SOLVER": "mock"})
res["cases"]["cpsat 5人x7日"] = run_case("c5x7", {"SOLVER": "cpsat", "SOLVER_STAFF": 5, "SOLVER_DAYS": 7})
res["cases"]["cpsat 20人x30日"] = run_case("c20x30", {"SOLVER": "cpsat", "SOLVER_STAFF": 20, "SOLVER_DAYS": 30})
(HERE / "v1_http_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n結果: harness\\v1_http_result.json")
print("注意: 入力は試験用の自動生成(必要人数は仮の値)。実店舗のデータ・実際の制約ではない。")