"""
動作確認スクリプト(APIとワーカーを起動してから実行)。
    python -m covershift_prototype.check_flow
確かめること:
  [A] 開始 → ワーカーが動いて「承認待ち」で止まる
  [B] 同じ編成の二重開始は 409
  [C] 再開の合図を同時に2回送っても、片方だけ通る(202 と 409)
  [D] 承認すると COMPLETED になる
  [E] 却下を繰り返すと、上限(MAX_REJECTS)で REJECTED になる
"""
import os
import sys
import threading
import time
import httpx

# APIのベースURL
BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")


# 指定された状態になるまで待機
def wait_status(thread_id: str, targets: set, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last = None
    
    # time.time(): deadline の間、指定されたthread_idの状態をポーリングし、targetsに含まれる状態になるまで待機する
    while time.time() < deadline:
        last = httpx.get(f"{BASE}/api/v1/shift/{thread_id}").json()
        if last["status"] in targets:
            return last

        # 0.5秒待機してから再度ポーリング
        time.sleep(0.5)

    # raise AssertionError: タイムアウト
    raise AssertionError(f"タイムアウト: {thread_id} は {targets} にならなかった (最後の状態: {last and last['status']})")



# 指定された条件が満たされているかをチェック
def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  OK  " if cond else "  NG  ") + name + (f"  {detail}" if detail else ""))
    # 条件が満たされていない場合は、プログラムを終了する
    if not cond:
        sys.exit(1)


# メイン関数
def main() -> None:
    suffix = str(int(time.time()))
    store = f"store-{suffix}"

    # 1回目の開始
    print("[A] 開始 → 承認待ち")
    # r: postリクエストのレスポンス
    r = httpx.post(f"{BASE}/api/v1/shift/start", json={"store_id": store, "period": "2026-10"})
    check("startが202", r.status_code == 202, str(r.json()))
    # tid: レスポンスから取得したthread_id
    tid = r.json()["thread_id"]
    # run: wait_status関数を呼び出して、指定されたthread_idの状態が"PAUSED_FOR_APPROVAL"または"ERROR"になるまで待機する
    run = wait_status(tid, {"PAUSED_FOR_APPROVAL", "ERROR"})
    check("承認待ちで止まった", run["status"] == "PAUSED_FOR_APPROVAL", f"error={run['error']}")
    check("解説文に実名が戻っている", "山田太郎" in (run["llm_explanation"] or ""), run["llm_explanation"] or "")

    # 2回目の開始 (二重開始)
    print("[B] 二重開始")
    r = httpx.post(f"{BASE}/api/v1/shift/start", json={"store_id": store, "period": "2026-10"})
    check("2回目のstartは409", r.status_code == 409)

    print("[C] 再開の合図を同時に2回")
    codes = []

    # go関数を定義し、httpx.postで再開の合図を送信し、レスポンスのステータスコードをcodesリストに追加する
    def go():
        codes.append(httpx.post(f"{BASE}/api/v1/shift/resume", json={"thread_id": tid, "approved": True}).status_code)
    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]; [t.join() for t in threads]
    check("202が1回・409が1回", sorted(codes) == [202, 409], str(sorted(codes)))

    # 再開の合図を送信した後、wait_status関数を呼び出して、指定されたthread_idの状態が
    # "COMPLETED"、"REJECTED"、または"ERROR"になるまで待機する
    print("[D] 承認 → 完了")
    run = wait_status(tid, {"COMPLETED", "REJECTED", "ERROR"})
    check("COMPLETEDになった", run["status"] == "COMPLETED", f"status={run['status']} error={run['error']}")
    # 再開の合図を送信しても、すでに完了しているため409が返ることを確認
    r = httpx.post(f"{BASE}/api/v1/shift/resume", json={"thread_id": tid, "approved": True})
    check("完了後の再開は409", r.status_code == 409)

    # 却下を繰り返す
    print("[E] 却下を繰り返す")
    store2 = f"store-rej-{suffix}"
    r = httpx.post(f"{BASE}/api/v1/shift/start", json={"store_id": store2})
    tid2 = r.json()["thread_id"]
    wait_status(tid2, {"PAUSED_FOR_APPROVAL"})
    
    # 却下の合図を送信
    httpx.post(f"{BASE}/api/v1/shift/resume", json={"thread_id": tid2, "approved": False})
    run = wait_status(tid2, {"PAUSED_FOR_APPROVAL", "REJECTED"})
    check("1回目の却下 → もう一度承認待ち", run["status"] == "PAUSED_FOR_APPROVAL", f"status={run['status']}")

    # 2回目の却下
    httpx.post(f"{BASE}/api/v1/shift/resume", json={"thread_id": tid2, "approved": False})
    run = wait_status(tid2, {"REJECTED", "PAUSED_FOR_APPROVAL"})
    check("2回目の却下 → REJECTEDで終了", run["status"] == "REJECTED", f"status={run['status']}")

    print("\nすべて OK")


if __name__ == "__main__":
    main()
