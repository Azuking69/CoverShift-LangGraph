"""E9(C案): 計算の途中でDBだけが再起動したとき、同じ仕事が二重に計算されないか。V6のE9と同じ条件。
  ソルバーワーカー2台・ダミー計算 EXP_SLEEP 秒(既定45)・キューの見えない時間 30秒。計算開始の5秒後にDBを3秒止める。
  見方: solver_log(計算を始めるたびに1行)に、同じ thread_id・seq の行が2つ以上あれば二重に計算が始まった。
        solver_results は ON CONFLICT DO NOTHING なので、結果が二重に書かれるかも見る。
環境変数: EXP_SLEEP(45) JOB_TIMEOUT_SEC(30) TOTAL_WAIT(120) E5_STOP_CMD / E5_START_CMD
実行: python -m harness_c.run_e9_c"""
import shlex

from harness_c.common_c import *

STOP = shlex.split(os.getenv("E5_STOP_CMD", "docker compose -f docker-compose.proto_c.yml stop db"))
START = shlex.split(os.getenv("E5_START_CMD", "docker compose -f docker-compose.proto_c.yml start db"))
SLEEP = os.getenv("EXP_SLEEP", "45")
TIMEOUT = os.getenv("JOB_TIMEOUT_SEC", "30")
TOTAL_WAIT = int(os.getenv("TOTAL_WAIT", "120"))
ENV = {"EXP_SLEEP": SLEEP, "MOCK_SOLVER_SLEEP": SLEEP, "JOB_TIMEOUT_SEC": TIMEOUT, "VISIBILITY_TIMEOUT_SEC": TIMEOUT}


def db_stop():
    subprocess.run(STOP, cwd=str(ROOT), check=True, capture_output=True)


def db_start():
    subprocess.run(START, cwd=str(ROOT), check=True, capture_output=True)
    return db_wait_ready()


def main():
    print(f"--- E9(C案): 計算の途中でDBが再起動 ---  EXP_SLEEP={SLEEP}秒 キューの見えない時間={TIMEOUT}秒")
    require_clean()
    result = {"system": "C-min", "EXP_SLEEP": SLEEP, "VISIBILITY_TIMEOUT_SEC": TIMEOUT}
    try:
        base = launch_api("e9c_api", 8098, ENV)
        launch_relay("e9c_relay", ENV)
        launch_flow("e9c_flow", ENV)
        launch_solver("e9c_s1", ENV)
        time.sleep(4)
        store = f"e9c-{int(time.time())}"
        r = requests.post(f"{base}/api/v1/shift/start", json={"store_id": store, "period": "2026-10"}, timeout=10)
        tid = r.json()["thread_id"]
        t0 = time.time()
        while time.time() - t0 < 20 and q("SELECT count(*) FROM solver_log WHERE thread_id = %s", (tid,))[0][0] < 1:
            time.sleep(0.25)
        print("1. ソルバー1が計算を始めた。ソルバー2を起動(待機)")
        launch_solver("e9c_s2", ENV)
        time.sleep(5)
        t_stop = time.time()
        db_stop()
        print("2. DBを止めた")
        time.sleep(3)
        ready = db_start()
        print(f"3. DBを起動({ready}秒で受付可能)")
        timeline, done_at, last = [], None, None
        while time.time() - t_stop < TOTAL_WAIT:
            try:
                n = q("SELECT count(*) FROM solver_log WHERE thread_id = %s", (tid,))[0][0]
                res = q("SELECT count(*) FROM solver_results WHERE thread_id = %s", (tid,))[0][0]
            except Exception as e:
                n, res = type(e).__name__, None
            st = run_status(base, tid)
            key = (n, res, st)
            if key != last:
                timeline.append({"t": round(time.time() - t_stop, 1), "solver_log_rows": n, "results_rows": res, "run_status": st})
                last = key
            if st in ("PAUSED_FOR_APPROVAL", "COMPLETED"):
                done_at = round(time.time() - t_stop, 1)
                break
            time.sleep(1)
        time.sleep(3)
        logs = q("SELECT seq, receive_count, worker FROM solver_log WHERE thread_id = %s ORDER BY id", (tid,))
        results = q("SELECT count(*) FROM solver_results WHERE thread_id = %s", (tid,))[0][0]
        double = len(logs) >= 2
        result.update({"thread_id": tid, "finished_at_sec_after_db_stop": done_at, "solver_log": logs,
                       "solver_results_rows": results, "同じ仕事の計算開始が2回以上": double, "timeline_changes": timeline})
        print("\n--- 状態が変わった点 ---")
        for s in timeline:
            print(s)
        print(f"\nsolver_log: {logs}\nsolver_results の行数: {results}")
        print("結論:", "二重に計算が始まった" if double else "二重には始まらなかった")
    finally:
        kill_all()
        try:
            db_start()
        except Exception:
            pass
        save("e9_c_result", result)


if __name__ == "__main__":
    main()