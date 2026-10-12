"""E6(C案): ソルバーワーカー2台(+フロー処理器2台)で20件(各2秒)を処理 → 二重実行がないか、2台とも働くか、承認20件が通るか。
比較: V2=22.2秒 / V3(直す前)=20.8秒 / V3改(Linux)=20.8秒。(2秒×20件÷2台=約20秒が理想)
実行: python -m harness_c.run_e6_c"""
import collections

from harness_c.common_c import *


def main():
    N = 20
    print(f"--- E6(C案): ソルバーワーカー2台で{N}件(各2秒) ---  対象DB={TARGET_DB}")
    require_clean()
    result = {"system": "C-min"}
    try:
        env = {"EXP_SLEEP": 2, "MOCK_SOLVER_SLEEP": 2}
        base = launch_api("e6_api", 8095, env)
        launch_relay("e6_relay", env)
        launch_flow("e6_f1", env)
        launch_flow("e6_f2", env)
        launch_solver("e6_s1", env)
        launch_solver("e6_s2", env)
        time.sleep(4)
        stamp = int(time.time())
        t0 = time.time()
        tids = []
        for i in range(N):
            r = requests.post(f"{base}/api/v1/shift/start", json={"store_id": f"e6-{stamp}-{i}", "period": "2026-10"})
            tids.append(r.json()["thread_id"])
        like = f"e6-{stamp}-%"
        while time.time() - t0 < 150:
            n = q("SELECT count(*) FROM runs WHERE thread_id LIKE %s AND status = 'PAUSED_FOR_APPROVAL'", (like,))[0][0]
            if n >= N:
                break
            time.sleep(0.5)
        t_start = round(time.time() - t0, 1)
        paused = q("SELECT count(*) FROM runs WHERE thread_id LIKE %s AND status = 'PAUSED_FOR_APPROVAL'", (like,))[0][0]
        mx_rc = q("SELECT COALESCE(max(receive_count),0) FROM solver_log WHERE thread_id LIKE %s", (like,))[0][0]
        dup = q("SELECT count(*) FROM (SELECT thread_id, seq FROM solver_log WHERE thread_id LIKE %s GROUP BY 1,2 HAVING count(*) > 1) x", (like,))[0][0]
        per = {w: log_count(w, "ジョブ検知・処理開始") for w in ("e6_s1", "e6_s2")}
        per_flow = {w: log_count(w, "イベント処理開始") for w in ("e6_f1", "e6_f2")}
        print(f"開始ジョブ: {N}件 → {t_start}秒 / 承認待ちに到達 {paused}件 / 受信回数 最大 {mx_rc} / 同じ件の二重計算 {dup} 件")
        print(f"ソルバー別の処理数 {per} / フロー処理器別のイベント数 {per_flow}")
        codes = collections.Counter(requests.post(f"{base}/api/v1/shift/resume", json={"thread_id": t, "approved": True}).status_code for t in tids)
        t1 = time.time()
        while time.time() - t1 < 150:
            c = q("SELECT count(*) FROM runs WHERE thread_id LIKE %s AND status = 'COMPLETED'", (like,))[0][0]
            if c >= N:
                break
            time.sleep(0.5)
        completed = q("SELECT count(*) FROM runs WHERE thread_id LIKE %s AND status = 'COMPLETED'", (like,))[0][0]
        result = {"system": "C-min", "jobs": N, "seconds_for_starts": t_start, "paused": paused, "max_receive_count": mx_rc,
                  "duplicate_solves": dup, "jobs_per_solver": per, "events_per_flow": per_flow,
                  "resume_http": dict(codes), "completed_after_resume": completed}
        print(f"承認 {N}件: HTTP {dict(codes)} / COMPLETED {completed}件")
        ok = paused == N and mx_rc == 1 and dup == 0 and completed == N and min(per.values()) > 0
        print("\n[成功] 二重実行なし・2台とも稼働・承認20/20" if ok else "\n[要確認] 上の数字を見てください(受信回数>1か二重計算=二重/再実行、片方0=2台目が働いていない)")
    finally:
        kill_all()
        save("e6_c_result", result)


if __name__ == "__main__":
    main()
