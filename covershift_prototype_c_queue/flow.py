"""フロー処理器: キューからイベントを1件ずつ受け取り、案件(runs)の状態を変え、次のメッセージを送信箱に書く(同じトランザクション)。
同じイベントは events 表のイベントIDで1回に絞る。案件の行は FOR UPDATE でロックする。
起動: python -m covershift_prototype_c_queue.flow"""
import json
import time

from . import db, mq

POOL = db.Pooled()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def apply(conn, ev: dict) -> str:
    eid, kind, tid = ev["event_id"], ev["kind"], ev["thread_id"]
    r = conn.execute("INSERT INTO events (event_id, thread_id, kind) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING event_id",
                     (eid, tid, kind)).fetchone()
    if r is None:
        return "duplicate"
    run = conn.execute("SELECT status, solve_seq FROM runs WHERE thread_id = %s FOR UPDATE", (tid,)).fetchone()
    if run is None:
        outcome = "no_run"
    elif kind == "start" and run["status"] == "QUEUED":
        seq = run["solve_seq"] + 1
        conn.execute("UPDATE runs SET status = 'SOLVING', solve_seq = %s, updated_at = CURRENT_TIMESTAMP WHERE thread_id = %s", (seq, tid))
        conn.execute("INSERT INTO outbox (queue, body) VALUES ('solve', %s)",
                     (json.dumps({"kind": "solve", "thread_id": tid, "seq": seq}),))
        outcome = "applied"
    elif kind == "draft_done" and run["status"] == "SOLVING" and ev.get("seq") == run["solve_seq"]:
        res = conn.execute("SELECT draft FROM solver_results WHERE thread_id = %s AND seq = %s", (tid, ev["seq"])).fetchone()
        conn.execute(
            "UPDATE runs SET status = 'PAUSED_FOR_APPROVAL', current_status = 'S5_管理者確認待ち', draft_shift = %s, "
            "llm_explanation = %s, interrupt_info = %s, updated_at = CURRENT_TIMESTAMP WHERE thread_id = %s",
            (res["draft"] if res else None, "(ダミー説明)", json.dumps({"question": "承認しますか?"}), tid))
        outcome = "applied"
    elif kind == "resume" and run["status"] == "RESUME_QUEUED":
        if ev.get("approved"):
            conn.execute("UPDATE runs SET status = 'COMPLETED', current_status = 'S6_確定', updated_at = CURRENT_TIMESTAMP WHERE thread_id = %s", (tid,))
        else:
            seq = run["solve_seq"] + 1
            conn.execute("UPDATE runs SET status = 'SOLVING', solve_seq = %s, updated_at = CURRENT_TIMESTAMP WHERE thread_id = %s", (seq, tid))
            conn.execute("INSERT INTO outbox (queue, body) VALUES ('solve', %s)",
                         (json.dumps({"kind": "solve", "thread_id": tid, "seq": seq}),))
        outcome = "applied"
    else:
        outcome = "ignored"  # 今の状態で受けるべきイベントではない(古い・順序違い)
    conn.execute("UPDATE events SET outcome = %s WHERE event_id = %s", (outcome, eid))
    return outcome


def main():
    while True:
        try:
            db.init_schema()
            url = mq.ensure_queue("flow")
            break
        except Exception as e:
            log("[フロー] 起動待ち:", type(e).__name__)
            time.sleep(1)
    log("[フロー] 起動")
    while True:
        try:
            for m in mq.receive(url):
                ev = json.loads(m["Body"])
                log(f"イベント処理開始 {ev['kind']} {ev['thread_id']}")
                try:
                    with POOL.tx() as conn:
                        apply(conn, ev)
                except Exception:
                    mq.release(url, m)  # 失敗 → すぐ戻して、次のループで取り直す(消さない)
                    raise
                mq.delete(url, m)  # 処理(COMMIT)まで終わってから消す。途中で落ちたらキューが渡し直す
        except Exception as e:
            log("[フロー] エラー(メッセージは消さずに続けます):", type(e).__name__, str(e)[:80])
            POOL.reset()
            time.sleep(1)


if __name__ == "__main__":
    main()
