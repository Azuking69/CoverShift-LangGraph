"""C案(最小版)の試験用の共通部品。V6の harness(real_common.py)と同じ作りで、起動するプロセスだけが違う:
   API / リレー / フロー処理器 / ソルバーワーカー。直接は実行しない。"""
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import requests

PKG = os.getenv("PKG", "covershift_prototype_c_queue")
HERE = Path(__file__).resolve().parent
ROOT = None
for _p in (HERE, HERE.parent, HERE.parent.parent):
    if (_p / PKG).is_dir():
        ROOT = _p
        break
if ROOT is None:
    raise SystemExit(f"[エラー] フォルダ '{PKG}' が見つかりません。harness_c を同じ階層に置いてください。 ({HERE})")

DB_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")
_u = urlparse(DB_URL)
TARGET_DB = _u.path.lstrip("/")
ADMIN_URL = urlunparse(_u._replace(path="/postgres"))
LOGDIR = HERE / "logs"
LOGDIR.mkdir(exist_ok=True)
procs = {}


def launch(name, args, extra_env=None):
    env = os.environ.copy()
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT), "DATABASE_URL": DB_URL})
    env.update({k: str(v) for k, v in (extra_env or {}).items()})
    f = open(LOGDIR / f"{name}.log", "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable] + args, cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT)
    procs[name] = p
    return p


def launch_api(name, port, extra_env=None):
    launch(name, ["-m", "uvicorn", f"{PKG}.main:app", "--port", str(port)], extra_env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            requests.get(base + "/", timeout=1)
            return base
        except Exception:
            time.sleep(0.25)
    raise SystemExit(f"[エラー] APIが起動しません。logs/{name}.log を見てください。")


def launch_relay(name, extra_env=None):
    return launch(name, ["-m", f"{PKG}.relay"], extra_env)


def launch_flow(name, extra_env=None):
    return launch(name, ["-m", f"{PKG}.flow"], extra_env)


def launch_solver(name, extra_env=None):
    return launch(name, ["-m", f"{PKG}.solver"], extra_env)


def kill(name):
    p = procs.pop(name, None)
    if p and p.poll() is None:
        p.kill()
        p.wait()


def kill_all():
    for n in list(procs):
        kill(n)


def alive(name):
    p = procs.get(name)
    return bool(p and p.poll() is None)


def open_connections():
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        r = c.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (TARGET_DB,)).fetchone()
    return int(r[0]) if r else -1


def require_clean():
    n = open_connections()
    if n != 0 and os.getenv("FORCE") != "1":
        raise SystemExit(f"[停止] 測る前に、DB '{TARGET_DB}' への接続が {n} 本あります。\n"
                         "  古いプロセスが残っているか、pgAdminなどがつないでいる可能性があります。\n"
                         "  止めてからもう一度実行してください(結果が汚れます)。")


def run_status(base, tid):
    try:
        return requests.get(f"{base}/api/v1/shift/{tid}", timeout=3).json().get("status")
    except Exception:
        return None


def wait_status(base, tid, wants, limit):
    t0 = time.time()
    while time.time() - t0 < limit:
        if run_status(base, tid) in wants:
            return round(time.time() - t0, 1)
        time.sleep(0.25)
    return None


def q(sql, args=()):
    with psycopg.connect(DB_URL, autocommit=True) as c:
        cur = c.execute(sql, args)
        return list(cur.fetchall()) if cur.description else []


def db_wait_ready(limit=90):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            with psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=2) as c:
                c.execute("SELECT 1")
            return round(time.time() - t0, 1)
        except Exception:
            time.sleep(0.5)
    return None


def clock_offset():
    xs = []
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        for _ in range(15):
            t1 = time.time()
            r = c.execute("SELECT extract(epoch FROM clock_timestamp())").fetchone()
            t2 = time.time()
            if r is not None:
                xs.append(float(r[0]) - (t1 + t2) / 2)
    return statistics.median(xs)


def stats(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return {"n": 0}
    return {"n": n, "min_ms": round(xs[0] * 1000), "median_ms": round(statistics.median(xs) * 1000),
            "p95_ms": round(xs[max(int(n * 0.95) - 1, 0)] * 1000), "max_ms": round(xs[-1] * 1000),
            "mean_ms": round(statistics.mean(xs) * 1000)}


def save(name, obj):
    (HERE / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"結果: harness_c/{name}.json")


def log_count(name, text):
    try:
        return (LOGDIR / f"{name}.log").read_text(encoding="utf-8", errors="replace").count(text)
    except FileNotFoundError:
        return 0
