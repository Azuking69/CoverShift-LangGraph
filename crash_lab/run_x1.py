"""
実験1: 「グラフ実行の直後・runs に書く前」にワーカーを落とす。
  A: 開始(start)の仕事で落とす / B: 再開(承認 True)で落とす / C: 再開(却下 False)で落とす / C0: 落とさずに却下(基準)
落ちたあと、別のワーカーを起動して、期限切れの仕事を拾い直させ、結果が正しいかを見る。
正しい結果: A→承認待ち(PAUSED)、B→完了(COMPLETED)、C→「却下1回」で再計算し、承認待ち(PAUSED)に戻る(C0と同じ)
"""
import json
import os
import sys
import time

import lab_common as L

OUT = os.path.join(L.HERE, "crash_lab_x1_result.json")


def run_case(label, crash_kind, approve):
    print(f"\n=== 実験1-{label} ===", flush=True)
    L.reset()
    mark = os.path.join(L.HERE, f"crash_mark_{label}")
    if os.path.exists(mark):
        os.remove(mark)
    thread = f"x1{label}-store-202610" if not L.V6 else f"x1{label}-202610"
    env1 = L.common_env(CRASH_KIND=crash_kind, CRASH_MARK=mark)
    w1 = L.spawn(f"x1{label}_w1", env1)
    time.sleep(3)
    # 依頼を入れる(V2とV6でcreate_runの引数が違う)
    if L.V6:
        thread = L.DB.create_run(f"x1{label}", "202610")
    else:
        L.DB.create_run(thread, f"x1{label}")
    base = crash_kind == ""   # 落とさない(基準)
    if crash_kind == "start":
        w1.wait(timeout=30)
    else:
        if not L.wait_paused(thread, 30):
            print("  最初の承認待ちに届きませんでした", L.run_row(thread)); L.kill_all(); return {"label": label, "error": "no pause"}
        print("  承認待ちに到達 → 再開の依頼を入れます(答え=%s)" % approve, flush=True)
        r = L.DB.queue_resume(thread, approve)
        print("  queue_resume =", r, flush=True)
        if not base:
            w1.wait(timeout=30)
    print("  落ちた直後: run =", L.run_row(thread), " jobs =", L.jobs(thread), flush=True)
    before = L.run_row(thread)
    print("  → 別のワーカー w2 を起動し、期限切れ(%s秒)を待ちます" % L.common_env()["JOB_TIMEOUT_SEC"], flush=True)
    if not base:
        L.spawn(f"x1{label}_w2", L.common_env())
    ok = L.wait_until(lambda: L.all_jobs_terminal(thread) and (L.run_row(thread) or {}).get("status") not in ("RUNNING", "QUEUED", "RESUME_QUEUED"), 45)
    time.sleep(2)
    evs = L.events()
    res = {
        "label": label, "crash_kind": crash_kind, "approve": approve, "thread": thread,
        "run_before_w2": before, "run_after": L.run_row(thread), "jobs_after": L.jobs(thread),
        "solver_runs": L.count(evs, "solver_begin", thread),
        "resume_answers": [e["answer"] for e in evs if e["ev"] == "resume_answer"],
        "crashes": L.count(evs, "crash_before_save", thread),
        "handle_errors": L.count(evs, "handle_error", thread),
        "settled": bool(ok),
        "graph_state": L.graph_state(thread),
    }
    L.kill_all()
    print("  結果:", json.dumps(res, ensure_ascii=False, default=str), flush=True)
    return res


if __name__ == "__main__":
    results = [run_case("C0", "", False), run_case("A", "start", None), run_case("B", "resume", True), run_case("C", "resume", False)]
    json.dump({"pkg": L.PKG, "results": results}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("\n保存:", OUT)
