"""
E3: ワーカー突然死 → 復旧テスト(本物の強制終了版)

やること(すべてこのスクリプトが自動で行う):
  1. API と ワーカー1 を起動(APIは別ポート 8099。あなたが起動中のAPIには触らない)
  2. シフト作成を1件投入し、ワーカー1が「処理中(RUNNING)」になるのを待つ
  3. ワーカー1を強制終了(Windowsでも Linuxでも「即死」。Ctrl+Cのようなきれいな終了ではない)
  4. ワーカー2を起動し、承認待ち(PAUSED_FOR_APPROVAL)まで進むまでの秒数と attempts を測る
  5. 成功/失敗を表示し、結果を harness/e3_result.json に保存

前提: ワーカーに「重い計算の代わりの待ち時間」(環境変数 EXP_SLEEP)と
      「期限切れ回収」(JOB_TIMEOUT_SEC)がある版。v5_notify の worker.py には両方ある。

実行(LangGraphフォルダ = harness と covershift_prototype_v5_notify が並ぶ場所で):
    python harness/run_e3_real.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

PKG = os.getenv("PKG", "covershift_prototype_v5_notify")
HERE = Path(__file__).resolve()

# パッケージのフォルダを自動で探す(harness の置き場所が違っても動くように)
ROOT = None
for p in (HERE.parent, HERE.parent.parent, HERE.parent.parent.parent):
    if (p / PKG).is_dir():
        ROOT = p
        break
if ROOT is None:
    raise SystemExit(f"[エラー] フォルダ '{PKG}' が見つかりません。\n"
                     f"  このスクリプトの場所: {HERE}\n"
                     f"  → '{PKG}' フォルダと同じ階層(または1つ上)に harness を置いてください。")
sys.path.insert(0, str(ROOT))

import importlib
db = importlib.import_module(f"{PKG}.db")

PORT = int(os.getenv("E3_PORT", "8099"))
BASE = f"http://127.0.0.1:{PORT}"
SLEEP = os.getenv("E3_SLEEP", "8")             # 処理に8秒かかることにする(重い計算の代わり)
TIMEOUT = os.getenv("JOB_TIMEOUT_SEC", "10")   # 10秒たった RUNNING は「死んだ」とみなして取り直す
LOGDIR = HERE.parent / "logs"
LOGDIR.mkdir(exist_ok=True)

env = os.environ.copy()
env.update({"EXP_SLEEP": SLEEP, "MOCK_SOLVER_SLEEP": SLEEP, "JOB_TIMEOUT_SEC": TIMEOUT,
            "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT)})

procs = []


def launch(name, args):
    f = open(LOGDIR / f"e3_{name}.log", "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable] + args, cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT)
    procs.append(p)
    return p


def job_rows(thread_id):
    with db.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, kind, status, attempts FROM jobs WHERE thread_id = %s ORDER BY id", (thread_id,))
            return [dict(r) for r in cur.fetchall()]


def run_status(thread_id):
    try:
        return requests.get(f"{BASE}/api/v1/shift/{thread_id}", timeout=3).json().get("status")
    except Exception:
        return None


def main():
    print("--- E3: ワーカー突然死・復旧テスト(本物の強制終了) ---")
    print(f"設定: 処理{SLEEP}秒 / 期限{TIMEOUT}秒 / 対象フォルダ {ROOT}")
    result = {"sleep_sec": SLEEP, "timeout_sec": TIMEOUT, "passed": False}
    try:
        launch("api", ["-m", "uvicorn", f"{PKG}.main:app", "--port", str(PORT)])
        for _ in range(100):
            try:
                requests.get(BASE + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise SystemExit("[エラー] APIが起動しません。logs/e3_api.log を見てください。")

        w1 = launch("worker1", ["-m", f"{PKG}.worker"])
        time.sleep(2)

        store = f"e3-{int(time.time())}"
        r = requests.post(f"{BASE}/api/v1/shift/start", json={"store_id": store, "period": "2026-10"})
        if r.status_code != 202:
            raise SystemExit(f"[エラー] 投入に失敗 (HTTP {r.status_code}): {r.text}")
        tid = r.json()["thread_id"]
        print(f"1. 投入成功 thread_id={tid}")

        # ワーカー1が処理中になるのを待つ
        running = False
        for _ in range(80):
            rows = job_rows(tid)
            if rows and rows[0]["status"] == "RUNNING":
                running = True
                break
            if rows and rows[0]["status"] in ("done", "failed"):
                break
            time.sleep(0.25)
        if not running:
            raise SystemExit("[エラー] 処理中(RUNNING)を捕まえられませんでした。\n"
                             "  ・ワーカーに待ち時間(EXP_SLEEP)が効いていない可能性があります(処理が一瞬で終わった)。\n"
                             f"  ・logs/e3_worker1.log を見てください。 jobs={job_rows(tid)}")
        time.sleep(1)
        print(f"2. ワーカー1が処理中: {job_rows(tid)}")

        w1.kill()          # 即死(Windows: TerminateProcess / Linux: SIGKILL)
        w1.wait()
        print("3. ワーカー1を強制終了しました")
        killed_status = run_status(tid)
        print(f"   強制終了直後の状態: run.status={killed_status}, jobs={job_rows(tid)}")

        t0 = time.time()
        launch("worker2", ["-m", f"{PKG}.worker"])
        print("4. ワーカー2を起動。回収されて承認待ちまで進むのを待ちます(最大70秒)...")
        final = None
        while time.time() - t0 < 70:
            st = run_status(tid)
            if st in ("PAUSED_FOR_APPROVAL", "WAITING_FOR_HUMAN", "COMPLETED"):
                final = st
                break
            time.sleep(0.5)
        secs = round(time.time() - t0, 1)
        rows = job_rows(tid)
        attempts = rows[0]["attempts"] if rows else None
        result.update({"thread_id": tid, "seconds_after_restart": secs if final else None,
                       "final_status": final, "jobs": rows, "attempts": attempts})
        if final and attempts and attempts >= 2:
            result["passed"] = True
            print(f"\n[成功] 再起動後 {secs} 秒で {final} まで進みました。attempts={attempts}(2以上＝やり直された証拠)")
        elif final:
            print(f"\n[要確認] 状態は進みましたが attempts={attempts} です。突然死前に完了していた可能性があります。")
        else:
            print(f"\n[失敗] 70秒待っても進みませんでした。 jobs={rows}")
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        (HERE.parent / "e3_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("結果: harness/e3_result.json")


if __name__ == "__main__":
    main()