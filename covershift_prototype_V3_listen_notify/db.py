import os
import psycopg
from psycopg.rows import dict_row

# ユーザー名: covershift / パスワード: covershift / DB名: covershift_proto に変更
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")

def get_db_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_schema():
    """テーブルとLISTEN/NOTIFY用トリガーを作成"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    thread_id VARCHAR(255) PRIMARY KEY,
                    store_id VARCHAR(255) NOT NULL,
                    status VARCHAR(50) NOT NULL,
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

def create_run(store_id: str, period: str) -> str:
    thread_id = f"{store_id}-{period}"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT thread_id FROM runs WHERE thread_id = %s", (thread_id,))
            if cur.fetchone():
                return None

            cur.execute(
                "INSERT INTO runs (thread_id, store_id, status) VALUES (%s, %s, %s)",
                (thread_id, store_id, "QUEUED")
            )
            cur.execute(
                "INSERT INTO jobs (thread_id, kind, payload) VALUES (%s, %s, %s)",
                (thread_id, "start", f'{{"store_id": "{store_id}", "period": "{period}"}}')
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
                (thread_id, "resume", f'{{"approved": {str(approved).lower()}}}')
            )
            conn.commit()
    return True

def get_run(thread_id: str):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM runs WHERE thread_id = %s", (thread_id,))
            return cur.fetchone()