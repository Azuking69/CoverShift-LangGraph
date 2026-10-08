"""
E6: ワーカー2台で20件(各2秒)を処理 → 二重実行がないか、2台とも働くか、承認20件が通るか

実行(LangGraphフォルダで):  python -m harness.run_e6_real      (約1分)
比較: V2=22.2秒 / V3(直す前)=20.8秒 / V3改(Linux)=20.8秒。(2秒×20件÷2台=約20秒が理想)
"""
import collections

from harness.real_common import *


def main():
    N = 20
    print(f"--- E6: ワーカー2台で{N}件(各2秒) ---  対象DB={TARGET_DB}")
    require_clean()
    result = {}
    try:
        base = launch_api("e6_api", 8095, {"EXP_SLEEP": 2})
        launch_worker("e6_w1", {"EXP_SLEEP": 2})
        launch_worker("e6_w2", {"EXP_SLEEP": 2})
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
        mx_att = q("SELECT COALESCE(max(attempts),0) FROM jobs WHERE thread_id LIKE %s", (like,))[0][0]
        per = {}
        for w in ("e6_w1", "e6_w2"):
            try:
                txt = (LOGDIR / f"{w}.log").read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                txt = ""
            per[w] = txt.count("ジョブ検知・処理開始")
        print(f"開始ジョブ: {N}件 → {t_start}秒 / 承認待ちに到達 {paused}件 / attempts 最大 {mx_att} / ワーカー別の処理数 {per}")
        codes = collections.Counter(requests.post(f"{base}/api/v1/shift/resume", json={"thread_id": t, "approved": True}).status_code for t in tids)
        t1 = time.time()
        while time.time() - t1 < 150:
            c = q("SELECT count(*) FROM runs WHERE thread_id LIKE %s AND status = 'COMPLETED'", (like,))[0][0]
            if c >= N:
                break
            time.sleep(0.5)
        completed = q("SELECT count(*) FROM runs WHERE thread_id LIKE %s AND status = 'COMPLETED'", (like,))[0][0]
        result = {"jobs": N, "seconds_for_starts": t_start, "paused": paused, "max_attempts": mx_att,
                  "jobs_per_worker": per, "resume_http": dict(codes), "completed_after_resume": completed}
        print(f"承認 {N}件: HTTP {dict(codes)} / COMPLETED {completed}件")
        ok = paused == N and mx_att == 1 and completed == N and min(per.values()) > 0
        print("\n[成功] 二重実行なし・2台とも稼働・承認20/20" if ok else "\n[要確認] 上の数字を見てください(attempts>1=二重/再実行、片方0=2台目が働いていない)")
    finally:
        kill_all()
        save("e6_result", result)


if __name__ == "__main__":
    main()
