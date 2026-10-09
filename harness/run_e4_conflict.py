"""
E4: 同時に二重送信(二重の start・二重の resume)

10組の店について、同じ依頼を「同時に2回」送り、返事(HTTPコード)の組を数える。
  理想: どれも [202, 409] (片方だけ通り、片方は「すでにある」で断られる)
  V2: start 10/10・resume 10/10 が [202,409] / V3(直す前): start は 4/10 だけ [202,409]、6/10 が [202,500]

実行(LangGraphフォルダで):  python -m harness.run_e4_real      (約1分)
"""
import collections
import threading
from concurrent.futures import ThreadPoolExecutor

from harness.real_common import *


def race(fn, n=2):
    b = threading.Barrier(n)

    def go(_):
        b.wait()
        return fn()
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(go, range(n)))


def main():
    print(f"--- E4: 同時二重送信テスト ---  対象DB={TARGET_DB}")
    require_clean()
    result = {}
    try:
        base = launch_api("e4_api", 8096)
        launch_worker("e4_worker")
        time.sleep(3)
        stamp = int(time.time())
        T = 10
        ds = collections.Counter()
        for i in range(T):
            body = {"store_id": f"e4-{stamp}-{i}", "period": "2026-10"}
            codes = sorted(r.status_code for r in race(lambda: requests.post(f"{base}/api/v1/shift/start", json=body)))
            ds[str(codes)] += 1
        print("二重 start の返事の組:", dict(ds))
        time.sleep(15)
        tids = [f"e4-{stamp}-{i}-2026-10" for i in range(T)]
        paused = sum(1 for t in tids if run_status(base, t) == "PAUSED_FOR_APPROVAL")
        dr = collections.Counter()
        for t in tids:
            body = {"thread_id": t, "approved": True}
            codes = sorted(r.status_code for r in race(lambda: requests.post(f"{base}/api/v1/shift/resume", json=body)))
            dr[str(codes)] += 1
        print("二重 resume の返事の組:", dict(dr))
        time.sleep(4)
        like = f"e4-{stamp}-%"
        runs_rows = q("SELECT count(*) FROM runs WHERE thread_id LIKE %s", (like,))[0][0]
        mx = q("SELECT COALESCE(max(c), 0) FROM (SELECT count(*) c FROM jobs WHERE kind='resume' AND thread_id LIKE %s GROUP BY thread_id) t", (like,))[0][0]
        fin = collections.Counter(r[0] for r in q("SELECT status FROM runs WHERE thread_id LIKE %s", (like,)))
        result = {"pairs": T, "double_start": dict(ds), "paused_before_resume": paused, "double_resume": dict(dr),
                  "runs_rows": runs_rows, "max_resume_jobs_per_thread": mx, "final_status": dict(fin)}
        print(f"\n[結果] runs の行数={runs_rows}(10が正常) / 1つの依頼あたりの resume ジョブ最大={mx}(1が正常) / 最終状態={dict(fin)}")
        ok = ds.get("[202, 409]") == T and dr.get("[202, 409]") == T and mx == 1 and runs_rows == T
        print("[成功] すべて [202,409]・重複なし" if ok else "[要確認] 理想と違う結果があります(上の数字を見てください)")
        print("比較: V2=start 10/10・resume 10/10 が[202,409] / V3(直す前)=start 4/10 のみ[202,409], 6/10 が[202,500] / V3改(Linux)=10/10")
    finally:
        kill_all()
        save("e4_result", result)


if __name__ == "__main__":
    main()
