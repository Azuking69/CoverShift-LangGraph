"""
E5: DBが止まったとき(Dockerで db コンテナを止めて再起動する)

  A. 短い停止(5秒)の後に出した仕事が、何秒で処理されるか(3回)。通知(NOTIFY)が届いたか
  B. 長い停止(45秒): 停止中のAPIの返事 / ワーカーが生きているか / 復旧後に処理されるか
  C. ワーカーを止めておいて3件入れ、DBを再起動 → ワーカー起動 → 3件とも処理されるか

DBの止め方・起動のしかたは、環境変数で変えられる(既定は docker compose)。
  E5_STOP_CMD  既定: docker compose -f docker-compose.proto.yml stop db
  E5_START_CMD 既定: docker compose -f docker-compose.proto.yml start db

実行(LangGraphフォルダで):  python -m harness.run_e5_real      (約3〜4分)
比較: V2=ワーカーが落ちて自分では戻らない / V3(直す前)=45秒で落ちる・再起動後は通知なし(約20秒遅れ)
      V3改(Linux)=45秒でも生存・復旧後0.5〜1.1秒
"""
import shlex

from harness.real_common import *

STOP = shlex.split(os.getenv("E5_STOP_CMD", "docker compose -f docker-compose.proto.yml stop db"))
START = shlex.split(os.getenv("E5_START_CMD", "docker compose -f docker-compose.proto.yml start db"))


def db_stop():
    subprocess.run(STOP, cwd=str(ROOT), check=True, capture_output=True)


def db_start():
    subprocess.run(START, cwd=str(ROOT), check=True, capture_output=True)
    return db_wait_ready()


def post_start(base, sid, timeout=40):
    t = time.time()
    try:
        r = requests.post(f"{base}/api/v1/shift/start", json={"store_id": sid, "period": "2026-10"}, timeout=timeout)
        return {"http": r.status_code, "sec": round(time.time() - t, 1)}
    except Exception as e:
        return {"http": type(e).__name__, "sec": round(time.time() - t, 1)}


def main():
    print(f"--- E5: DB停止テスト ---  対象DB={TARGET_DB}")
    require_clean()
    result = {}
    stamp = int(time.time())
    try:
        base = launch_api("e5_api", 8094)
        launch_worker("e5_w1")
        time.sleep(8)

        # A. 短い停止
        lat = []
        for i in range(3):
            db_stop()
            time.sleep(5)
            ready = db_start()
            time.sleep(2)
            sid = f"e5a-{stamp}-{i}"
            post_start(base, sid)
            lat.append(wait_status(base, f"{sid}-2026-10", ("PAUSED_FOR_APPROVAL",), 60))
            print(f"A-{i + 1}: DB復旧に {ready} 秒 / 復旧後に出した仕事が承認待ちになるまで {lat[-1]} 秒")
        try:
            txt = (LOGDIR / "e5_w1.log").read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            txt = ""
        notif = txt.count("NOTIFY受信")
        result["A_latency_after_short_outage_sec"] = lat
        result["A_notify_lines"] = notif
        print(f"A: 通知(NOTIFY)を受け取った回数 = {notif}(0なら、再接続後は通知でなく保険の確認で拾っている)")

        # B. 長い停止
        db_stop()
        t_down = time.time()
        time.sleep(45)
        result["B_post_during_down"] = post_start(base, f"e5b-{stamp}-x", timeout=40)
        result["B_worker_alive_after_45s"] = alive("e5_w1")
        ready = db_start()
        time.sleep(2)
        sid = f"e5b-{stamp}-after"
        post_start(base, sid)
        result["B_latency_after_long_outage_sec"] = wait_status(base, f"{sid}-2026-10", ("PAUSED_FOR_APPROVAL",), 60)
        result["B_worker_alive_end"] = alive("e5_w1")
        print(f"B: 停止中のAPIの返事={result['B_post_during_down']} / 45秒後ワーカー生存={result['B_worker_alive_after_45s']} "
              f"/ 復旧後の処理まで {result['B_latency_after_long_outage_sec']} 秒 / 最後まで生存={result['B_worker_alive_end']}")

        # C. ワーカー停止中に3件 → DB再起動 → ワーカー起動
        kill("e5_w1")
        sids = [f"e5c-{stamp}-{i}" for i in range(3)]
        for s in sids:
            post_start(base, s)
        db_stop()
        time.sleep(1)
        db_start()
        time.sleep(2)
        launch_worker("e5_w2")
        time.sleep(15)
        ok3 = sum(1 for s in sids if run_status(base, f"{s}-2026-10") == "PAUSED_FOR_APPROVAL")
        result["C_queued_during_restart_processed_of_3"] = ok3
        print(f"C: DB再起動をまたいで残っていた仕事が処理された数 = {ok3} / 3")
        survived = result["B_worker_alive_after_45s"] and result["B_worker_alive_end"]
        print("\n[まとめ] ワーカー生存(45秒停止):", "OK" if survived else "落ちた", "/ 仕事の保持:", "OK" if ok3 == 3 else "要確認")
    finally:
        kill_all()
        try:
            db_start()      # 念のため、DBを必ず起動した状態で終わらせる
        except Exception:
            pass
        save("e5_result", result)


if __name__ == "__main__":
    main()
