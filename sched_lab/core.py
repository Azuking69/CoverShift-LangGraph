"""スケジューラー検討用の実験部品(試験専用。本番のコードには入れない)。
やること: 「時刻(due_at)になった連絡」を見つけて、送った記録(lab_notif_log)を残す。
  guard=True : UPDATE ... FOR UPDATE SKIP LOCKED で『自分が取った分だけ』送る(二重送信を防ぐ)
  guard=False: 見つけて→送って→印をつける(守りなし。2つ動くと二重に送る可能性がある)
"""
import os
import time

import psycopg

DB_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")
SEND_SEC = 0.05  # 「LINEに送る」のにかかる時間の仮の値(実測ではない)


def connect():
    return psycopg.connect(DB_URL, autocommit=True, connect_timeout=5)


def reset():
    with connect() as c:
        c.execute("DROP TABLE IF EXISTS lab_notif_log, lab_tasks")
        c.execute("CREATE TABLE lab_tasks (id SERIAL PRIMARY KEY, due_at TIMESTAMPTZ NOT NULL, notified_at TIMESTAMPTZ)")
        c.execute("CREATE TABLE lab_notif_log (id SERIAL PRIMARY KEY, task_id INT, sent_by TEXT, "
                  "lateness_ms DOUBLE PRECISION, sent_at TIMESTAMPTZ DEFAULT clock_timestamp())")


def add_tasks(offsets_sec):
    """今から offsets_sec 秒後が期限の連絡を登録する。"""
    with connect() as c:
        for o in offsets_sec:
            c.execute("INSERT INTO lab_tasks (due_at) VALUES (clock_timestamp() + make_interval(secs => %s))", (float(o),))


def tick(c, who: str, guard: bool):
    if guard:
        rows = c.execute(
            "UPDATE lab_tasks SET notified_at = clock_timestamp() WHERE id IN ("
            "  SELECT id FROM lab_tasks WHERE notified_at IS NULL AND due_at <= clock_timestamp() "
            "  ORDER BY id FOR UPDATE SKIP LOCKED) "
            "RETURNING id, extract(epoch FROM (clock_timestamp() - due_at)) * 1000").fetchall()
        for tid, late in rows:
            time.sleep(SEND_SEC)
            c.execute("INSERT INTO lab_notif_log (task_id, sent_by, lateness_ms) VALUES (%s,%s,%s)", (tid, who, late))
    else:
        rows = c.execute(
            "SELECT id, extract(epoch FROM (clock_timestamp() - due_at)) * 1000 FROM lab_tasks "
            "WHERE notified_at IS NULL AND due_at <= clock_timestamp() ORDER BY id").fetchall()
        for tid, late in rows:
            time.sleep(SEND_SEC)  # 送っている間に、別のスケジューラーも同じ連絡を見つける
            c.execute("INSERT INTO lab_notif_log (task_id, sent_by, lateness_ms) VALUES (%s,%s,%s)", (tid, who, late))
            c.execute("UPDATE lab_tasks SET notified_at = clock_timestamp() WHERE id = %s", (tid,))


def loop(who: str, guard: bool, interval: float = 0.2, stop=None):
    c = connect()
    while stop is None or not stop.is_set():
        tick(c, who, guard)
        time.sleep(interval)
