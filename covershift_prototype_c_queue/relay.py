"""リレー(伝達役): 送信箱(outbox)の未送信メッセージを、キューへ移す。
合図(LISTEN/NOTIFY)が来たらすぐ、来なくても RELAY_POLL_SEC ごとに確認する(保険)。
送ったあと、記録(sent_at)の前に落ちると、同じメッセージが2回出る(最低1回)。受ける側がイベントIDで1回に絞る。
起動: python -m covershift_prototype_c_queue.relay"""
import json
import time

import psycopg

from . import config, db, mq


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def drain(conn, urls) -> int:
    total = 0
    while True:
        with conn.transaction():
            rows = conn.execute(
                "SELECT id, queue, body FROM outbox WHERE sent_at IS NULL ORDER BY id LIMIT 50 FOR UPDATE SKIP LOCKED"
            ).fetchall()
            for row in rows:
                oid, queue, body = row
                body = dict(body)
                body["event_id"] = f"ob-{oid}"
                mq.send(urls[queue], body)
                conn.execute("UPDATE outbox SET sent_at = clock_timestamp() WHERE id = %s", (oid,))
        total += len(rows)
        if len(rows) < 50:
            return total


def main():
    while True:
        try:
            db.init_schema()
            urls = {"flow": mq.ensure_queue("flow"), "solve": mq.ensure_queue("solve")}
            break
        except Exception as e:
            log("[リレー] 起動待ち:", type(e).__name__)
            time.sleep(1)
    log("[リレー] 起動")
    conn = None
    while True:
        try:
            if conn is None or conn.closed:
                conn = psycopg.connect(db.DATABASE_URL, autocommit=True, connect_timeout=5)
                conn.execute("LISTEN outbox_new")
                log("[リレー] DBにつなぎました(合図待ち)")
            n = drain(conn, urls)
            if n:
                log(f"[リレー] {n}件をキューへ移しました")
            for _ in conn.notifies(timeout=config.RELAY_POLL_SEC, stop_after=1):
                pass
        except Exception as e:
            log("[リレー] エラー(つなぎ直します):", type(e).__name__, str(e)[:80])
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None
            time.sleep(1)


if __name__ == "__main__":
    main()
