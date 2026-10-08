"""
V4(Celery + Redis) の Windows 用の試験。Redis と Celery だけを測る(V4専用。V6の試験とは別)。

  A. Redis の保存: 順番待ちの列に仕事を3件入れた後、Redisを止める/殺す/作り直す → 3件は残るか
       A1 安全な停止 (docker compose stop → start)
       A2 突然死    (docker kill → start)
       A3 コンテナの作り直し (docker compose rm -sf → up)   ※ composeに volume が無いので、消える見込み(推測です)
       A4 対策案の確認: AOF(appendonly) + volume 付きのRedisを別に立てて、突然死でも残るか
  B. Redis停止中のAPI/ワーカー: 20秒止める → 停止中のPOSTの返事 / ワーカーは自動で再接続するか / 戻った後に処理されるか
  C. 待機の負荷: ワーカーを待機させて60秒、Redisへの命令数と、新しく開かれた接続の数

実行(LangGraphフォルダで。事前に docker compose -f docker-compose.proto_V4.yml up -d redis ):
    python -m harness.run_v4_redis_real       (約3〜4分)
前提: pip install celery redis (V4のREADME手順)。V4のフォルダ名が違う場合は、環境変数 PKG4 で指定。
操作コマンドは、環境変数で変えられる(既定は docker compose):
    V4_COMPOSE (既定 docker-compose.proto_V4.yml) / V4_REDIS_SERVICE (既定 redis) / V4_REDIS_CONTAINER (既定 covershift_redis_v4)
"""
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import redis
import requests

PKG = os.getenv("PKG4", "covershift_prototype_V4_celery_redis")
HERE = Path(__file__).resolve().parent
ROOT = None
for _p in (HERE, HERE.parent, HERE.parent.parent):
    if (_p / PKG).is_dir():
        ROOT = _p
        break
if ROOT is None:
    raise SystemExit(f"[エラー] フォルダ '{PKG}' が見つかりません。harness を同じ階層に置いてください。")
ROOT = Path(ROOT)  # 型チェック用(上でNoneなら終了している)

COMPOSE = os.getenv("V4_COMPOSE", "docker-compose.proto_V4.yml")
SERVICE = os.getenv("V4_REDIS_SERVICE", "redis")
CONTAINER = os.getenv("V4_REDIS_CONTAINER", "covershift_redis_v4")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
LOGDIR = HERE / "logs"
LOGDIR.mkdir(exist_ok=True)
procs = {}


def sh(cmd, check=False):
    return subprocess.run(shlex.split(cmd) if isinstance(cmd, str) else cmd, cwd=str(ROOT), capture_output=True, text=True, check=check)


def dc(*a):
    return sh(["docker", "compose", "-f", COMPOSE, *a])


def R(url=None):
    return redis.Redis.from_url(url or REDIS_URL, socket_connect_timeout=2, socket_timeout=3)


def wait_redis(url=None, limit=60):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            if R(url).ping():
                return round(time.time() - t0, 1)
        except Exception:
            time.sleep(0.3)
    return None


def qlen(url=None):
    for _ in range(10):
        try:
            return R(url).llen("celery")
        except Exception:
            time.sleep(0.5)
    return None


def launch(name, args, extra_env=None):
    env = os.environ.copy()
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT), "REDIS_URL": REDIS_URL})
    env.update({k: str(v) for k, v in (extra_env or {}).items()})
    f = open(LOGDIR / f"{name}.log", "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable] + args, cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT)
    procs[name] = p
    return p


def kill_all():
    for n, p in list(procs.items()):
        if p.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            else:
                p.kill()
        procs.pop(n, None)


def launch_api(port):
    launch("v4_api", ["-m", "uvicorn", f"{PKG}.main:app", "--port", str(port)])
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            requests.get(base + "/docs", timeout=1)
            return base
        except Exception:
            time.sleep(0.25)
    raise SystemExit("[エラー] APIが起動しません。logs/v4_api.log を見てください。")


def launch_worker(name="v4_worker"):
    # Windows は prefork が使えないので -P solo
    return launch(name, ["-m", "celery", "-A", f"{PKG}.cel_app", "worker", "--loglevel=info", "-P", "solo"])


def post(base, tid, timeout=40):
    t = time.time()
    try:
        r = requests.post(f"{base}/api/v1/shift", json={"thread_id": tid, "data": {"store_id": tid}}, timeout=timeout)
        return {"http": r.status_code, "sec": round(time.time() - t, 1), "task_id": (r.json().get("task_id") if r.status_code == 202 else None)}
    except Exception as e:
        return {"http": type(e).__name__, "sec": round(time.time() - t, 1), "task_id": None}


def task_state(task_id):
    try:
        return R().get(f"celery-task-meta-{task_id}")
    except Exception:
        return None


def wait_done(task_id, limit=60):
    t0 = time.time()
    while time.time() - t0 < limit:
        v = task_state(task_id)
        text = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v or "")
        if '"SUCCESS"' in text:
            return round(time.time() - t0, 1)
        time.sleep(0.2)
    return None


def push3(tag):
    """ワーカー無しで、API経由で3件、列に入れる"""
    base = launch_api(8101)
    ids = [post(base, f"{tag}{i}", 15)["task_id"] for i in range(3)]
    kill_all()
    return qlen()


def part_a(res):
    print("\n=== A. Redisの保存(順番待ちの列に仕事3件) ===")
    out = {}
    wait_redis()
    cases = [
        ("A1_安全な停止(stop→start)", lambda: dc("stop", SERVICE), lambda: dc("start", SERVICE)),
        ("A2_突然死(kill→start)", lambda: sh(["docker", "kill", CONTAINER]), lambda: sh(["docker", "start", CONTAINER])),
        ("A3_作り直し(rm→up)", lambda: (dc("stop", SERVICE), dc("rm", "-f", SERVICE)), lambda: dc("up", "-d", SERVICE)),
    ]
    for label, stopper, starter in cases:
        wait_redis()
        try:
            R().flushall()
        except Exception:
            pass
        before = push3(label[:2])
        stopper()
        time.sleep(1)
        starter()
        ready = wait_redis()
        after = qlen()
        out[label] = {"queue_before": before, "queue_after": after, "redis_back_sec": ready}
        print(f"{label}: 前={before} → 後={after}   (Redisが戻るまで {ready} 秒)")
    # A4: AOF + volume つきのRedisを別に立てて、突然死でも残るか(対策案の確認)
    print("A4: 対策案(AOF + volume)の確認...")
    name, vol, port = "cs_redis_aof_test", "cs_redis_aof_test_vol", 6390
    url = f"redis://localhost:{port}/0"
    sh(["docker", "rm", "-f", name])
    sh(["docker", "volume", "rm", "-f", vol])
    sh(["docker", "run", "-d", "--name", name, "-p", f"{port}:6379", "-v", f"{vol}:/data", "redis:7-alpine",
        "redis-server", "--appendonly", "yes", "--appendfsync", "everysec"])
    try:
        wait_redis(url)
        R(url).flushall()
        global REDIS_URL
        old = REDIS_URL
        REDIS_URL = url
        before = push3("a4")
        REDIS_URL = old
        time.sleep(2)  # everysec: 1秒ごとに保存されるのを待つ
        sh(["docker", "kill", name])
        sh(["docker", "start", name])
        ready = wait_redis(url)
        after = qlen(url)
        out["A4_AOF+volume(kill→start)"] = {"queue_before": before, "queue_after": after, "redis_back_sec": ready}
        print(f"A4_AOF+volume(kill→start): 前={before} → 後={after}")
    finally:
        sh(["docker", "rm", "-f", name])
        sh(["docker", "volume", "rm", "-f", vol])
    res["A"] = out


def part_b(res):
    print("\n=== B. Redis停止中のAPI・ワーカー(20秒停止) ===")
    wait_redis()
    R().flushall()
    base = launch_api(8102)
    launch_worker()
    time.sleep(10)
    ok = post(base, "bpre")
    print("停止前の確認:", ok, "処理完了まで", wait_done(ok["task_id"]) if ok["task_id"] else None, "秒")
    dc("stop", SERVICE)
    time.sleep(3)
    during = post(base, "bdown", timeout=40)
    print("停止中のPOSTの返事:", during)
    time.sleep(max(0, 20 - during["sec"] - 3))
    t_back = time.time()
    dc("start", SERVICE)
    ready = wait_redis()
    after = None
    for _ in range(40):  # 再接続待ち(待ち時間が延びる)
        a = post(base, f"bafter{int(time.time())}", timeout=10)
        if a["http"] == 202:
            after = a
            break
        time.sleep(1)
    done = wait_done(after["task_id"], 90) if after and after["task_id"] else None
    alive = procs.get("v4_worker") is not None and procs["v4_worker"].poll() is None
    txt = ""
    try:
        txt = (LOGDIR / "v4_worker.log").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        pass
    res["B"] = {"post_during_outage": during, "redis_back_sec": ready,
                "post_accepted_after": after, "task_done_after_restore_sec": done,
                "sec_from_restore_to_task_done": round(time.time() - t_back, 1) if done is not None else None,
                "worker_alive": alive, "log_has_connection_lost": ("Connection to broker lost" in txt) or ("broker" in txt and "lost" in txt)}
    print("B:", json.dumps(res["B"], ensure_ascii=False))


def part_c(res):
    print("\n=== C. 待機の負荷(ワーカーだけ起動して60秒) ===")
    kill_all()
    time.sleep(1)
    wait_redis()
    R().flushall()
    launch_worker("v4_worker_idle")
    time.sleep(15)

    def snap():
        i = R().info("stats")
        return i["total_commands_processed"], i["total_connections_received"]

    c0, k0 = snap()
    time.sleep(60)
    c1, k1 = snap()
    res["C"] = {"redis_commands_60s": c1 - c0 - 1, "connections_opened_60s": k1 - k0 - 1,
                "note": "測定用の接続自身の分(INFO 1回・接続1本)を引いた"}
    print("C: 60秒間で Redisへの命令", res["C"]["redis_commands_60s"], "回 / 新しく開かれた接続", res["C"]["connections_opened_60s"], "本")
    print("   比較(Linux): 命令91回 / 接続1本")


def main():
    print(f"--- V4 (Celery + Redis) Windows試験 ---  対象フォルダ: {ROOT / PKG}")
    print(f"compose={COMPOSE} / service={SERVICE} / container={CONTAINER}")
    if wait_redis(limit=5) is None:
        raise SystemExit(f"[停止] Redisに接続できません。先に起動してください:  docker compose -f {COMPOSE} up -d redis")
    res = {}
    try:
        part_a(res)
        part_b(res)
        part_c(res)
    finally:
        kill_all()
        try:
            dc("start", SERVICE)
        except Exception:
            pass
        (HERE / "v4_redis_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n結果: harness/v4_redis_result.json")


if __name__ == "__main__":
    main()