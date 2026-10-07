# CoverShift 試作 V3 — LISTEN/NOTIFYによる即時通知

v2での「1秒ごとのポーリングによる遅延」を解消し、PostgreSQLの `LISTEN / NOTIFY` トリガー機能を用いて、ジョブが投入された瞬間にワーカーへ即時通知・実行する構成を確かめるための版です。

## v2 → V3 で変えたこと

|                    | v2(前回の試作)                | V3                                            |
| ------------------ | ----------------------------- | --------------------------------------------- |
| ジョブ検知の仕組み | **1秒ごとのDBポーリング**     | **PostgreSQLの `LISTEN / NOTIFY` (即時通知)** |
| 通知受信ライブラリ | `psycopg` (定期クエリ)        | **`asyncpg` (非同期リスナー待機)**            |
| 検知レスポンス     | 平均 0.5秒〜1秒のラグ発生     | **即時（ミリ秒単位）で検知・処理開始**        |
| ソルバーの実装     | 完全ダミー (`mock_solver.py`) | **OR-Tools (CP-SAT) による最適化計算**        |
| LangGraph構築      | 単一スクリプト内構成          | **`main_graph.py` による状態遷移制御**        |
| DBユーザー・接続名 | `postgres` / `password`       | **`covershift` / `covershift_proto`**         |

```
 ブラウザ / curl
       │
  (1) POST /api/v1/shift/start
       ▼
 ┌──────────────────────────┐
 │  API (main.py)           │
 │  - ジョブ受付 (202 Queued) │
 └────────────┬─────────────┘
              │ (2) INSERT (Job)
              ▼
 ┌──────────────────────────┐      (3) NOTIFY 'job_created'
 │ PostgreSQL (DB)          │─────────────────────────────┐
 │  - jobs 表 (Trigger)     │                             │
 │  - checkpoint / runs     │                             │
 └──────────────────────────┘                             ▼
                                              ┌──────────────────────────┐
                                              │ ワーカー (worker.py)     │
                                              │  - asyncpg (LISTEN待機)  │
                                              │  - LangGraph 実行        │
                                              │  - CP-SAT ソルバー計算   │
                                              └──────────────────────────┘
```

## 動かし方(Windows / PowerShell)

`covershift_prototype_V3_listen_notify` フォルダの**親フォルダ**(`LangGraph`)で実行します。コマンドの中のフォルダ名は、`covershift_prototype_V3_listen_notify` です。

```powershell
# 1. DBを起動(V3専用。ポート5434。covershift ユーザー)
docker compose -f docker-compose.proto.yml up -d

# 2. ライブラリを入れる(venvの中で。asyncpg や ortools などが入っていること)
pip install -r requirements.txt

# 3. ターミナルを3つ開く(どれも LangGraph フォルダで)。
#    ターミナルA: API(受付)。ポート8001で起動
uvicorn covershift_prototype_V3_listen_notify.main:app --port 8001
#    ターミナルB: ワーカー(LISTEN待機)
python -m covershift_prototype_V3_listen_notify.worker
#    ターミナルC: 動作確認
$env:API_BASE="[http://127.0.0.1:8001](http://127.0.0.1:8001)"
python -m covershift_prototype_V3_listen_notify.check_flow
```

別のDBを使うときは、APIとワーカーの両方で `$env:DATABASE_URL="postgresql://ユーザー:パスワード@localhost:5434/DB名"` を設定します。

## 課題・要件との対応

| 確かめたいこと                           | 確かめ方                                                                    |
| ---------------------------------------- | --------------------------------------------------------------------------- |
| ① DBトリガーとLISTEN/NOTIFYでの即時通知  | リクエスト直後、ワーカーのターミナルに即座に `⚡ [NOTIFY受信]` が出る       |
| ② ポーリング遅延の解消                   | 1秒の待機時間なく、ミリ秒単位でワーカーがジョブを検知・処理開始する         |
| ③ OR-Tools (CP-SAT) と LangGraph の連携  | `main_solver.py` の最適化計算が `main_graph.py` 経由で正常に実行される      |
| ④ 承認待ち(HITL)と二重再開防止の継続検証 | `PAUSED_FOR_APPROVAL` 状態での停止と、重複 `resume` に対する 409 エラー制御 |
| ⑤ 通知取りこぼし対策（フォールバック）   | LISTEN待機に加え、定期チェック（30秒おき）の二重構成でジョブ処理を保証する  |

状況は `GET http://127.0.0.1:8001/api/v1/shift/{thread_id}` で見られます(ポートは、起動時の `--port` に合わせる)。
`status`: `QUEUED` → `RUNNING` → `PAUSED_FOR_APPROVAL` →(再開)─▶ `RESUME_QUEUED` → `RUNNING` → `COMPLETED` / `REJECTED` / `ERROR`

## 実証された機能・要件

| 検証項目                     | 詳細と実績                                                                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **① 即時通知とイベント駆動** | DBへの `INSERT` 発生時に PostgreSQL トリガーから `NOTIFY job_created` が即座に発火し、`asyncpg` を待機するワーカーがミリ秒単位でリアルタイム検知。                 |
| **② 非同期 HITL (店長承認)** | LangGraph の `interrupt()` で一時停止 (`PAUSED_FOR_APPROVAL`) し、承認リクエスト後に `Command(resume=...)` で再開される非同期 Human-in-the-Loop フローが正常機能。 |
| **③ 状態保持と永続化**       | `thread_id` (`store001-2026-10`) に基づき、チェックポインター経由で実行状態と進捗スナップショットが保持・更新。                                                    |
| **④ 2段階ステータス遷移**    | `QUEUED` → `RUNNING` → `PAUSED_FOR_APPROVAL` → `RESUME_QUEUED` → `RUNNING` → `COMPLETED` の一連のライフサイクルが完全完結。                                        |

## 確認した結果（課題・要件への対応結果）

| 確かめたいこと                               | 実証・確認した結果                                                                                                                 |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **① DBトリガーとLISTEN/NOTIFYでの即時通知**  | リクエスト直後、ワーカーターミナルに `⚡ [NOTIFY受信] チャンネル: job_created` が即座に出力され、トリガー通知が捕捉された。        |
| **② ポーリング遅延の解消**                   | v2のような1秒間隔のポーリング待機なく、ミリ秒単位でワーカーが `Job ID=1`, `Job ID=2` を検知・処理開始した。                        |
| **③ OR-Tools (CP-SAT) と LangGraph の連携**  | `main_graph.py` 経由で `main_solver.py` (CP-SAT) の最適化計算が正常実行され、シフト案の生成まで完結した。                          |
| **④ 承認待ち(HITL)と二重再開防止の継続検証** | `PAUSED_FOR_APPROVAL` で正常停止し、`resume` リクエストで再開された。二重送信時は 409 Conflict エラー制御が維持されている。        |
| **⑤ 通知取りこぼし対策（フォールバック）**   | LISTENリアルタイム待機に加え、30秒周期の定期チェックがバックグラウンドで並行動作し、通知取りこぼしを二重保護できる構成を確認した。 |

### Windows(Docker Desktop / PowerShell)

- `check_flow` を実行した瞬間に、ワーカー側ターミナルで `⚡ [NOTIFY受信]` が検知され、ポーリング遅延なしで即座にジョブ処理が実行された。
- `asyncpg` を用いた非同期イベントループにより、PostgreSQLのトリガー関数 `notify_job_created()` からの通知が正常に捕捉された。
- OR-Tools CP-SAT ソルバーでのシフト計算および LangGraph による状態保持・承認フロー（`PAUSED_FOR_APPROVAL` → `COMPLETED`）まで一気通貫で確認できた。

## Windows(PowerShell)でのつまずきやすい点

| 症状                                              | 原因                                            | 対処                                            |
| ------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------- |
| `ModuleNotFoundError: No module named 'asyncpg'`  | `asyncpg` が未インストール                      | `pip install asyncpg` を実行する                |
| `KeyboardInterrupt` / `CancelledError` で停止する | 起動中のワーカー画面で `Ctrl+C` を押した        | 中断せず `📡 [LISTEN開始]` のまま待機させる     |
| PowerShellで `>>` が出てコマンドが動かない        | 改行やコピペで入力待ちになっている              | `Ctrl+C` でキャンセルし、1行ずつ実行する        |
| `psycopg.errors.InvalidPassword` (認証エラー)     | DB初期化中（5〜10秒）のアクセスまたは設定不一致 | `docker compose logs db` で準備完了を確認後実行 |

## 確かめていないこと・限界

- 大量の同時リクエスト（通知ラッシュ）発生時における `LISTEN/NOTIFY` キューの溢れや取りこぼし検証。
- 本物の LINE Messaging API や Claude API との外部通信連携時のエラーハンドリング。
- 複数台のワーカープロセスを分散並列起動した際の、`LISTEN/NOTIFY` 通知の奪い合いとスケール特性。

## 注意: 設定の一致について

`docker-compose.proto.yml` の環境変数（`covershift` / `covershift` / `covershift_proto`）と、各コード（`db.py`, `worker.py`, `config.py`）の `DATABASE_URL` が一致していることを確認して実行してください。
