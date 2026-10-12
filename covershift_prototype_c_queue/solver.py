"""ソルバーワーカー: 編成要求を1件受け取り、(ダミーの)計算をして、結果をDBに保存し、「草案完成」イベントを送信箱に書く。
計算の待ち時間は MOCK_SOLVER_SLEEP(V6と同じ。重い計算の代わり)。本物のCP-SATは使っていない(V6の試験もダミー)。
起動: python -m covershift_prototype_c_queue.solver"""
import json
import os
import time

from . import config, db, mq

POOL = db.Pooled()
WORKER = f"pid{os.getpid()}"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    while True:
        try:
            db.init_schema()
            url = mq.ensure_queue("solve")
            break
        except Exception as e:
            log("[ソルバー] 起動待ち:", type(e).__name__)
            time.sleep(1)
    log("[ソルバー] 起動", WORKER)
    while True:
        try:
            for m in mq.receive(url):
                req = json.loads(m["Body"])
                rc = int(m.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
                tid, seq = req["thread_id"], req["seq"]
                log(f"ジョブ検知・処理開始 {tid} seq={seq} 受信回数={rc}")
                try:
                    with POOL.tx() as conn:
                        conn.execute("INSERT INTO solver_log (thread_id, seq, receive_count, worker) VALUES (%s, %s, %s, %s)",
                                     (tid, seq, rc, WORKER))
                    if config.MOCK_SOLVER_SLEEP:
                        time.sleep(config.MOCK_SOLVER_SLEEP)
                    draft = json.dumps({"assignments": [{"day": 1, "staff": "A", "task": "レジ"}]}, ensure_ascii=False)
                    with POOL.tx() as conn:
                        conn.execute("INSERT INTO solver_results (thread_id, seq, draft) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                                     (tid, seq, draft))
                        conn.execute("INSERT INTO outbox (queue, body) VALUES ('flow', %s)",
                                     (json.dumps({"kind": "draft_done", "thread_id": tid, "seq": seq}),))
                except Exception:
                    mq.release(url, m)  # 失敗 → すぐ戻して取り直す
                    raise
                mq.delete(url, m)
        except Exception as e:
            log("[ソルバー] エラー(メッセージは消さずに続けます):", type(e).__name__, str(e)[:80])
            POOL.reset()
            time.sleep(1)


if __name__ == "__main__":
    main()
