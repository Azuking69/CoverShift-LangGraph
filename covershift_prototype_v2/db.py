"""
DB(PostgreSQL)とのやりとり。APIもワーカーも、ここを通して「依頼箱(jobs)」と「実行状況(runs)」を使う。

  runs : 編成1件ごとの状況。画面はこれを読む(APIはグラフを動かさない)。
  jobs : 「開始して」「再開して」という依頼箱。APIが書き、ワーカーが取り出す。
  (LangGraphの途中状態は、PostgresSaver が別のテーブルに自動で保存する)
"""
from contextlib import contextmanager
from typing import Any, Optional
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .config import DATABASE_URL, JOB_TIMEOUT_SEC

# DBのスキーマを作るSQL。テーブルがなければ作る。すでにあれば何もしない。
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    thread_id       TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    status          TEXT NOT NULL,
    current_status  TEXT,
    draft_shift     JSONB,
    llm_explanation TEXT,
    interrupt_info  JSONB,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('start', 'resume')),
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'done', 'failed')),
    attempts    INT NOT NULL DEFAULT 0,
    locked_at   TIMESTAMPTZ,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs (status, id);
"""


# @contextmanager: with で囲むと、抜けたときに自動で commit/rollback してくれる
@contextmanager
def connect():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


# 初期化
def init_schema() -> None:
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(727001)")  # APIとワーカーが同時に作っても衝突しないように
        conn.execute(SCHEMA_SQL)


# 編成を新しく作って「開始」の依頼を出す。同じthread_idが既にあれば False
def create_run(thread_id: str, store_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO runs (thread_id, store_id, status) " \
            "VALUES (%s, %s, 'QUEUED') "
            "ON CONFLICT (thread_id) " \
            "DO NOTHING RETURNING thread_id",
            (thread_id, store_id),
        ).fetchone()

        # thread_id が既に存在していた場合は row が None になるので、False を返す
        if row is None:
            return False
        conn.execute(
            "INSERT INTO jobs (thread_id, kind, payload) " \
            "VALUES (%s, 'start', %s)",
            (thread_id, Jsonb({"store_id": store_id})),
        )

        return True


# 「再開」の依頼を出す。返り値: 'queued' | 'not_found' | 'conflict'
def queue_resume(thread_id: str, approved: bool) -> str:
    """
    承認待ち(PAUSED_FOR_APPROVAL)のときだけ受け付ける。
    同じ合図が2回来ても、1回目が状態を RESUME_QUEUED に変えるので、2回目は 'conflict' になる。
    (UPDATE が行をロックするので、同時に来ても片方しか通らない)
    """
    with connect() as conn:
        row = conn.execute(
            "UPDATE runs SET status = 'RESUME_QUEUED', updated_at = now() "
            "WHERE thread_id = %s AND status = 'PAUSED_FOR_APPROVAL' RETURNING thread_id",
            (thread_id,),
        ).fetchone()

        # thread_id が存在しないか、承認待ちでない場合は row が None になるので、'not_found' を返す
        if row:
            conn.execute(
                "INSERT INTO jobs (thread_id, kind, payload) VALUES (%s, 'resume', %s)",
                (thread_id, Jsonb({"approved": approved})),
            )
            return "queued"

        # fetchone() で None が返る場合は、thread_id が存在しないか、承認待ちでない場合なので、'not_found' を返す
        exists = conn.execute("SELECT 1 FROM runs WHERE thread_id = %s", (thread_id,)).fetchone()
        return "conflict" if exists else "not_found"


# thread_id で runs を1件取得する。なければ None
# optional[dict] で返すので、呼び出し側は「if run is None:」で存在チェックできる
def get_run(thread_id: str) -> Optional[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM runs WHERE thread_id = %s", (thread_id,)).fetchone()


# 依頼を1件取り出す
def claim_job() -> Optional[dict]:
    """
    依頼を1件取り出す。FOR UPDATE SKIP LOCKED で、他のワーカーが取った依頼は飛ばす。
    処理中のまま JOB_TIMEOUT_SEC 以上たった依頼は、ワーカーが死んだとみなして取り直す。
    """
    with connect() as conn:
        return conn.execute(
            """
            UPDATE jobs SET status = 'processing', locked_at = now(), attempts = attempts + 1
            WHERE id = (
                SELECT id FROM jobs
                WHERE status = 'queued'
                   OR (status = 'processing' AND locked_at < now() - make_interval(secs => %s))
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, thread_id, kind, payload, attempts
            """,
            (float(JOB_TIMEOUT_SEC),),
        ).fetchone()


# 依頼が終わったら、jobs の status を done/failed にする
def finish_job(job_id: int, error: Optional[str] = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = %s, error = %s, finished_at = now() WHERE id = %s",
            ("failed" if error else "done", error, job_id),
        )

# _: この範囲内でのみ更新可能なカラムを定義
_RUN_COLUMNS = {
    "status", "current_status", "draft_shift", "llm_explanation", "interrupt_info", "error",
}
_JSON_COLUMNS = {"draft_shift", "interrupt_info"}


# thread_id で runs を更新する。存在しなければ例外
def update_run(thread_id: str, **fields: Any) -> None:
    sets, values = [], []

    # fields のキーが _RUN_COLUMNS に含まれていない場合は例外を投げる
    for key, value in fields.items():
        if key not in _RUN_COLUMNS:
            raise ValueError(f"unknown column: {key}")
        sets.append(f"{key} = %s")
        values.append(Jsonb(value) if key in _JSON_COLUMNS and value is not None else value)
    # updated_at を自動で更新する
    sets.append("updated_at = now()")
    with connect() as conn:
        conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE thread_id = %s", (*values, thread_id))
