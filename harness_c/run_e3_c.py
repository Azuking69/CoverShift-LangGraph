"""E3(C案): ワーカー突然死 → 復旧。V6のE3と同じ流れ(処理8秒・期限10秒・本物の強制終了)。
  1. API・リレー・フロー処理器・ソルバーワーカー1を起動し、1件投入
  2. ソルバーワーカー1が計算を始めたら(solver_log に記録された時点)、強制終了
  3. ソルバーワーカー2を起動し、キューが渡し直して「承認待ち」まで進むまでの秒数と、受信回数を測る
V6では「ワーカー1台がすべて」を担当するので、C案では計算を担当するソルバーワーカーを落とす。
(フロー処理器・リレーを落とす試験は含まれない。)
実行: python -m harness_c.run_e3_c"""
from harness_c.common_c import *

SLEEP = os.getenv("E3_SLEEP", "8")
TIMEOUT = os.getenv("JOB_TIMEOUT_SEC", "10")
ENV = {"EXP_SLEEP": SLEEP, "MOCK_SOLVER_SLEEP": SLEEP, "JOB_TIMEOUT_SEC": TIMEOUT, "VISIBILITY_TIMEOUT_SEC": TIMEOUT}


def main():
    print("--- E3(C案): ソルバーワーカー突然死・復旧テスト(本物の強制終了) ---")
    print(f"設定: 処理{SLEEP}秒 / 期限(キューの見えない時間){TIMEOUT}秒")
    require_clean()
    result = {"system": "C-min", "sleep_sec": SLEEP, "timeout_sec": TIMEOUT, "passed": False}
    try:
        base = launch_api("e3_api", 8099, ENV)
        launch_relay("e3_relay", ENV)
        launch_flow("e3_flow", ENV)
        w1 = launch_solver("e3_solver1", ENV)
        time.sleep(3)
        store = f"e3-{int(time.time())}"
        r = requests.post(f"{base}/api/v1/shift/start", json={"store_id": store, "period": "2026-10"})
        if r.status_code != 202:
            raise SystemExit(f"[エラー] 投入に失敗 (HTTP {r.status_code}): {r.text}")
        tid = r.json()["thread_id"]
        print(f"1. 投入成功 thread_id={tid}")
        started = False
        for _ in range(80):
            if q("SELECT count(*) FROM solver_log WHERE thread_id = %s", (tid,))[0][0] >= 1:
                started = True
                break
            time.sleep(0.25)
        if not started:
            raise SystemExit("[エラー] ソルバーワーカーが計算を始めたのを捕まえられませんでした。logs/e3_*.log を見てください。")
        time.sleep(1)
        print(f"2. ソルバーワーカー1が計算中: {q('SELECT seq, receive_count, worker FROM solver_log WHERE thread_id = %s', (tid,))}")
        w1.kill()
        w1.wait()
        print("3. ソルバーワーカー1を強制終了しました")
        print(f"   強制終了直後の状態: {run_status(base, tid)}")
        t0 = time.time()
        launch_solver("e3_solver2", ENV)
        print("4. ソルバーワーカー2を起動。キューが渡し直して承認待ちまで進むのを待ちます(最大70秒)...")
        final = None
        while time.time() - t0 < 70:
            st = run_status(base, tid)
            if st in ("PAUSED_FOR_APPROVAL", "COMPLETED"):
                final = st
                break
            time.sleep(0.5)
        secs = round(time.time() - t0, 1)
        logs = q("SELECT seq, receive_count, worker FROM solver_log WHERE thread_id = %s ORDER BY id", (tid,))
        max_rc = max([r[1] for r in logs], default=None)
        result.update({"thread_id": tid, "seconds_after_restart": secs if final else None, "final_status": final,
                       "solver_log": logs, "max_receive_count": max_rc})
        if final and max_rc and max_rc >= 2:
            result["passed"] = True
            print(f"\n[成功] 再起動後 {secs} 秒で {final} まで進みました。受信回数={max_rc}(2以上＝渡し直された証拠)")
        elif final:
            print(f"\n[要確認] 状態は進みましたが受信回数={max_rc}です。突然死前に完了していた可能性があります。")
        else:
            print(f"\n[失敗] 70秒待っても進みませんでした。 solver_log={logs}")
    finally:
        kill_all()
        save("e3_c_result", result)


if __name__ == "__main__":
    main()
