"""
E2: 仕事を出してから、ワーカーが取りかかるまでの遅れ(50回)

測り方(V2・V3・V4の比較資料と同じ):
  ・APIに「シフト作成」を50回送る(間隔は0.2〜1.3秒のランダム。乱数の種=7で毎回同じ並び)
  ・遅れ = ワーカーが仕事を取った時刻(jobs.locked_at) − 送信した時刻
  ・中央値・95%・最大 を出す

Docker Desktop(Windows)では、DBコンテナの時計がパソコンの時計と少しずれることがあるため、
  最初に「DBの時計 − パソコンの時計」のずれを測って、補正してから引き算する。
  念のため、時計に左右されない値(jobs.created_at → locked_at、DBの時計だけで計算)も出す。

やること(自動):
  0. 余分なワーカーが残っていないか確認(DBへの接続が0でなければ止まる)
  1. API(ポート8097)とワーカーを1台起動 → 8秒待つ
  2. 50回送信 → 3秒待つ → 集計 → harness/e2_result.json に保存

実行(LangGraphフォルダで):
    python -m harness.run_e2_real
"""
import json
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import requests

PKG = os.getenv("PKG", "covershift_prototype_v5_notify")
HERE = Path(__file__).resolve()
ROOT = None
for p in (HERE.parent, HERE.parent.parent, HERE.parent.parent.parent):
    if (p / PKG).is_dir():
        ROOT = p
        break
if ROOT is None:
    raise SystemExit(f"[エラー] フォルダ '{PKG}' が見つかりません。harness を同じ階層に置いてください。 ({HERE})")

DB_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")
u = urlparse(DB_URL)
TARGET_DB = u.path.lstrip("/")
ADMIN_URL = urlunparse(u._replace(path="/postgres"))
PORT = int(os.getenv("E2_PORT", "8097"))
BASE = f"http://127.0.0.1:{PORT}"
N = int(os.getenv("E2_N", "50"))
LOGDIR = HERE.parent / "logs"
LOGDIR.mkdir(exist_ok=True)
env = os.environ.copy()
env.update({"PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT), "DATABASE_URL": DB_URL})
procs = []


def launch(name, args):
    f = open(LOGDIR / f"e2_{name}.log", "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable] + args, cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT)
    procs.append(p)
    return p


def open_connections():
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        r = c.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (TARGET_DB,)).fetchone()
    return int(r[0]) if r else -1


def clock_offset():
    """DBの時計 − パソコンの時計(秒)。往復の時間の真ん中で補正し、中央値を採る。"""
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
    return {"n": n, "min_ms": round(xs[0] * 1000), "median_ms": round(statistics.median(xs) * 1000),
            "p95_ms": round(xs[max(int(n * 0.95) - 1, 0)] * 1000), "max_ms": round(xs[-1] * 1000),
            "mean_ms": round(statistics.mean(xs) * 1000)}


def main():
    print(f"--- E2: 仕事を出してから始まるまでの遅れ({N}回) ---  対象DB={TARGET_DB}")
    n0 = open_connections()
    if n0 != 0 and os.getenv("E2_FORCE") != "1":
        raise SystemExit(f"[停止] 測る前に、DB '{TARGET_DB}' への接続が {n0} 本あります。\n"
                         "  古いワーカー/APIが残っているか、pgAdminなどがつないでいる可能性があります。\n"
                         "  止めてからもう一度実行してください(古いワーカーが仕事を横取りして、結果が汚れます)。")
    result = {"db": TARGET_DB, "n_requested": N}
    try:
        launch("api", ["-m", "uvicorn", f"{PKG}.main:app", "--port", str(PORT)])
        for _ in range(100):
            try:
                requests.get(BASE + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise SystemExit("[エラー] APIが起動しません。logs/e2_api.log を見てください。")
        launch("worker", ["-m", f"{PKG}.worker"])
        print("起動しました。8秒待って落ち着かせます...")
        time.sleep(8)
        off = clock_offset()
        print(f"DBの時計 − パソコンの時計 = {off * 1000:.1f} ms (この分を補正します)")

        rnd = random.Random(7)
        stamp = int(time.time())
        sent = {}
        for i in range(N):
            t = time.time()
            r = requests.post(f"{BASE}/api/v1/shift/start", json={"store_id": f"e2-{stamp}-{i}", "period": "2026-10"})
            if r.status_code != 202:
                raise SystemExit(f"[エラー] 投入に失敗 (HTTP {r.status_code}): {r.text}")
            sent[r.json()["thread_id"]] = t
            time.sleep(rnd.uniform(0.2, 1.3))
        print("送信完了。3秒待って集計します...")
        time.sleep(3)

        with psycopg.connect(DB_URL, autocommit=True) as c:
            rows = c.execute("SELECT thread_id, extract(epoch FROM created_at), extract(epoch FROM locked_at) "
                             "FROM jobs WHERE kind = 'start' AND thread_id = ANY(%s)", (list(sent),)).fetchall()
        client_lat, db_lat = [], []
        for tid, created, locked in rows:
            if locked is None:
                continue
            client_lat.append(float(locked) - (sent[tid] + off))
            db_lat.append(float(locked) - float(created))
        result["client_based"] = stats(client_lat)
        result["client_based"]["missing"] = N - len(client_lat)
        result["db_clock_only"] = stats(db_lat)
        result["clock_offset_ms"] = round(off * 1000, 1)
        print("\n[結果] 送信した時刻から、ワーカーが取りかかるまで(時計ずれ補正済み)")
        print(f"   {result['client_based']}")
        print("[参考] DBの時計だけで計算(登録→取りかかり)")
        print(f"   {result['db_clock_only']}")
        print("比較(中央値/95%/最大 ms): V2=528/998/1035, V3(直す前)=38/46/49, V3改(Linux)=39/49/62, V4=5/7/192")
        if result["client_based"]["missing"]:
            print(f"[注意] {result['client_based']['missing']} 件は取りかかりが記録されていません。ワーカーのログを確認してください。")
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        (HERE.parent / "e2_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("結果: harness/e2_result.json")


if __name__ == "__main__":
    main()