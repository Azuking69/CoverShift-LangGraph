"""
E9: 計算の途中でDBだけが再起動したとき、同じ仕事が二重に計算されないか(V6の新しい確認)

背景: advisory lock は「DB接続」に付く。DBが再起動すると接続が切れ、ロックが外れる。
      元のワーカーは計算を続けているのに、期限(JOB_TIMEOUT_SEC)後に別のワーカーが同じ仕事を取れるかもしれない。
やること:
  1. API、ワーカー1を起動 → 仕事を1件入れる(ダミーの計算は EXP_SLEEP 秒かかる)
  2. 仕事が RUNNING になったら、ワーカー2を起動(待機)
  3. 5秒後にDBを止めて、3秒後に起動し直す(計算は途中)
  4. そこから最長 TOTAL_WAIT 秒、1秒ごとに「仕事の状態・attempts・advisoryロックの数」を記録
  5. 最後に、各ワーカーのログで「同じ Job ID の処理開始」が何回、どのワーカーで起きたかを数える

見方: 2つのワーカーが同じJob IDの「処理開始」を出していたら、二重に計算された(=Opusの指摘が当たっている)。
環境変数: EXP_SLEEP(既定45) JOB_TIMEOUT_SEC(既定30) TOTAL_WAIT(既定120)
          E5_STOP_CMD / E5_START_CMD (DBの止め方・起動のしかた。E5と同じ)
実行: python -m harness_v6real.run_e9_dbrestart_midjob     (約2分)
"""
import re
import shlex

from harness_v6real.real_common import *

STOP = shlex.split(os.getenv("E5_STOP_CMD", "docker compose -f docker-compose.proto.yml stop db"))
START = shlex.split(os.getenv("E5_START_CMD", "docker compose -f docker-compose.proto.yml start db"))
SLEEP = os.getenv("EXP_SLEEP", "45")
TIMEOUT = os.getenv("JOB_TIMEOUT_SEC", "30")
TOTAL_WAIT = int(os.getenv("TOTAL_WAIT", "120"))


def db_stop():
    subprocess.run(STOP, cwd=str(ROOT), check=True, capture_output=True)


def db_start():
    subprocess.run(START, cwd=str(ROOT), check=True, capture_output=True)
    return db_wait_ready()


def snap(tid):
    try:
        j = q("SELECT status, attempts FROM jobs WHERE thread_id = %s ORDER BY id DESC LIMIT 1", (tid,))
        locks = q("SELECT count(*) FROM pg_locks WHERE locktype='advisory'")
        return {"job": j[0][0] if j else None, "attempts": j[0][1] if j else None, "advisory_locks": locks[0][0]}
    except Exception as e:
        return {"error": type(e).__name__}


def starts(name):
    try:
        txt = (LOGDIR / f"{name}.log").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    return re.findall(r"ジョブ検知・処理開始: Job ID=(\d+).*?試行=(\d+)", txt)


def retired(name):
    """世代番号の確認で「引き下がった」回数(v6_gen用。v6_minでは常に0)"""
    try:
        txt = (LOGDIR / f"{name}.log").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 0
    return txt.count("世代が古いので引き下がります")


def main():
    print(f"--- E9: 計算の途中でDBが再起動 ---  EXP_SLEEP={SLEEP}秒 JOB_TIMEOUT_SEC={TIMEOUT}秒")
    require_clean()
    result: dict = {"EXP_SLEEP": SLEEP, "JOB_TIMEOUT_SEC": TIMEOUT}
    env = {"EXP_SLEEP": SLEEP, "MOCK_SOLVER_SLEEP": SLEEP, "JOB_TIMEOUT_SEC": TIMEOUT}
    sid = f"e9-{int(time.time())}"
    tid = f"{sid}-2026-10"
    try:
        base = launch_api("e9_api", 8097, env)
        launch_worker("e9_w1", env)
        time.sleep(6)
        requests.post(f"{base}/api/v1/shift/start", json={"store_id": sid, "period": "2026-10"}, timeout=10)
        t0 = time.time()
        while time.time() - t0 < 20 and snap(tid).get("job") != "RUNNING":
            time.sleep(0.25)
        print("1. 仕事が RUNNING になった。ワーカー2を起動(待機)")
        launch_worker("e9_w2", env)
        time.sleep(5)
        t_stop = time.time()
        db_stop()
        print("2. DBを止めた")
        time.sleep(3)
        ready = db_start()
        print(f"3. DBを起動({ready}秒で受付可能)")
        timeline = []
        done_at = None
        while time.time() - t_stop < TOTAL_WAIT:
            s = snap(tid)
            s["t"] = round(time.time() - t_stop, 1)
            s["run_status"] = run_status(base, tid)
            timeline.append(s)
            if s["run_status"] == "PAUSED_FOR_APPROVAL" and s.get("job") == "done":
                done_at = s["t"]
                break
            time.sleep(1)
        time.sleep(3)
        w1, w2 = starts("e9_w1"), starts("e9_w2")
        result.update({
            "worker1_starts(JobID,試行)": w1, "worker2_starts(JobID,試行)": w2,
            "finished_at_sec_after_db_stop": done_at,
            "final": timeline[-1] if timeline else None,
        })
        ids1, ids2 = {a for a, _ in w1}, {a for a, _ in w2}
        double = bool(ids1 & ids2) or len(w1) + len(w2) > 1
        result["同じ仕事の処理開始が2回以上"] = double
        result["世代が古くて引き下がった回数(w1,w2)"] = [retired("e9_w1"), retired("e9_w2")]
        result["worker1_alive"] = alive("e9_w1")
        result["worker2_alive"] = alive("e9_w2")
        ck = q("SELECT count(*) FROM checkpoints WHERE thread_id = %s", (tid,))
        result["checkpoint_rows"] = ck[0][0] if ck else None
        # 1秒ごとの記録から、状態が変わった点だけ残す
        slim, last = [], None
        for s in timeline:
            key = (s.get("job"), s.get("attempts"), s.get("advisory_locks"), s.get("run_status"))
            if key != last:
                slim.append(s)
                last = key
        result["timeline_changes"] = slim
        print("\n--- 状態が変わった点 ---")
        for s in slim:
            print(s)
        print(f"\nワーカー1の処理開始: {w1}\nワーカー2の処理開始: {w2}")
        print(f"世代が古くて引き下がった回数(w1, w2): {result['世代が古くて引き下がった回数(w1,w2)']}")
        print("結論:", "二重に処理が始まった(要対策: 世代番号など)" if double else "二重には始まらなかった")
    finally:
        kill_all()
        try:
            db_start()
        except Exception:
            pass
        save("e9_result", result)


if __name__ == "__main__":
    main()