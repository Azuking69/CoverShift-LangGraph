"""
役割: LangGraph を実際に動かす「厨房(ワーカー)」。APIとは別のプロセス。
やること: 依頼箱(jobs)から「開始」「再開」を取り出し、グラフを動かして、結果を runs に書く。
         人の承認待ち(interrupt)で止まったら、状態は PostgreSQL(PostgresSaver)に残り、
         このプロセスが終了しても、再起動して「再開」の依頼が来れば続きから動く。
起動: python -m covershift_prototype.worker
"""
import time
import traceback
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from .config import DATABASE_URL, JOB_MAX_ATTEMPTS, WORKER_POLL_SEC
from .db import claim_job, finish_job, init_schema, update_run
from .graphs.main_graph import build_graph


# _has_interrupt: snapshot に interrupt があるかどうかを判定する
def _has_interrupt(snapshot) -> bool:
    return any(task.interrupts for task in snapshot.tasks)


# _save_result: グラフの状態を runs に保存する。
def _save_result(graph, thread_id: str, config: dict) -> None:
    snap = graph.get_state(config)
    values = snap.values or {}
    interrupts = [i for task in snap.tasks for i in task.interrupts]

    # interrupt があれば PAUSED_FOR_APPROVAL、next がなければ COMPLETED/REJECTED、途中で止まっていれば ERROR
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


# handle_job: 依頼(job)を処理する。job の kind に応じてグラフを動かす。
def handle_job(graph, job: dict) -> None:
    thread_id = job["thread_id"]
    config = {"configurable": {"thread_id": thread_id}}
    update_run(thread_id, status="RUNNING")
    snap = graph.get_state(config)

    if job["kind"] == "start":
        if not snap.created_at:  # まだチェックポイントがない = 初めての開始
            initial_state = {
                "store_id": job["payload"]["store_id"],
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
        # resume の場合は、承認待ち(interrupt)のときだけ受け付ける。そうでなければ無視する。
        if _has_interrupt(snap):
            graph.invoke(Command(resume=job["payload"]["approved"]), config)
        elif snap.next:
            graph.invoke(None, config)

    # _save_result: グラフの状態を runs に保存する。
    _save_result(graph, thread_id, config)


def main() -> None:
    # DB のスキーマを初期化する
    init_schema()
    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        checkpointer.setup()  # LangGraph用のテーブルを(なければ)作る
        graph = build_graph(checkpointer)
        print("[worker] 起動しました。依頼を待ちます。Ctrl+C で終了。", flush=True)

        while True:
            # claim_job: jobs から「開始」「再開」の依頼を1件取り出す。なければ None
            job = claim_job()

            # job が None の場合は、依頼がないので少し待ってからループを続ける
            if job is None:
                time.sleep(WORKER_POLL_SEC)
                continue
            print(f"[worker] job={job['id']} kind={job['kind']} thread={job['thread_id']} attempt={job['attempts']}", flush=True)
            
            # attempts が JOB_MAX_ATTEMPTS を超えていたら、ジョブを失敗として終了し、runs を ERROR にする
            if job["attempts"] > JOB_MAX_ATTEMPTS:
                finish_job(job["id"], error="試行回数の上限を超えました")
                update_run(job["thread_id"], status="ERROR", error="試行回数の上限を超えました")
                continue
            
            # handle_job: 依頼(job)を処理する。job の kind に応じてグラフを動かす。
            try:
                handle_job(graph, job)
                finish_job(job["id"])
            except Exception as exc:  # noqa: BLE001  試作なので全部拾って記録する
                traceback.print_exc()
                finish_job(job["id"], error=str(exc))
                update_run(job["thread_id"], status="ERROR", error=str(exc))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[worker] 終了しました。")
