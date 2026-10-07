# CoverShift 試作 V4 — Celery + Redis による分散タスクキュー

教授(10/1)の指摘「LangGraphはWeb APIの中ではなく別プロセスで。どう通信するのか」に対し、V2/V3での課題（自作DBポーリングやLISTEN/NOTIFYの複雑化）を踏まえ、**Redis** をメッセージブローカーとし、**Celery** を用いた業界標準の分散タスクキュー構成で実現した決定版です。

## V2 / V3 → V4 で変えたこと

| 項目                     | V2 / V3 (今までの試作)                         | V4                                                                                       |
| ------------------------ | ---------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **メッセージブローカー** | PostgreSQL (`jobs` ポーリング / LISTEN-NOTIFY) | **Redis (Port 6379)**                                                                    |
| **ワーカーのタスク管理** | 自作 `worker.py` (DBステータス手動管理)        | **Celery Worker (`cel_app.py`, `tasks.py`)**                                             |
| **タスク配送・信頼性**   | アプリ手動制御 (タイムアウト再取得など)        | **Celery (At-least-once 配送・自動リトライ・分散処理)**                                  |
| **API応答**              | 即時 `202 Accepted`                            | **即時 `202 Accepted`**                                                                  |
| **LangGraphが動く場所**  | 別プロセス `worker.py`                         | **Celery Worker プロセス**                                                               |
| **最適化ソルバー**       | ダミー / モック関数                            | **OR-Tools CP-SAT (実数計算・14シフト最適割り当て)**                                     |
| **HITL (承認待ち) 処理** | DBレコードの更新                               | **LangGraph `interrupt` + Celery 分離タスク (`process_shift_job` / `resume_shift_job`)** |
| **thread_id**            | `店舗ID-期間`                                  | `店舗ID-期間` (例: `store001-2026-10`)                                                   |

```text
 ブラウザ/check_flow ──HTTP──▶ FastAPI (main.py) ──delay()──▶ Redis (6379)
                         受付だけ (202)                    キュー保持
                                                             │
                                                             ▼ (POP)
                                                      Celery Worker (tasks.py)
                                                        ├── OR-Tools CP-SAT (main_solver.py)
                                                        └── LangGraph (main_graph.py)
```

## 動かし方(Windows / PowerShell)

`covershift_prototype_V4_celery_redis` フォルダの**親フォルダ**(`LangGraph`)で実行します。

```powershell
# 1. インフラを起動 (PostgreSQL: ポート5434, Redis: ポート6379)
docker compose -f docker-compose.proto_V4.yml up -d

# 2. 必要なライブラリのインストール
pip install celery redis ortools langgraph fastapi uvicorn

# 3. ターミナルを3つ開く (すべて LangGraph フォルダ直下で実行)
#   ターミナルA: Celery ワーカー (Windows環境のため -P solo オプションを指定)
celery -A covershift_prototype_V4_celery_redis.cel_app worker --loglevel=info -P solo

#   ターミナルB: FastAPI (受付 API)
uvicorn covershift_prototype_V4_celery_redis.main:app --port 8001

#   ターミナルC: E2E 動作確認テスト
python -m covershift_prototype_V4_celery_redis.check_flow
```

## 教授の5項目＋α との対応

| 確かめたいこと                                   | 確かめ方・結果                                                                              |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| **① APIとは別プロセスで LangGraph/CP-SATが動く** | API(FastAPI) と Celery ワーカーが完全別プロセス。重い処理中も API は 202 即時応答           |
| **② 応答待ちで止まっても状態が維持される**       | LangGraph の `interrupt` で一時停止。Celery は `PAUSED_FOR_APPROVAL` を返して終了           |
| **③ APIの合図で続きから動く**                    | `resume_shift_job` を Redis 経由で呼び出すことで、わずか 0.02秒で `COMPLETED` へ到達        |
| **④ 分散スケールアウト対応**                     | Redis キューを挟むため、ワーカープロセスを増設するだけで自動並列処理が可能                  |
| **⑤ 二重処理・シリアライズエラーの防止**         | HITL 停止時の状態を Pure Dict に整形し、Celery/Redis 間の JSON シリアライズ制限をクリア     |
| **(追加) CP-SAT による実数計算の統合**           | OR-Tools CP-SAT を組込み、条件（全員最低2日出勤）を満たす最適シフト（計14シフト）を自動算出 |

状況は `GET http://127.0.0.1:8001/api/v1/shift/{thread_id}` で確認できます。  
`status`: `QUEUED` → `RUNNING` → `PAUSED_FOR_APPROVAL` →(承認/再開)→ `RESUME_QUEUED` → `COMPLETED` / `REJECTED`

## 確認した結果

### Windows 11 (PowerShell / Celery 5.6.3 / Redis / Python 3.13)

- `check_flow` の一連のフロー（シフト自動作成 → 承認待ち一時停止 → 再開承認）が全ステップ正常通過。
- **初回タスク (`process_shift_job`)**:
  - OR-Tools CP-SAT 計算を実行（`assigned_total: 14` の `OPTIMAL` スケジュールを算出）。
  - LangGraph の `interrupt` で承認待ち停止し、`PAUSED_FOR_APPROVAL` ステータスを **0.08 秒** で返却。
- **再開タスク (`resume_shift_job`)**:
  - 店長承認リクエストを受信後、**0.02 秒** でチェックポイントから復元・再開し、`COMPLETED` 状態へ遷移完了。

## Windows(PowerShell)でのつまずきやすい点

| 症状                                                             | 原因                                                                          | 対処                                                                             |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `ValueError: Not implemented on THIS platform`                   | Windows 上で Celery のデフォルト (prefork) モードが動作しない                 | ワーカー起動時に `-P solo` (または `-P eventlet`) を付与する                     |
| `EncodeError: Object of type Interrupt is not JSON serializable` | LangGraph の `Interrupt` オブジェクトを直接 Celery レスポンスへ含めようとした | ワーカー側で辞書型 (`{"status": "PAUSED_FOR_APPROVAL", ...}`) に整形して返却する |
| `ImportError: circular import`                                   | モジュール間（`main_solver.py` 等）での自己参照・相互参照                     | インポート記述を整理し、`solver` と `graphs` のモジュール結合度を分離する        |
| **Redis 接続エラー (`Error 10061`)**                             | Redis サーバーが起動していない                                                | `docker compose -f docker-compose.proto_V4.yml up -d` でコンテナを起動する       |

## 確かめていないこと・限界

- ワーカー複数台起動時におけるタスクの優先度付きキューイング（Priority Queue）や負荷分散のチューニング。
- `MemorySaver` から PostgreSQL Checkpointer (`PostgresSaver`) への完全接続・DB永続化（現在はメモリチェックポインターを使用）。
- フロントエンド (Vue.js) や LINE Messaging API 実機との連携処理。
