"""
V6 ワーカー = V5(通知 + 保険の確認 + 期限切れ回収 + 再接続)に、V2のLangGraph + PostgresSaver を載せたもの。

V5までは、仕事の中身が「固定の文を runs に書くだけ」だった。V6では、仕事を取ったら
  LangGraph(graphs/main_graph.py: solver → 説明 → 承認待ち(interrupt) → 確定)を動かし、
  途中状態を PostgresSaver(PostgreSQL)に保存し、結果を runs に写す。

仕事の取り方(通知・10秒ごとの保険・期限切れ回収)は V5 と同じ。
追加した所:
  - DB接続が切れたとき、グラフ用の接続も作り直す(GraphHolder)。
  - DBまわりの失敗は「失敗」にせず、RUNNINGのまま残す → 期限後に回収される。
  - 回収された仕事は、LangGraphの最後のチェックポイントから続きを動かす(handle_job)。
起動: python -m covershift_prototype_v6_langgraph.worker
"""
import asyncio
import json
import os

import asyncpg
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row

from .db import update_run
from .graphs.main_graph import build_graph

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")

JOB_TIMEOUT_SEC = float(os.getenv("JOB_TIMEOUT_SEC", "30"))
JOB_MAX_ATTEMPTS = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
FALLBACK_SEC = float(os.getenv("WORKER_FALLBACK_SEC", "10"))

DB_ERRORS = (psycopg.OperationalError, psycopg.InterfaceError)


class GraphHolder:
    """LangGraph用のDB接続(PostgresSaver)を1本持つ。切れたら捨てて、次に作り直す。"""

    def __init__(self):
        self.conn = None
        self.graph = None

    def get(self):
        if self.graph is None:
            conn = psycopg.connect(DATABASE_URL, autocommit=True, prepare_threshold=0,
                                   row_factory=dict_row, connect_timeout=5)  # type: ignore
            try:
                saver = PostgresSaver(conn)  # type: ignore
                saver.setup()  # LangGraph用のテーブルを(なければ)作る
            except Exception:
                conn.close()
                raise
            self.conn = conn
            self.graph = build_graph(saver)
        return self.graph

    def reset(self):
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass
        self.conn = None
        self.graph = None


HOLDER = GraphHolder()


def _has_interrupt(snapshot) -> bool:
    return any(task.interrupts for task in snapshot.tasks)


def _save_result(graph, thread_id: str, config: dict) -> None:
    snap = graph.get_state(config)
    values = snap.values or {}
    interrupts = [i for task in snap.tasks for i in task.interrupts]
    if interrupts:
        status, info, error = "PAUSED_FOR_APPROVAL", interrupts[0].value, None
    elif not snap.next:
        status = "COMPLETED" if values.get("manager_approved") else "REJECTED"
        info, error = None, None
    else:
        status, info, error = "ERROR", None, f"グラフが途中で止まっています: next={snap.next}"
    update_run(
        thread_id,
        status=status,
        current_status=values.get("status"),
        draft_shift=values.get("draft_shift"),
        llm_explanation=values.get("llm_explanation"),
        interrupt_info=info,
        error=error,
    )


def handle_job(graph, job: dict) -> None:
    """V2と同じ。回収された仕事(前のワーカーが途中で死んだ)も、最後のチェックポイントから続きを動かす。"""
    thread_id = job["thread_id"]
    payload = job["payload"]
    config = {"configurable": {"thread_id": thread_id}}
    update_run(thread_id, status="RUNNING")
    snap = graph.get_state(config)

    if job["kind"] == "start":
        if not snap.created_at:  # まだチェックポイントがない = 初めての開始
            initial_state = {
                "store_id": payload["store_id"],
                "status": "S0_開始",
                "draft_shift": None,
                "llm_explanation": None,
                "manager_approved": None,
                "raw_input_names": {},
                "retry_count": 0,
            }
            graph.invoke(initial_state, config)
        elif snap.next and not _has_interrupt(snap):
            graph.invoke(None, config)  # 前回の実行が途中で死んでいた → 最後のチェックポイントから続ける
    elif job["kind"] == "resume":
        if _has_interrupt(snap):
            graph.invoke(Command(resume=payload["approved"]), config)
        elif snap.next:
            graph.invoke(None, config)
    _save_result(graph, thread_id, config)


def process_job():
    """DBから未処理のジョブを1件取得して実行する"""
    with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                UPDATE jobs
                SET status = 'RUNNING', locked_at = CURRENT_TIMESTAMP, attempts = attempts + 1
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE (status = 'QUEUED'
                           OR (status = 'RUNNING' AND attempts < %s
                               AND locked_at < now() - make_interval(secs => %s)))  -- reclaim expired RUNNING jobs
                    ORDER BY id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *;
            """, (JOB_MAX_ATTEMPTS, JOB_TIMEOUT_SEC))
            job = cur.fetchone()
            if not job:
                return False

            conn.commit()

            job["payload"] = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]
            print(f"[WORKER] ジョブ検知・処理開始: Job ID={job['id']}, Kind={job['kind']}, Thread={job['thread_id']}, 試行={job['attempts']}")

            try:
                try:
                    handle_job(HOLDER.get(), job)
                except DB_ERRORS:
                    # グラフ用の接続が古い(DB再起動で切れた)可能性。接続を作り直して、すぐ1回だけやり直す。
                    # handle_job はチェックポイントから続きを動かす作りなので、やり直しても二重にならない
                    HOLDER.reset()
                    print("[WORKER] グラフ用のDB接続を作り直して、もう1回やります")
                    handle_job(HOLDER.get(), job)
            except DB_ERRORS:
                # まだDBが使えない。「失敗」にはせずRUNNINGのまま残す(期限後に回収される)
                HOLDER.reset()
                raise
            except Exception as e:
                conn.rollback()
                cur.execute("UPDATE jobs SET status = 'failed', error = %s WHERE id = %s;", (str(e), job["id"]))
                cur.execute("UPDATE runs SET status = 'ERROR', error = %s WHERE thread_id = %s;", (str(e), job["thread_id"]))
                conn.commit()
                print(f"[WORKER] ジョブエラー: Job ID={job['id']}, Error={e}")
                return True

            cur.execute("UPDATE jobs SET status = 'done' WHERE id = %s;", (job["id"],))
            conn.commit()
            print(f"[WORKER] ジョブ完了: Job ID={job['id']}")
            return True


def drain():
    """DBが落ちていても例外でワーカーを止めない"""
    try:
        while process_job():
            pass
        return True
    except Exception as e:
        print(f"[WORKER] DBエラー(次の周期に再試行): {type(e).__name__}")
        return False


async def connect_listener():
    conn = await asyncpg.connect(DATABASE_URL, timeout=5)

    def on_notification(connection, pid, channel, payload):
        print(f"\n⚡ [NOTIFY受信] チャンネル: {channel}, Job ID: {payload}")
        drain()

    await conn.add_listener("job_created", on_notification)
    return conn


async def listen_and_work():
    """LISTEN通知を待ち、通知が切れたら張り直す。FALLBACK_SEC ごとに保険の確認と期限切れジョブの回収"""
    print("[WORKER] ワーカー起動(V6: LangGraph + PostgresSaver)。未処理ジョブのチェック中...")
    conn = None
    while True:
        try:
            if conn is None or conn.is_closed():
                conn = await connect_listener()
                print("📡 [LISTEN開始/再接続]")
        except Exception as e:
            conn = None
            print(f"[WORKER] LISTEN接続失敗(再試行): {type(e).__name__}")
        drain()
        await asyncio.sleep(FALLBACK_SEC)


if __name__ == "__main__":
    asyncio.run(listen_and_work())
