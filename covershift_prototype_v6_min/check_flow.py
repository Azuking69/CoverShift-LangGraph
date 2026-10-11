import os
import time
import requests

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8001")

def run_test():
    store_id = "store001"
    period = "2026-10"
    thread_id = f"{store_id}-{period}"

    print("=== 1. シフト作成リクエスト (POST /api/v1/shift/start) ===")
    res = requests.post(f"{API_BASE}/api/v1/shift/start", json={"store_id": store_id, "period": period})
    print(f"ステータスコード: {res.status_code}")
    print(f"レスポンス: {res.json()}\n")

    print("=== 2. ワーカー処理待ち (ステータス監視) ===")
    for _ in range(10):
        res = requests.get(f"{API_BASE}/api/v1/shift/{thread_id}")
        run = res.json()
        status = run.get("status")
        print(f"[STATUS] 現在のステータス: {status}")
        if status == "PAUSED_FOR_APPROVAL":
            print(f"-> 店長確認待ちになりました！ Draft: {run.get('draft_shift')}\n")
            break
        time.sleep(1)

    print("=== 3. 承認リクエスト (POST /api/v1/shift/resume) ===")
    res = requests.post(f"{API_BASE}/api/v1/shift/resume", json={"thread_id": thread_id, "approved": True})
    print(f"ステータスコード: {res.status_code}")
    print(f"レスポンス: {res.json()}\n")

    print("=== 4. 最終完了監視 ===")
    for _ in range(10):
        res = requests.get(f"{API_BASE}/api/v1/shift/{thread_id}")
        run = res.json()
        status = run.get("status")
        print(f"[STATUS] 現在のステータス: {status}")
        if status in ["COMPLETED", "REJECTED"]:
            print(f"-> 処理完了！ 最終ステータス: {status}\n")
            break
        time.sleep(1)

if __name__ == "__main__":
    run_test()