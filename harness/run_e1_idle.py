"""
E1: 何もしない60秒の負荷(DBへの問い合わせの数)

測り方(V2・V3・V4の比較資料と同じ):
  PostgreSQLの統計 pg_stat_database から、対象DBの
    ・transactions(コミット+ロールバックの数)
    ・connections_opened(開かれた接続の数 = sessions)
  を、60秒の前後で取って、その差を出す。
  ※ 数える側は別のDB(postgres)につなぐので、測定そのものは数字に入らない。

やること(自動):
  1. API(ポート8098)とワーカーを1台起動
  2. 8秒待って落ち着かせる → 数字を記録 → 何もせず60秒待つ → 数字を記録
  3. 差を表示し、harness/e1_result.json に保存

注意: 測っている間は、pgAdmin・DBeaver・VSCodeのDB拡張など、
      同じDB(covershift_proto)につないでいるものを閉じてください(数字が増えます)。
      古いワーカー・APIも止めてください(PowerShellで Get-Process python)。

実行(LangGraphフォルダで):
    python -m harness.run_e1_real
"""
import json
import os
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
PORT = int(os.getenv("E1_PORT", "8098"))
WINDOW = int(os.getenv("E1_WINDOW", "60"))
LOGDIR = HERE.parent / "logs"
LOGDIR.mkdir(exist_ok=True)
env = os.environ.copy()
env.update({"PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT), "DATABASE_URL": DB_URL})
procs = []


def launch(name, args):
    f = open(LOGDIR / f"e1_{name}.log", "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable] + args, cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT)
    procs.append(p)
    return p


def snap():
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        r = c.execute("SELECT xact_commit + xact_rollback, sessions FROM pg_stat_database WHERE datname = %s",
                      (TARGET_DB,)).fetchone()
        n = c.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (TARGET_DB,)).fetchone()
    if r is None or n is None:
        raise SystemExit(f"[エラー] DB '{TARGET_DB}' の統計が取れません。DATABASE_URL のDB名を確認してください。")
    return {"transactions": int(r[0]), "connections_opened": int(r[1]), "open_connections_now": int(n[0])}


def main():
    print(f"--- E1: 何もしない{WINDOW}秒の負荷 ---  対象DB={TARGET_DB}")
    result = {"window_sec": WINDOW, "db": TARGET_DB}
    try:
        launch("api", ["-m", "uvicorn", f"{PKG}.main:app", "--port", str(PORT)])
        for _ in range(100):
            try:
                requests.get(f"http://127.0.0.1:{PORT}/", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise SystemExit("[エラー] APIが起動しません。logs/e1_api.log を見てください。")
        launch("worker", ["-m", f"{PKG}.worker"])
        print("起動しました。8秒待って落ち着かせます...")
        time.sleep(8)
        a = snap()
        print(f"開始時: {a}")
        t0 = time.time()
        print(f"何もせず {WINDOW} 秒待ちます(この間はAPIを叩かないでください)...")
        time.sleep(WINDOW)
        b = snap()
        dt = round(time.time() - t0, 1)
        d_tx = b["transactions"] - a["transactions"]
        d_cn = b["connections_opened"] - a["connections_opened"]
        result.update({"seconds": dt, "transactions": d_tx, "connections_opened": d_cn,
                       "open_connections_at_start": a["open_connections_now"],
                       "open_connections_at_end": b["open_connections_now"]})
        print(f"\n[結果] {dt}秒間で  トランザクション {d_tx} 回 / 新しく開かれた接続 {d_cn} 回")
        print(f"       (参考) 開いている接続: 開始時 {a['open_connections_now']} → 終了時 {b['open_connections_now']}")
        print("比較: V2=120回/59接続, V3(直す前)=6回/2接続, V3改(Linux)=15回/6接続  (すべてワーカー1台・60秒)")
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        (HERE.parent / "e1_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("結果: harness/e1_result.json")


if __name__ == "__main__":
    main()