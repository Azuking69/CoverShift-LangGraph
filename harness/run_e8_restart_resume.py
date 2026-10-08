"""E8(V6用): 承認待ちで止まった後、ワーカーを全部止めて起動し直しても、続きから再開できるか(LangGraph + PostgresSaver の確認)。
実行(LangGraphフォルダで): python -m harness.run_e8_restart_resume   (約30秒)
"""
from harness.real_common import *


def main():
    print("--- E8: 承認待ち → ワーカー全停止 → 再起動 → 承認で続きから ---")
    require_clean()
    result = {}
    stamp = int(time.time())
    sid = f"e8-{stamp}"
    tid = f"{sid}-2026-10"
    try:
        base = launch_api("e8_api", 8096)
        launch_worker("e8_w1")
        time.sleep(6)
        r = requests.post(f"{base}/api/v1/shift/start", json={"store_id": sid, "period": "2026-10"}, timeout=10)
        result["start_http"] = r.status_code
        result["paused_sec"] = wait_status(base, tid, ("PAUSED_FOR_APPROVAL",), 60)
        print(f"1. 承認待ちになった({result['paused_sec']}秒)")
        kill("e8_w1")
        time.sleep(1)
        print("2. ワーカーを止めた。1秒待って、新しいワーカーを起動")
        launch_worker("e8_w2")
        time.sleep(6)
        rs = [requests.post(f"{base}/api/v1/shift/resume", json={"thread_id": tid, "approved": True}, timeout=10).status_code for _ in range(2)]
        result["double_resume_http"] = rs
        result["completed_sec"] = wait_status(base, tid, ("COMPLETED",), 60)
        result["final_status"] = run_status(base, tid)
        rows = q("select count(*) as n from checkpoints where thread_id=%s", (tid,))
        result["checkpoints_rows"] = rows[0][0] if rows else None
        print(f"3. 承認を2回送った返事={rs} / 完了まで {result['completed_sec']} 秒 / 最終={result['final_status']} / チェックポイント行数={result['checkpoints_rows']}")
        ok = result["final_status"] == "COMPLETED" and sorted(rs) == [202, 409]
        print("[成功] 再起動をまたいで続きから動き、二重承認は止まった" if ok else "[要確認] 結果を確認してください")
    finally:
        kill_all()
        save("e8_result", result)


if __name__ == "__main__":
    main()
