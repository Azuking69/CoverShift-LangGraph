import asyncio
import asyncpg
import json
import os
import psycopg

# ユーザー名: covershift / パスワード: covershift / DB名: covershift_proto に変更
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")

def process_job():
    """DBから未処理のジョブを1件取得して実行する"""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("""
                UPDATE jobs 
                SET status = 'RUNNING', locked_at = CURRENT_TIMESTAMP, attempts = attempts + 1
                WHERE id = (
                    SELECT id FROM jobs 
                    WHERE status = 'QUEUED' 
                    ORDER BY id ASC 
                    FOR UPDATE SKIP LOCKED 
                    LIMIT 1
                )
                RETURNING *;
            """)
            job = cur.fetchone()
            if not job:
                return False

            conn.commit()

            thread_id = job["thread_id"]
            kind = job["kind"]
            payload = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]

            print(f"[WORKER] ジョブ検知・処理開始: Job ID={job['id']}, Kind={kind}, Thread={thread_id}")

            try:
                if kind == "start":
                    cur.execute("""
                        UPDATE runs 
                        SET status = 'PAUSED_FOR_APPROVAL',
                            draft_shift = '10/02 早番: Aさん, 遅番: Bさん',
                            llm_explanation = '人件費とスキルのバランスを考慮して配置しました。',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE thread_id = %s;
                    """, (thread_id,))
                elif kind == "resume":
                    approved = payload.get("approved", False)
                    final_status = "COMPLETED" if approved else "REJECTED"
                    cur.execute("""
                        UPDATE runs 
                        SET status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE thread_id = %s;
                    """, (final_status, thread_id))

                cur.execute("UPDATE jobs SET status = 'done' WHERE id = %s;", (job["id"],))
                conn.commit()
                print(f"[WORKER] ジョブ完了: Job ID={job['id']}")
            except Exception as e:
                conn.rollback()
                cur.execute("UPDATE jobs SET status = 'failed', error = %s WHERE id = %s;", (str(e), job["id"]))
                cur.execute("UPDATE runs SET status = 'ERROR', error = %s WHERE thread_id = %s;", (str(e), thread_id))
                conn.commit()
                print(f"[WORKER] ジョブエラー: Job ID={job['id']}, Error={e}")

            return True

async def listen_and_work():
    """LISTEN通知を待機するイベントループ"""
    print("[WORKER] ワーカー起動。未処理ジョブのチェック中...")
    while process_job():
        pass

    conn = await asyncpg.connect(DATABASE_URL)

    def on_notification(connection, pid, channel, payload):
        print(f"\n⚡ [NOTIFY受信] チャンネル: {channel}, Job ID: {payload}")
        while process_job():
            pass

    await conn.add_listener("job_created", on_notification)
    print("📡 [LISTEN開始] DBからの通知 'job_created' をリアルタイム待機中... (Ctrl+C で終了)")

    try:
        while True:
            await asyncio.sleep(30)
            while process_job():
                pass
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(listen_and_work())