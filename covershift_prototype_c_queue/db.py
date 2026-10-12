"""C案(最小版)のDB。 runs(案件の状態) / outbox(送信箱) / events(処理済みイベント) / solver_log / solver_results。
V6の jobs 表(DBの作業の列)はない。仕事はキューで届く。"""
import json
import os
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import config

DATABASE_URL = config.DATABASE_URL


def get_db_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)  # type: ignore


class Pooled:
    """常駐プロセス用: 接続を1本持ち回し、切れたら捨てて次に作り直す。"""

    def __init__(self):
        self.conn = None

    def get(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)  # type: ignore
        return self.conn

    def reset(self):
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass
        self.conn = None

    @contextmanager
    def tx(self):
        c = self.get()
        try:
            with c.transaction():
                yield c
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self.reset()
            raise


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    thread_id VARCHAR(255) PRIMARY KEY,
    store_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    current_status TEXT,
    draft_shift TEXT,
    llm_explanation TEXT,
    interrupt_info JSONB,
    error TEXT,
    solve_seq INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS solve_seq INT NOT NULL DEFAULT 0;  -- V6の試験で作られた runs 表が残っていても動くように
CREATE TABLE IF NOT EXISTS outbox (
    id BIGSERIAL PRIMARY KEY,
    queue VARCHAR(50) NOT NULL,
    body JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS outbox_unsent ON outbox (id) WHERE sent_at IS NULL;
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    thread_id VARCHAR(255),
    kind VARCHAR(50),
    outcome VARCHAR(50),
    started_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS solver_log (
    id SERIAL PRIMARY KEY,
    thread_id VARCHAR(255),
    seq INT,
    receive_count INT,
    worker TEXT,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS solver_results (
    thread_id VARCHAR(255),
    seq INT,
    draft TEXT,
    PRIMARY KEY (thread_id, seq)
);
CREATE OR REPLACE FUNCTION notify_outbox_new() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('outbox_new', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS outbox_insert_trigger ON outbox;
CREATE TRIGGER outbox_insert_trigger AFTER INSERT ON outbox
FOR EACH ROW EXECUTE FUNCTION notify_outbox_new();
"""


def init_schema():
    """表を(なければ)作る。複数のプロセスが同時に呼んでも壊れないよう、助言ロックで1つずつにする。"""
    with get_db_connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(60601)")
        conn.execute(SCHEMA)  # type: ignore
        conn.commit()


def create_run(store_id: str, period: str) -> str | None:
    """案件を登録し、同じ1回のトランザクションで、送信箱に「start」イベントを書く(状態変更とメッセージが一緒)。"""
    thread_id = f"{store_id}-{period}"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (thread_id, store_id, status) VALUES (%s, %s, 'QUEUED') "
                "ON CONFLICT (thread_id) DO NOTHING RETURNING thread_id", (thread_id, store_id))
            if cur.fetchone() is None:
                return None
            cur.execute("INSERT INTO outbox (queue, body) VALUES ('flow', %s)",
                        (json.dumps({"kind": "start", "thread_id": thread_id, "store_id": store_id, "period": period}),))
        conn.commit()
    return thread_id


def queue_resume(thread_id: str, approved: bool) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE runs SET status = 'RESUME_QUEUED', updated_at = CURRENT_TIMESTAMP "
                        "WHERE thread_id = %s AND status = 'PAUSED_FOR_APPROVAL'", (thread_id,))
            if cur.rowcount == 0:
                return False
            cur.execute("INSERT INTO outbox (queue, body) VALUES ('flow', %s)",
                        (json.dumps({"kind": "resume", "thread_id": thread_id, "approved": approved}),))
        conn.commit()
    return True


def get_run(thread_id: str):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM runs WHERE thread_id = %s", (thread_id,))
            return cur.fetchone()
