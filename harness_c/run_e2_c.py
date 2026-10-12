"""E2(C案): 仕事を出してから、処理が始まるまでの遅れ(50回)。V6のE2と同じ並び(間隔0.2〜1.3秒のランダム・乱数の種=7)。
V6は「API受付 → ワーカーが仕事を取る」まで。C案は「API受付 → 送信箱 → リレー → キュー → フロー処理器が取りかかる」まで(2回の受け渡しを含む)。
  遅れ = events.started_at(フロー処理器が受け取って処理を始めた時刻) − 送信した時刻(DBの時計のずれは補正)
  参考: 同じ件が「承認待ち」になるまでの全体の時間(C案は ソルバーワーカーまで往復する)も出す。
実行: python -m harness_c.run_e2_c"""
import random

from harness_c.common_c import *

N = int(os.getenv("E2_N", "50"))


def main():
    print(f"--- E2(C案): 仕事を出してから始まるまでの遅れ({N}回) ---  対象DB={TARGET_DB}")
    require_clean()
    result = {"system": "C-min", "db": TARGET_DB, "n_requested": N}
    try:
        base = launch_api("e2_api", 8097)
        launch_relay("e2_relay")
        launch_flow("e2_flow")
        launch_solver("e2_solver")
        print("起動しました。8秒待って落ち着かせます...")
        time.sleep(8)
        off = clock_offset()
        print(f"DBの時計 − パソコンの時計 = {off * 1000:.1f} ms (この分を補正します)")
        rnd = random.Random(7)
        stamp = int(time.time())
        sent = {}
        for i in range(N):
            t = time.time()
            r = requests.post(f"{base}/api/v1/shift/start", json={"store_id": f"e2-{stamp}-{i}", "period": "2026-10"})
            if r.status_code != 202:
                raise SystemExit(f"[エラー] 投入に失敗 (HTTP {r.status_code}): {r.text}")
            sent[r.json()["thread_id"]] = t
            time.sleep(rnd.uniform(0.2, 1.3))
        print("送信完了。3秒待って集計します...")
        time.sleep(3)
        rows = q("SELECT e.thread_id, extract(epoch FROM o.created_at), extract(epoch FROM e.started_at) "
                 "FROM events e JOIN outbox o ON e.event_id = 'ob-' || o.id "
                 "WHERE e.kind = 'start' AND e.thread_id = ANY(%s)", (list(sent),))
        client_lat, db_lat = [], []
        for tid, created, started in rows:
            client_lat.append(float(started) - (sent[tid] + off))
            db_lat.append(float(started) - float(created))
        result["client_based"] = stats(client_lat)
        result["client_based"]["missing"] = N - len(client_lat)
        result["db_clock_only"] = stats(db_lat)
        result["clock_offset_ms"] = round(off * 1000, 1)
        paused = q("SELECT thread_id, extract(epoch FROM updated_at) FROM runs WHERE thread_id = ANY(%s) AND status = 'PAUSED_FOR_APPROVAL'", (list(sent),))
        full = [float(u) - (sent[t] + off) for t, u in paused]
        result["reference_until_paused"] = stats(full)
        result["reference_until_paused"]["missing"] = N - len(full)
        print("\n[結果] 送信した時刻から、フロー処理器が取りかかるまで(時計ずれ補正済み)")
        print(f"   {result['client_based']}")
        print("[参考] DBの時計だけで計算(送信箱に書いた時刻→取りかかり)")
        print(f"   {result['db_clock_only']}")
        print("[参考] 送信してから「承認待ち」になるまで(ソルバーワーカーへの往復を含む。V6の測定とは別物)")
        print(f"   {result['reference_until_paused']}")
        print("比較(中央値/95%/最大 ms): V2=528/998/1035, V3(直す前)=38/46/49, V3改(Linux)=39/49/62, V4=5/7/192")
        if result["client_based"]["missing"]:
            print(f"[注意] {result['client_based']['missing']} 件は取りかかりが記録されていません。logs/e2_*.log を確認してください。")
    finally:
        kill_all()
        save("e2_c_result", result)


if __name__ == "__main__":
    main()
