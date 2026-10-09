import importlib
import json
import os
import subprocess
import sys
import time

import psycopg

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
EVENTS = os.path.join(HERE, "events.jsonl")
PKG = os.environ.get("PKG")
if not PKG:
    sys.exit("PKG 環境変数がありません。例: $env:PKG='covershift_prototype_v6_langgraph'")

def _find_pkg_root(pkg, start):
    """pkg の db.py があるフォルダを、start から深さ3まで探し、その親フォルダを返す"""
    import os
    for root, dirs, files in os.walk(start):
        if root[len(start):].count(os.sep) > 3:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in ("venv", ".venv", "node_modules", "__pycache__", ".git")]
        if os.path.basename(root) == pkg and "db.py" in files:
            return os.path.dirname(root)
    return start

sys.path.insert(0, _find_pkg_root(PKG, os.getcwd()))
print("パッケージの場所:", sys.path[0])
DB = importlib.import_module(PKG + ".db")
URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")
V6 = hasattr(importlib.import_module(PKG + ".worker"), "listen_and_work")
TERMINAL_JOB = ("done", "failed")
PROCS = []


def sql(q, args=(), fetch=True):
    with psycopg.connect(URL, autocommit=True) as c:
        cur = c.execute(q, args)
        if fetch and cur.description:
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def reset():
    DB.init_schema()
    have = {r["tablename"] for r in sql("select tablename from pg_tables where schemaname='public'")}
    for t in ("jobs", "runs", "checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        if t in have:
            sql(f"TRUNCATE {t} RESTART IDENTITY", fetch=False)
    open(EVENTS, "w").close()
    os.makedirs(LOGS, exist_ok=True)


def spawn(name, env=None):
    e = os.environ.copy()
    e.update({k: str(v) for k, v in (env or {}).items()})
    e["PYTHONUNBUFFERED"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"
    e["LAB_EVENTS"] = EVENTS
    e["LAB_PKG_ROOT"] = sys.path[0]
    f = open(os.path.join(LOGS, name + ".log"), "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "lab_worker.py"), name],
                         cwd=os.getcwd(), env=e, stdout=f, stderr=subprocess.STDOUT)
    PROCS.append(p)
    return p


def kill_all():
    for p in PROCS:
        if p.poll() is None:
            p.kill()
    PROCS.clear()


def events():
    out = []
    with open(EVENTS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def run_row(thread):
    r = sql("select status, current_status, error from runs where thread_id=%s", (thread,))
    return r[0] if r else None


def jobs(thread):
    return sql("select id, kind, status, attempts from jobs where thread_id=%s order by id", (thread,))


def wait_until(fn, timeout, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def all_jobs_terminal(thread):
    js = jobs(thread)
    return bool(js) and all(j["status"] in TERMINAL_JOB for j in js)


def wait_paused(thread, timeout=30):
    return wait_until(lambda: (run_row(thread) or {}).get("status") == "PAUSED_FOR_APPROVAL", timeout)


def count(evs, name, thread=None):
    return sum(1 for e in evs if e["ev"] == name and (thread is None or e["thread"] == thread))


def intervals(evs, thread):
    """handle_begin〜handle_end(or error/crash) の区間を、仕事ごとに作る"""
    res, open_ = [], {}
    for e in evs:
        if e["thread"] != thread:
            continue
        key = (e["pid"], e["job"])
        if e["ev"] == "handle_begin":
            open_[key] = e
        elif e["ev"] in ("handle_end", "handle_error", "crash_before_save") and key in open_:
            b = open_.pop(key)
            res.append({"pid": e["pid"], "job": e["job"], "kind": b["kind"], "attempt": b["attempt"],
                        "start": b["t"], "end": e["t"], "result": e["ev"]})
    return res


def overlaps(ivs):
    pairs = []
    for i in range(len(ivs)):
        for j in range(i + 1, len(ivs)):
            a, b = ivs[i], ivs[j]
            if a["pid"] != b["pid"] and a["start"] < b["end"] and b["start"] < a["end"]:
                pairs.append((a, b))
    return pairs


def common_env(**kw):
    e = {"JOB_TIMEOUT_SEC": "4", "WORKER_FALLBACK_SEC": "2", "WORKER_POLL_SEC": "0.5",
         "MOCK_SOLVER_SLEEP": "1", "EXP_SLEEP": "0", "JOB_MAX_ATTEMPTS": "5"}
    e.update({k: str(v) for k, v in kw.items()})
    return e


def graph_state(thread):
    """LangGraph(PostgresSaver)に残っている、その件の状態を直接読む"""
    from langgraph.checkpoint.postgres import PostgresSaver
    gb = importlib.import_module(PKG + ".graphs.main_graph").build_graph
    with PostgresSaver.from_conn_string(URL) as cp:
        g = gb(cp)
        s = g.get_state({"configurable": {"thread_id": thread}})
        v = s.values or {}
        return {"retry_count": v.get("retry_count"), "manager_approved": v.get("manager_approved"),
                "status": v.get("status"), "next": list(s.next or [])}
