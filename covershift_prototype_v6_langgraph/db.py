import json
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# ユーザー名: covershift / パスワード: covershift / DB名: covershift_proto に変更
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")

def get_db_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)  # type: ignore  # 【改善】DBが止まっても5秒で諦める

def init_schema():
    """テーブルとLISTEN/NOTIFY用トリガーを作成"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    thread_id VARCHAR(255) PRIMARY KEY,
                    store_id VARCHAR(255) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    current_status TEXT,
                    draft_shift TEXT,
                    llm_explanation TEXT,
                    interrupt_info JSONB,
                    error TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    thread_id VARCHAR(255) NOT NULL,
                    kind VARCHAR(50) NOT NULL,
                    payload JSONB,
                    status VARCHAR(50) DEFAULT 'QUEUED',
                    attempts INT DEFAULT 0,
                    locked_at TIMESTAMP WITH TIME ZONE,
                    error TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );

                -- V6: add current_status to runs tables created by V5
                ALTER TABLE runs ADD COLUMN IF NOT EXISTS current_status TEXT;
            """)

            cur.execute("""
                CREATE OR REPLACE FUNCTION notify_job_created()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_notify('job_created', NEW.id::text);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS jobs_insert_trigger ON jobs;
                CREATE TRIGGER jobs_insert_trigger
                AFTER INSERT ON jobs
                FOR EACH ROW EXECUTE FUNCTION notify_job_created();
            """)
            conn.commit()

def create_run(store_id: str, period: str) -> str | None:  # ◄ -> str から -> str | None に修正
    thread_id = f"{store_id}-{period}"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (thread_id, store_id, status) VALUES (%s, %s, %s) "
                "ON CONFLICT (thread_id) DO NOTHING RETURNING thread_id",
                (thread_id, store_id, "QUEUED")
            )
            if cur.fetchone() is None:
                return None  # ◄ ここで None を返しても型エラーにならなくなります
            
            cur.execute(
                "INSERT INTO jobs (thread_id, kind, payload) VALUES (%s, %s, %s)",
                (thread_id, "start", json.dumps({"store_id": store_id, "period": period}))
            )
            conn.commit()
    return thread_id

def queue_resume(thread_id: str, approved: bool) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'RESUME_QUEUED', updated_at = CURRENT_TIMESTAMP WHERE thread_id = %s AND status = 'PAUSED_FOR_APPROVAL'",
                (thread_id,)
            )
            if cur.rowcount == 0:
                return False

            cur.execute(
                "INSERT INTO jobs (thread_id, kind, payload) VALUES (%s, %s, %s)",
                (thread_id, "resume", json.dumps({"approved": approved}))
            )
            conn.commit()
    return True

def get_run(thread_id: str):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM runs WHERE thread_id = %s", (thread_id,))
            return cur.fetchone()


_RUN_COLUMNS = {"status", "current_status", "draft_shift", "llm_explanation", "interrupt_info", "error"}


def update_run(thread_id: str, **fields: Any) -> None:
    """【V6】ワーカーが runs を更新する(許可した列だけ)。LangGraphの結果を画面用の表に写す。"""
    sets, values = [], []
    for key, value in fields.items():
        if key not in _RUN_COLUMNS:
            raise ValueError(f"unknown column: {key}")
        if key == "interrupt_info" and value is not None:
            value = Jsonb(value)
        elif key == "draft_shift" and value is not None and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        sets.append(f"{key} = %s")
        values.append(value)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE runs SET {', '.join(sets)} WHERE thread_id = %s", (*values, thread_id))
        conn.commit()
