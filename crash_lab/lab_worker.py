"""
実験用ワーカーの起動役。本物の worker.py は1行も書き換えず、起動のときだけ「見張り」を付ける。
  - handle_job の前後、ソルバー、LangGraph への「再開の答え」を events.jsonl に記録する
  - CRASH_KIND (start / resume) が設定されていて、印のファイルがまだ無ければ、
    「グラフ実行の直後・runs に書く前」で、このプロセスをいきなり落とす(1回だけ)
使い方: python crash_lab\lab_worker.py <名前>     (PKG 環境変数 = 試すパッケージ名)
"""
import asyncio
import importlib
import json
import os
import sys
import time

NAME = sys.argv[1]
PKG = os.environ["PKG"]
sys.path.insert(0, os.environ.get("LAB_PKG_ROOT", os.getcwd()))
EVENTS = os.environ.get("LAB_EVENTS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.jsonl"))
CRASH_KIND = os.environ.get("CRASH_KIND", "")
CRASH_MARK = os.environ.get("CRASH_MARK", "")

W = importlib.import_module(PKG + ".worker")
MG = importlib.import_module(PKG + ".graphs.main_graph")
CUR = {"thread": None, "kind": None, "job": None, "attempt": None}


def ev(name, **kw):
    rec = {"t": time.time(), "who": NAME, "pid": os.getpid(), "ev": name, **CUR, **kw}
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ① handle_job の前後を記録
_orig_handle = W.handle_job


def handle(graph, job):
    CUR.update(thread=job["thread_id"], kind=job["kind"], job=job.get("id"), attempt=job.get("attempts"))
    ev("handle_begin")
    try:
        _orig_handle(graph, job)
        ev("handle_end")
    except BaseException as e:  # noqa: BLE001
        ev("handle_error", err=repr(e)[:200])
        raise


W.handle_job = handle

# ② ソルバー(実行された回数を数える)
for _n in ("generate_shift_schedule", "solve_shift_optimization"):
    if hasattr(MG, _n):
        def _wrap(orig):
            def f(*a, **k):
                ev("solver_begin")
                r = orig(*a, **k)
                ev("solver_end")
                return r
            return f
        setattr(MG, _n, _wrap(getattr(MG, _n)))

# ③ LangGraph に渡す「再開の答え」を記録
_RealCommand = W.Command


def cmd(**kw):
    ev("resume_answer", answer=kw.get("resume"))
    return _RealCommand(**kw)


W.Command = cmd

# ④ 「グラフ実行の直後・記録の前」で落とす
_orig_save = W._save_result


def save(graph, thread_id, config):
    if CRASH_KIND and CUR["kind"] == CRASH_KIND and CRASH_MARK and not os.path.exists(CRASH_MARK):
        open(CRASH_MARK, "w").close()
        ev("crash_before_save")
        os._exit(1)
    return _orig_save(graph, thread_id, config)


W._save_result = save

ev("worker_up")
if hasattr(W, "listen_and_work"):
    asyncio.run(W.listen_and_work())
else:
    W.main()
