"""
E5-追加: DBが止まっている間、接続の失敗がなぜ「10秒」かかるのかを調べる。
  仮説(推測です): 'localhost' が IPv6(::1) と IPv4(127.0.0.1) の2つに分かれ、5秒の時間切れを2回待っている。
  → 'localhost' / '127.0.0.1' / '::1' で、それぞれ接続にかかる時間を、DB停止中と通常時で測る。

実行(LangGraphフォルダで):  python harness\\run_e5_why10.py     (約1分)
DBの止め方・起動のしかたは E5 と同じ(環境変数 E5_STOP_CMD / E5_START_CMD で変えられる)。
"""
import os
import shlex
import socket
import subprocess
import time
from urllib.parse import urlparse

import psycopg

DB_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")
u = urlparse(DB_URL)
PORT = u.port or 5432
STOP = shlex.split(os.getenv("E5_STOP_CMD", "docker compose -f docker-compose.proto.yml stop db"))
START = shlex.split(os.getenv("E5_START_CMD", "docker compose -f docker-compose.proto.yml start db"))
TIMEOUT = int(os.getenv("WHY10_TIMEOUT", "5"))


def timed(host):
    t = time.time()
    try:
        psycopg.connect(host=host, port=PORT, user=u.username, password=u.password,
                        dbname=u.path.lstrip("/"), connect_timeout=TIMEOUT).close()
        res = "接続できた"
    except Exception as e:  # noqa: BLE001
        res = type(e).__name__
    return round(time.time() - t, 1), res


def measure(label):
    print(f"\n[{label}]  connect_timeout={TIMEOUT}秒")
    out = {}
    for host in ("localhost", "127.0.0.1", "::1"):
        sec, res = timed(host)
        out[host] = (sec, res)
        print(f"  host={host:<10} → {sec:>5} 秒  ({res})")
    return out


def main():
    print("--- E5-追加: 接続失敗に10秒かかる理由 ---")
    print("localhost の名前解決:", sorted({a[4][0] for a in socket.getaddrinfo("localhost", PORT, type=socket.SOCK_STREAM)}))
    result = {}
    try:
        result["running"] = measure("DBが動いているとき")
        subprocess.run(STOP, check=True, capture_output=True)
        time.sleep(3)
        result["stopped"] = measure("DBを止めたとき")
    finally:
        try:
            subprocess.run(START, check=True, capture_output=True)
        except Exception as e:  # noqa: BLE001
            print("[注意] DBの再起動に失敗しました。手で起動してください:", e)
    print("\n読み方: 'localhost' だけが約10秒で、'127.0.0.1' が約5秒以下なら、2つのアドレスを5秒ずつ試している(仮説どおり)。")
    print("        どれも約5秒なら、仮説は外れ(別の理由)。どれも一瞬で失敗するなら、この環境では時間切れは働いていない。")
    import json
    with open("harness/e5_why10_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("結果: harness/e5_why10_result.json")


if __name__ == "__main__":
    main()