"""E1(C案): 何もしない60秒の負荷(DBへの問い合わせの数)。V6のE1と同じ測り方(pg_stat_database の前後の差)。
起動するもの: API(8098) + リレー + フロー処理器1 + ソルバーワーカー1。キューへの問い合わせはDBの数字に入らない(別のサービス)。
実行: python -m harness_c.run_e1_c"""
from harness_c.common_c import *

WINDOW = int(os.getenv("E1_WINDOW", "60"))


def snap():
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        r = c.execute("SELECT xact_commit + xact_rollback, sessions FROM pg_stat_database WHERE datname = %s", (TARGET_DB,)).fetchone()
        n = c.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (TARGET_DB,)).fetchone()
    if r is None or n is None:
        raise SystemExit(f"[エラー] DB '{TARGET_DB}' の統計が取れません。")
    return {"transactions": int(r[0]), "connections_opened": int(r[1]), "open_connections_now": int(n[0])}


def main():
    print(f"--- E1(C案): 何もしない{WINDOW}秒の負荷 ---  対象DB={TARGET_DB}")
    result = {"system": "C-min", "window_sec": WINDOW, "db": TARGET_DB}
    try:
        launch_api("e1_api", 8098)
        launch_relay("e1_relay")
        launch_flow("e1_flow")
        launch_solver("e1_solver")
        print("起動しました。8秒待って落ち着かせます...")
        time.sleep(8)
        a = snap()
        print(f"開始時: {a}")
        t0 = time.time()
        print(f"何もせず {WINDOW} 秒待ちます(この間はAPIを叩かないでください)...")
        time.sleep(WINDOW)
        b = snap()
        dt = round(time.time() - t0, 1)
        result.update({"seconds": dt, "transactions": b["transactions"] - a["transactions"],
                       "connections_opened": b["connections_opened"] - a["connections_opened"],
                       "open_connections_at_start": a["open_connections_now"], "open_connections_at_end": b["open_connections_now"]})
        print(f"\n[結果] {dt}秒間で  トランザクション {result['transactions']} 回 / 新しく開かれた接続 {result['connections_opened']} 回")
        print(f"       (参考) 開いている接続: 開始時 {a['open_connections_now']} → 終了時 {b['open_connections_now']}")
        print("比較: V2=120回/59接続, V3(直す前)=6回/2接続, V3改(Linux)=15回/6接続 (ワーカー1台・60秒)")
    finally:
        kill_all()
        save("e1_c_result", result)


if __name__ == "__main__":
    main()
