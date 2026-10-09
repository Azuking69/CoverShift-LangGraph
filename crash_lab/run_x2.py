"""
実験2: 同じ件(thread)の仕事を、2台のワーカーが同時に持つとどうなるか。
  D: 1つの仕事が長く(8秒)、期限(3秒)が切れて、2台目が「同じ仕事」を拾い直す
  E: 同じ件の「開始」を2つ、直接 jobs に入れる(2台が1つずつ取る)
  F: 承認待ちの件に、「却下」の再開を2つ、直接 jobs に入れる
見るもの: 同じ件の処理が時間的に重なったか / ソルバーが何回動いたか / 最後の状態
"""
import json
import os
import time

from psycopg.types.json import Jsonb

import lab_common as L

OUT = os.path.join(L.HERE, "crash_lab_x2_result.json")


def mk_run(label):
    thread = f"x2{label}-202610"
    if L.V6:
        thread = L.DB.create_run(f"x2{label}", "202610")  # start ジョブも1つ入る
    else:
        L.DB.create_run(thread, f"x2{label}")
    return thread


def summarize(label, thread, extra=None):
    evs = L.events()
    ivs = L.intervals(evs, thread)
    ov = L.overlaps(ivs)
    res = {
        "label": label, "thread": thread, "run_after": L.run_row(thread), "jobs_after": L.jobs(thread),
        "solver_runs": L.count(evs, "solver_begin", thread),
        "resume_answers": [e["answer"] for e in evs if e["ev"] == "resume_answer"],
        "intervals": [{"pid": i["pid"], "job": i["job"], "kind": i["kind"], "attempt": i["attempt"], "sec": round(i["end"] - i["start"], 1), "result": i["result"]} for i in ivs],
        "overlapping_pairs": len(ov),
        "graph_state": L.graph_state(thread),
    }
    if extra:
        res.update(extra)
    print("  結果:", json.dumps(res, ensure_ascii=False, default=str), flush=True)
    return res


def case_D():
    print("\n=== 実験2-D: 期限切れの拾い直しが、まだ動いている仕事と重なる ===", flush=True)
    L.reset()
    env = L.common_env(JOB_TIMEOUT_SEC=3, MOCK_SOLVER_SLEEP=8)
    L.spawn("x2D_w1", env); L.spawn("x2D_w2", env)
    time.sleep(3)
    thread = mk_run("D")
    L.wait_until(lambda: L.all_jobs_terminal(thread), 60)
    time.sleep(10)  # 2台目の処理(約8秒)が終わるまで待つ
    r = summarize("D", thread)
    L.kill_all()
    return r


def case_E():
    print("\n=== 実験2-E: 同じ件の「開始」を2つ入れる ===", flush=True)
    L.reset()
    env = L.common_env(JOB_TIMEOUT_SEC=60, MOCK_SOLVER_SLEEP=4)
    L.spawn("x2E_w1", env); L.spawn("x2E_w2", env)
    time.sleep(3)
    thread = "x2E-202610"
    with L.psycopg.connect(L.URL) as c:
        c.execute("INSERT INTO runs (thread_id, store_id, status) VALUES (%s,%s,'QUEUED')", (thread, "x2E"))
        for _ in range(2):
            c.execute("INSERT INTO jobs (thread_id, kind, payload) VALUES (%s,'start',%s)", (thread, Jsonb({"store_id": "x2E", "period": "202610"})))
    L.wait_until(lambda: L.all_jobs_terminal(thread), 60)
    time.sleep(2)
    r = summarize("E", thread)
    L.kill_all()
    return r


def case_F():
    print("\n=== 実験2-F: 承認待ちの件に「却下」の再開を2つ入れる ===", flush=True)
    L.reset()
    env = L.common_env(JOB_TIMEOUT_SEC=60, MOCK_SOLVER_SLEEP=4)
    L.spawn("x2F_w1", env); L.spawn("x2F_w2", env)
    time.sleep(3)
    thread = mk_run("F")
    if not L.wait_paused(thread, 40):
        print("  承認待ちに届かず"); L.kill_all(); return {"label": "F", "error": "no pause"}
    time.sleep(1)
    n0 = L.count(L.events(), "solver_begin", thread)
    print("  承認待ちに到達。却下の再開ジョブを2つ直接入れます", flush=True)
    with L.psycopg.connect(L.URL) as c:
        c.execute("UPDATE runs SET status='RESUME_QUEUED' WHERE thread_id=%s", (thread,))
        for _ in range(2):
            c.execute("INSERT INTO jobs (thread_id, kind, payload) VALUES (%s,'resume',%s)", (thread, Jsonb({"approved": False})))
    L.wait_until(lambda: L.all_jobs_terminal(thread), 60)
    time.sleep(2)
    r = summarize("F", thread, {"solver_runs_before_resume": n0})
    L.kill_all()
    return r


if __name__ == "__main__":
    out = [case_D(), case_E(), case_F()]
    json.dump({"pkg": L.PKG, "results": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("\n保存:", OUT)
