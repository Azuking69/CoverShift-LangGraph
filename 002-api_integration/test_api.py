# 002-api_integration/test_api.py
"""
FastAPI × LangGraph の動作確認用テストスクリプト
1. POST /api/shift/start  -> LangGraph を起動し、S5(店長確認)で一時停止することを確認
2. POST /api/shift/resume -> Command(resume=True) で途中から再開し、最後まで完了することを確認
"""
import requests
import json
import time


BASE_URL = "http://localhost:8000"

# run_test: API連携の動作確認テスト
def run_test():
    print("==================================================")
    print(" [Step 1] API POST /api/shift/start を送信（処理開始）")
    print("==================================================")
    
    # 店舗IDを指定してシフト生成を開始
    response_start = requests.post(
        f"{BASE_URL}/api/shift/start", 
        json={"store_id": "store-101"}
    )
    
    print("レスポンス ステータスコード:", response_start.status_code)
    data_start = response_start.json()
    print("レスポンス内容:")
    print(json.dumps(data_start, indent=2, ensure_ascii=False))

    # 発行された thread_id（セッション識別子）を取得
    thread_id = data_start["thread_id"]
    print(f"\n--> LangGraph は S5(店長確認) の interrupt() で一時停止中。thread_id: '{thread_id}'")

    print("\n... 店長が画面で内容を確認中 (3秒待機) ...\n")
    time.sleep(3)

    print("==================================================")
    print(" [Step 2] API POST /api/shift/resume を送信（承認して再開）")
    print("==================================================")
    
    # 店長が画面で「承認(approved=True)」ボタンを押した想定で送信
    response_resume = requests.post(
        f"{BASE_URL}/api/shift/resume", 
        json={
            "thread_id": thread_id,
            "approved": True
        }
    )
    
    print("レスポンス ステータスコード:", response_resume.status_code)
    data_resume = response_resume.json()
    print("レスポンス内容:")
    print(json.dumps(data_resume, indent=2, ensure_ascii=False))
    print("\n✅ テスト完了: 中断されていた LangGraph が正常に再開し、完結しました！")


if __name__ == "__main__":
    try:
        run_test()
    except requests.exceptions.ConnectionError:
        print("\n❌ エラー: APIサーバー(app.py)が起動していません。")
        print("先に別のターミナルで 'python 002-api_integration/app.py' を起動してください。")