"""スケジューラーを『分ける』か『ワーカーに入れる』かの比較実験(約3分)。
  実行(LangGraphフォルダで):  python -m sched_lab.run_lab
  本番のコードには触らない。DBには lab_tasks / lab_notif_log という試験専用の表だけを作る。
  L1 スケジューラーを落として、起動し直す → 止まっていた間の連絡は、あとで送られるか
  L2 スケジューラーを2つ同時に動かす → 二重に送られるか(守りなし/あり)
  L3 重い計算(約8秒)の最中でも、スケジューラーは時刻どおりに動くか(A:別プロセス / B:ワーカーの中)
  L4 ワーカーだけが突然死んだら、連絡は止まるか(A / B)
"""
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

from . import core

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = Path(__file__).resolve().parent / "logs"
LOGDIR.mkdir(exist_ok=True)
procs = []


def spawn(mod, *args):
    f = open(LOGDIR / f"{mod}_{'_'.join(args)}.log".replace(" ", ""), "ab")
    p = subprocess.Popen([sys.executable, "-m", f"sched_lab.{mod}", *args], cwd=ROOT, stdout=f, stderr=f)
    procs.append(p)
    return p


def kill(p):
    if p.poll() is None:
        p.kill()
        p.wait()


def sleep_until(t0, sec):
    d = t0 + sec - time.time()
    if d > 0:
        time.sleep(d)


def report():
    with core.connect() as c:
        tasks = c.execute("SELECT id, extract(epoch FROM notified_at) IS NOT NULL FROM lab_tasks ORDER BY id").fetchall()
        logs = c.execute("SELECT task_id, sent_by, lateness_ms FROM lab_notif_log ORDER BY id").fetchall()
    late = {}
    for tid, who, ms in logs:
        late.setdefault(tid, []).append(ms)
    first = [min(v) for v in late.values()]
    return {
        "tasks": len(tasks),
        "notified_tasks": len(late),
        "log_rows": len(logs),
        "duplicate_rows": len(logs) - len(late),
        "late_median_ms": round(statistics.median(first)) if first else None,
        "late_max_ms": round(max(first)) if first else None,
        "per_task_late_ms": {t: round(min(v)) for t, v in sorted(late.items())},
    }


def l1():
    core.reset()
    core.add_tasks([3, 4, 5, 6, 7, 8])
    t0 = time.time()
    p = spawn("scheduler_main", "S1", "1")
    sleep_until(t0, 4.5)
    kill(p)  # 突然死
    sleep_until(t0, 9)
    spawn("scheduler_main", "S1b", "1")  # 起動し直し
    sleep_until(t0, 12.5)
    return report()


def l2(guard):
    core.reset()
    core.add_tasks([3 + 0.1 * i for i in range(40)])
    t0 = time.time()
    ps = [spawn("scheduler_main", "S1", guard), spawn("scheduler_main", "S2", guard)]
    sleep_until(t0, 10)
    for p in ps:
        kill(p)
    return report()


def l3(mode):
    core.reset()
    core.add_tasks([3 + i for i in range(20)])
    t0 = time.time()
    if mode == "A":
        spawn("scheduler_main", "S1", "1")
        spawn("busy_worker")
    else:
        spawn("embedded", "E1", "1")
    sleep_until(t0, 26)
    return report()


def l4(mode):
    core.reset()
    core.add_tasks([3 + i for i in range(10)])
    t0 = time.time()
    if mode == "A":
        spawn("scheduler_main", "S1", "1")
        w = spawn("busy_worker")
    else:
        w = spawn("embedded", "E1", "1")
    sleep_until(t0, 5.5)
    kill(w)  # ワーカー役だけ突然死(Bではスケジューラーも一緒に消える)
    sleep_until(t0, 15)
    r = report()
    r["notified_before_restart"] = r["notified_tasks"]
    if mode == "B":
        spawn("embedded", "E2", "1")  # 起動し直し
        sleep_until(t0, 19)
        r["after_restart"] = report()
    return r


def main():
    res = {}
    try:
        for name, fn in [("L1_スケジューラー突然死→再起動", l1), ("L2_二重起動(守りなし)", lambda: l2("0")),
                         ("L2_二重起動(守りあり)", lambda: l2("1")), ("L3_重い計算中(A:別プロセス)", lambda: l3("A")),
                         ("L3_重い計算中(B:ワーカー内)", lambda: l3("B")), ("L4_ワーカー突然死(A:別プロセス)", lambda: l4("A")),
                         ("L4_ワーカー突然死(B:ワーカー内)", lambda: l4("B"))]:
            print(f"--- {name} ...", flush=True)
            r = fn()
            for p in procs:
                kill(p)
            procs.clear()
            res[name] = r
            short = {k: v for k, v in r.items() if k != "per_task_late_ms"}
            print("   ", short, flush=True)
    finally:
        for p in procs:
            kill(p)
        out = Path(__file__).resolve().parent / "sched_lab_result.json"
        out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print("結果:", out)


if __name__ == "__main__":
    main()
