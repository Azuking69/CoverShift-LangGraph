# 動作確認用クライアントスクリプト
import time
import requests

BASE_URL = "http://127.0.0.1:8001"
THREAD_ID = "store001-2026-10"

def run_test():
    print("=== V4 (Celery + Redis) 動作検証開始 ===")
    
    # 1. シフト作成リクエスト（即時202）
    print("\n1. シフト作成リクエストを送信中...")
    res = requests.post(f"{BASE_URL}/api/v1/shift", json={
        "thread_id": THREAD_ID,
        "store_id": "store001",
        "target_month": "2026-10"
    })
    print("応答:", res.status_code, res.json())
    
    # ワーカー処理待ち
    time.sleep(2)
    
    # 2. 承認リクエスト (HITL 再開)
    print("\n2. 店長承認 (resume) リクエストを送信中...")
    res_resume = requests.post(f"{BASE_URL}/api/v1/shift/{THREAD_ID}/resume", json={
        "approved": True,
        "comments": "問題なし。このシフト案で確定します。"
    })
    print("応答:", res_resume.status_code, res_resume.json())
    
    time.sleep(2)
    print("\n=== 検証完了 ===")

if __name__ == "__main__":
    run_test()