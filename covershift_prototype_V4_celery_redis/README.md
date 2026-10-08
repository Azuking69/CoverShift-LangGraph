# CoverShift 試作 V4 — Celery + Redis による分散タスクキュー

教授(10/1)の指摘「LangGraphはWeb APIの中ではなく別プロセスで。どう通信するのか」に対し、**Redis** をメッセージブローカー(受け渡しの係)、**Celery** をタスクキューとして実現してみた**比較用の試作**です。V2・V3と同じ条件で比べるために作りました。**採用するかどうかは未決定です。**

## V2 / V3 → V4 で変えたこと

| 項目                     | V2 / V3 (今までの試作)                         | V4                                                                                       |
| ------------------------ | ---------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **メッセージブローカー** | PostgreSQL (`jobs` ポーリング / LISTEN-NOTIFY) | **Redis (Port 6379)**                                                                    |
| **ワーカーのタスク管理** | 自作 `worker.py` (DBステータス手動管理)        | **Celery Worker (`cel_app.py`, `tasks.py`)**                                             |
| **タスク配送・信頼性**   | V2: 期限切れの仕事を取り直す                   | **Celeryの既定のまま**。再試行・`acks_late` などの設定は入れていない(下の測定結果を参照) |
| **API応答**              | 即時 `202 Accepted`                            | 即時 `202 Accepted`                                                                      |
| **LangGraphが動く場所**  | 別プロセス `worker.py`                         | Celery Worker プロセス                                                                   |
| **ソルバー**             | ダミー / モック関数                            | OR-Tools CP-SAT(4人×7日、各日2人以上。**目的関数なし**＝条件を満たす割り当てを1つ出す)   |
| **状態の保存先**         | V2: PostgresSaver(DB)                          | **`MemorySaver`(ワーカーのメモリ)**                                                      |
| **HITL (承認待ち) 処理** | DBレコードの更新                               | LangGraph `interrupt` + Celery 分離タスク (`process_shift_job` / `resume_shift_job`)     |
| **状態の確認API**        | `GET /api/v1/shift/{thread_id}`                | **なし**(`POST /api/v1/shift` と `POST /api/v1/shift/{thread_id}/resume` の2つだけ)      |

```text
 ブラウザ/check_flow ──HTTP──▶ FastAPI (main.py) ──delay()──▶ Redis (6379)
                         受付だけ (202)                    キュー保持
                                                             │
                                                             ▼ (POP)
                                                      Celery Worker (tasks.py)
                                                        ├── OR-Tools CP-SAT (main_solver.py)
                                                        └── LangGraph (main_graph.py, MemorySaver)
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

> `docker-compose.proto_V4.yml` のRedisは、設定ファイルもvolumeも付けていない(`redis:7-alpine` の既定)。既定の保存設定は効くが、突然死・コンテナ作り直しでは待っている仕事が消える。

## 教授の5項目＋α との対応

| 確かめたいこと                                   | 結果                                                                                                                                                                                                                   |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **① APIとは別プロセスで LangGraph/CP-SATが動く** | API(FastAPI) と Celery ワーカーは別プロセス。計算中もAPIは202で即答する構成                                                                                                                                            |
| **② 応答待ちで止まっても状態が維持される**       | `interrupt` で一時停止し `PAUSED_FOR_APPROVAL` を返す。ただし**状態はワーカーのメモリ**にあるため、ワーカーを再起動すると消える                                                                                        |
| **③ APIの合図で続きから動く**                    | `resume_shift_job` で再開できる(1台のワーカーで確認。0.02秒)                                                                                                                                                           |
| **④ 分散スケールアウト**                         | 開始タスクは2台で並列に動く(20件・各2秒 → 20.8秒)。**ただし承認の再開は、状態を持たない別のワーカーに当たると `KeyError` で失敗する**(2台で 4/20 しか成功しなかった)。保存先を PostgresSaver に替えると 20/20 成功した |
| **⑤ 二重処理の防止**                             | **防止の仕組みはない。** 同じ `thread_id` を同時に2回送っても両方 202 になり、同じ仕事が2回動く。存在しない `thread_id` の `resume` も 202 を返し、後でワーカー内で `KeyError` になる                                  |
| **(追加) JSONシリアライズ**                      | `Interrupt` オブジェクトを辞書に整形して返し、Celery/Redis間のJSON制限をクリアした                                                                                                                                     |
| **(追加) CP-SAT**                                | 各日2人以上、という条件を満たす割り当てを算出(`assigned_total: 14`)。目的関数がないので「最適化」ではなく「条件を満たす割り当て」                                                                                      |

## 確認した結果

### Windows 11 (PowerShell / Celery 5.6.3 / Redis / Python 3.13)

- `check_flow` の一連のフロー（シフト作成 → 承認待ち一時停止 → 再開承認）が全ステップ通過した。
- 初回タスク `process_shift_job`: CP-SAT計算を実行し、`PAUSED_FOR_APPROVAL` を0.08秒で返却。
- 再開タスク `resume_shift_job`: 0.02秒で `COMPLETED` へ。

### Linux検証環境(2026-10-08 / Python 3.13 / PostgreSQL 16 / Redis / 1台・localhost / `-P solo`)

V2・V3・V4を同じ手順で測った(詳細は `V2_V3_V4_比較結果.pdf`)。

| 実験                                        | V4の結果                                                                                                                                                                                                                              |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 何もしない60秒の負荷                        | Redisへの命令91回・接続1(DBは使わない)                                                                                                                                                                                                |
| 仕事を出してから始まるまで(50回)            | 中央値5ms・最大192ms                                                                                                                                                                                                                  |
| 処理中にワーカーを `kill -9` して起動し直す | 70秒待っても再実行されない。Redis上に未確認(unacked)として残り、**再配信の待ち時間(`visibility_timeout`、既定3600秒)が過ぎるまで動かない**。15秒に縮めると約100秒後に再実行された。`task_acks_late` だけでは差が出なかった(`-P solo`) |
| 同時に二重送信                              | 10/10 が [202, 202]。同じ仕事が2回実行された                                                                                                                                                                                          |
| ワーカー2台(solo)で20件の承認               | **4/20 だけ成功**(残りは `KeyError`)。1台に子プロセス2つ(prefork)でも 8/20                                                                                                                                                            |
| 同じ構成で保存先だけ PostgresSaver          | 20/20 成功。ワーカーを全台 `kill -9` して起動し直しても承認できた                                                                                                                                                                     |
| Redisが止まる(20秒)                         | APIは約19秒固まって500。ワーカーは自動で再接続し、復旧後1.2秒で処理再開                                                                                                                                                               |
| Redisの再起動(既定の保存設定)               | 安全な停止(`docker stop` 相当)は待っていた3件が残る。突然死(`kill -9`)は3/3消える。volumeが無いのでコンテナを作り直しても消える(推測です。Dockerでは未測定)                                                                           |

## Windows(PowerShell)でのつまずきやすい点

| 症状                                                             | 原因                                                                          | 対処                                                                             |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `ValueError: Not implemented on THIS platform`                   | Windows 上で Celery のデフォルト (prefork) モードが動作しない                 | ワーカー起動時に `-P solo` (または `-P eventlet`) を付与する                     |
| `EncodeError: Object of type Interrupt is not JSON serializable` | LangGraph の `Interrupt` オブジェクトを直接 Celery レスポンスへ含めようとした | ワーカー側で辞書型 (`{"status": "PAUSED_FOR_APPROVAL", ...}`) に整形して返却する |
| `ImportError: circular import`                                   | モジュール間（`main_solver.py` 等）での自己参照・相互参照                     | インポート記述を整理し、`solver` と `graphs` のモジュール結合度を分離する        |
| **Redis 接続エラー (`Error 10061`)**                             | Redis サーバーが起動していない                                                | `docker compose -f docker-compose.proto_V4.yml up -d` でコンテナを起動する       |

## 確かめていないこと・限界

- **状態の確認API(GET)がない。** 結果はワーカーのログか、Celeryの結果(Redis)でしか見えない。
- **状態の保存は `MemorySaver`。** ワーカーを再起動すると、承認待ちの状態が消える。複数台では、別のワーカーに当たると再開できない(PostgresSaver に替えると解消した)。
- **二重防止・存在確認がない。** 同時の二重送信は両方通る。
- **落ちた仕事の再実行は、既定では1時間後**(`visibility_timeout`)。再試行・`task_acks_late` などは未設定。`prefork`(複数子プロセス)での `acks_late` の動きは未確認。
- **Redisの保存**: volume・AOF(毎操作の記録)は付けていない。AOF付きで測り直すかは未定。
- ワーカー複数台でのタスクの優先度付き・負荷分散のチューニング、Vue.js・LINE実機との連携は未確認。
- 費用・運用の面では、Redisという部品が1つ増える(AWSでは別の管理サービスが要る。料金は未調査)。
