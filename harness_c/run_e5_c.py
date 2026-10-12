"""E5(C案): DBが止まったとき(Dockerで db コンテナを止めて再起動する)。V6のE5と同じA・B・Cに、C案だけの D を足した。
  A. 短い停止(5秒)の後に出した仕事が、何秒で「承認待ち」になるか(3回)
  B. 長い停止(45秒): 停止中のAPIの返事 / 4つのプロセス(リレー・フロー処理器・ソルバー・API)が生きているか / 復旧後に処理されるか
  C. リレー・フロー処理器・ソルバーを止めておいて3件入れ、DBを再起動 → 3つを起動 → 3件とも処理されるか
  D. (C案だけ)キューにつながらない20秒(dockerの一時停止): 停止中もAPIは受け付けるか(送信箱にたまる) / 復旧後に処理されるか
     ※ ElasticMQ は「再起動」するとメッセージが消える(保存しない設定)ので、止めずに一時停止する。本物のSQSは消えない。
DBの止め方・起動のしかたは、環境変数で変えられる(既定は docker compose)。
  E5_STOP_CMD / E5_START_CMD    既定: docker compose -f docker-compose.proto_c.yml stop db / start db
  E5_QSTOP_CMD / E5_QSTART_CMD  既定: docker compose -f docker-compose.proto_c.yml pause elasticmq / unpause elasticmq
実行: python -m harness_c.run_e5_c      (約4〜5分)"""
import shlex

from harness_c.common_c import *

F = os.getenv("COMPOSE_C", "docker-compose.proto_c.yml")
STOP = shlex.split(os.getenv("E5_STOP_CMD", f"docker compose -f {F} stop db"))
START = shlex.split(os.getenv("E5_START_CMD", f"docker compose -f {F} start db"))
QSTOP = shlex.split(os.getenv("E5_QSTOP_CMD", f"docker compose -f {F} pause elasticmq"))
QSTART = shlex.split(os.getenv("E5_QSTART_CMD", f"docker compose -f {F} unpause elasticmq"))
ALL = ("e5_api", "e5_relay", "e5_flow", "e5_solver")


def sh(cmd):
    subprocess.run(cmd, cwd=str(ROOT), check=True, capture_output=True)


def db_stop():
    sh(STOP)


def db_start():
    sh(START)
    return db_wait_ready()


def post_start(base, sid, timeout=40):
    t = time.time()
    try:
        r = requests.post(f"{base}/api/v1/shift/start", json={"store_id": sid, "period": "2026-10"}, timeout=timeout)
        return {"http": r.status_code, "sec": round(time.time() - t, 1)}
    except Exception as e:
        return {"http": type(e).__name__, "sec": round(time.time() - t, 1)}


def start_workers():
    launch_relay("e5_relay")
    launch_flow("e5_flow")
    launch_solver("e5_solver")


def main():
    print(f"--- E5(C案): DB停止テスト ---  対象DB={TARGET_DB}")
    require_clean()
    result = {"system": "C-min"}
    stamp = int(time.time())
    try:
        base = launch_api("e5_api", 8094)
        start_workers()
        time.sleep(8)

        lat = []
        for i in range(3):
            db_stop()
            time.sleep(5)
            ready = db_start()
            time.sleep(2)
            sid = f"e5a-{stamp}-{i}"
            post_start(base, sid)
            lat.append(wait_status(base, f"{sid}-2026-10", ("PAUSED_FOR_APPROVAL",), 90))
            print(f"A-{i + 1}: DB復旧に {ready} 秒 / 復旧後に出した仕事が承認待ちになるまで {lat[-1]} 秒")
        result["A_latency_after_short_outage_sec"] = lat

        db_stop()
        time.sleep(45)
        result["B_post_during_down"] = post_start(base, f"e5b-{stamp}-x", timeout=40)
        result["B_alive_after_45s"] = {n: alive(n) for n in ALL}
        ready = db_start()
        time.sleep(2)
        sid = f"e5b-{stamp}-after"
        post_start(base, sid)
        result["B_latency_after_long_outage_sec"] = wait_status(base, f"{sid}-2026-10", ("PAUSED_FOR_APPROVAL",), 90)
        result["B_alive_end"] = {n: alive(n) for n in ALL}
        print(f"B: 停止中のAPIの返事={result['B_post_during_down']} / 45秒後の生存={result['B_alive_after_45s']} "
              f"/ 復旧後の処理まで {result['B_latency_after_long_outage_sec']} 秒 / 最後の生存={result['B_alive_end']}")

        for n in ("e5_relay", "e5_flow", "e5_solver"):
            kill(n)
        sids = [f"e5c-{stamp}-{i}" for i in range(3)]
        for s in sids:
            post_start(base, s)
        db_stop()
        time.sleep(1)
        db_start()
        time.sleep(2)
        start_workers()
        time.sleep(20)
        ok3 = sum(1 for s in sids if run_status(base, f"{s}-2026-10") == "PAUSED_FOR_APPROVAL")
        result["C_queued_during_restart_processed_of_3"] = ok3
        print(f"C: DB再起動をまたいで残っていた仕事が処理された数 = {ok3} / 3")

        sids = [f"e5d-{stamp}-{i}" for i in range(3)]
        try:
            sh(QSTOP)
            time.sleep(1)
            posts = [post_start(base, s, timeout=15) for s in sids]
            time.sleep(20)
            unsent = q("SELECT count(*) FROM outbox WHERE sent_at IS NULL")[0][0]
            result["D_post_during_queue_down"] = posts
            result["D_outbox_unsent_during_queue_down"] = unsent
            result["D_alive_during_queue_down"] = {n: alive(n) for n in ALL}
        finally:
            try:
                sh(QSTART)
            except Exception as e:
                print("[注意] キューの再開に失敗:", e)
        time.sleep(1)
        t0 = time.time()
        ok_d = 0
        while time.time() - t0 < 120:
            ok_d = sum(1 for s in sids if run_status(base, f"{s}-2026-10") == "PAUSED_FOR_APPROVAL")
            if ok_d == 3:
                break
            time.sleep(0.5)
        result["D_processed_of_3"] = ok_d
        result["D_seconds_after_queue_back"] = round(time.time() - t0, 1)
        print(f"D: キュー停止中のAPIの返事={result.get('D_post_during_queue_down')} / 送信箱に残った未送信={result.get('D_outbox_unsent_during_queue_down')} "
              f"/ 復旧後に処理された数 {ok_d}/3 ({result['D_seconds_after_queue_back']}秒) / 停止中の生存={result.get('D_alive_during_queue_down')}")

        survived = all(result["B_alive_after_45s"].values()) and all(result["B_alive_end"].values())
        print("\n[まとめ] プロセス生存(DB45秒停止):", "OK" if survived else "落ちたものあり",
              "/ 仕事の保持(C):", "OK" if ok3 == 3 else "要確認", "/ キュー停止からの復旧(D):", "OK" if ok_d == 3 else "要確認")
    finally:
        kill_all()
        try:
            db_start()
        except Exception:
            pass
        try:
            sh(QSTART)
        except Exception:
            pass
        save("e5_c_result", result)


if __name__ == "__main__":
    main()
