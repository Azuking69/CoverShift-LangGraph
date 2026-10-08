# CoverShift 試作 V3 — LISTEN/NOTIFYによる即時通知

v2での「1秒ごとのポーリングによる遅延」を解消するために、PostgreSQLの `LISTEN / NOTIFY` を使い、ジョブが入った瞬間にワーカーへ通知する構成を確かめるための版です。

> **この版の位置づけ:** V2・V3・V4を同じ条件で比べるための**比較用の試作**です。採用は未決定です。
> **重要:** この版のワーカーは、**LangGraphもCP-SATも実際には動かしていません**(「確かめていないこと・限界」を参照)。通知の仕組み(LISTEN/NOTIFY)だけを確かめる版です。

## v2 → V3 で変えたこと

|                    | v2(前回の試作)                 | V3                                                                                      |
| ------------------ | ------------------------------ | --------------------------------------------------------------------------------------- |
| ジョブ検知の仕組み | **1秒ごとのDBポーリング**      | **PostgreSQLの `LISTEN / NOTIFY` (即時通知)**                                           |
| 通知受信ライブラリ | `psycopg` (定期クエリ)         | **`asyncpg` (非同期リスナー待機)**                                                      |
| 検知の遅れ         | 中央値0.53秒・最大1.04秒(実測) | **中央値38ms・最大49ms(実測)**                                                          |
| ソルバー           | ダミー (`mock_solver.py`)      | `solver/main_solver.py` に CP-SAT のコードあり。**ワーカーからは呼ばれていない**        |
| LangGraph          | `worker.py` の中で実行         | `graphs/main_graph.py` にコードあり。**読み込みエラーで、ワーカーからも呼ばれていない** |
| ワーカーが書く結果 | LangGraphの実行結果            | **SQLで `runs` に固定の文を書く**(`'10/02 早番: Aさん, 遅番: Bさん'`)                   |
| DBユーザー・接続名 | `postgres` / `password`        | `covershift` / `covershift_proto`                                                       |

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
 │  - runs 表               │                             │
 └──────────────────────────┘                             ▼
                                              ┌──────────────────────────┐
                                              │ ワーカー (worker.py)     │
                                              │  - asyncpg (LISTEN待機)  │
                                              │  - SQLで runs を更新     │
                                              │    (LangGraph/CP-SATは未接続) │
                                              └──────────────────────────┘
```

## 動かし方(Windows / PowerShell)

`covershift_prototype_V3_listen_notify` フォルダの**親フォルダ**(`LangGraph`)で実行します。

```powershell
# 1. DBを起動(V3専用。ポート5434。covershift ユーザー)
docker compose -f docker-compose.proto.yml up -d

# 2. ライブラリを入れる(venvの中で)
pip install -r requirements.txt

# 3. ターミナルを3つ開く(どれも LangGraph フォルダで)。
#    ※先にAPIを起動する(テーブルはAPIの起動時に作られる。ワーカーを先に起動すると `UndefinedTable: jobs` で落ちる)
#    ターミナルA: API(受付)。ポート8001で起動
uvicorn covershift_prototype_V3_listen_notify.main:app --port 8001
#    ターミナルB: ワーカー(LISTEN待機)
python -m covershift_prototype_V3_listen_notify.worker
#    ターミナルC: 動作確認
$env:API_BASE="http://127.0.0.1:8001"
python -m covershift_prototype_V3_listen_notify.check_flow
```

別のDBを使うときは、APIとワーカーの両方で `$env:DATABASE_URL="postgresql://ユーザー:パスワード@localhost:5434/DB名"` を設定します。

## 課題・要件との対応

| 確かめたいこと                          | 確かめ方                                                        | 結果                                                       |
| --------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------- |
| ① DBトリガーとLISTEN/NOTIFYでの即時通知 | リクエスト直後、ワーカーのターミナルに `⚡ [NOTIFY受信]` が出る | 確認できた                                                 |
| ② ポーリング遅延の解消                  | 仕事を出してから始まるまでの時間(50回)                          | 中央値38ms(v2は528ms)                                      |
| ③ OR-Tools (CP-SAT) と LangGraph の連携 | ワーカーが `main_graph.py` / `main_solver.py` を実行する        | **確認できていない**(未接続)                               |
| ④ 二重再開の防止                        | `PAUSED_FOR_APPROVAL` で同時に `resume` を2回送る               | 10/10 が 202 と 409(確認できた)                            |
| ⑤ 通知取りこぼし対策（フォールバック）  | 30秒おきの定期チェック                                          | 未処理(`QUEUED`)の取りこぼしは拾える。ただし下の限界を参照 |

状況は `GET http://127.0.0.1:8001/api/v1/shift/{thread_id}` で見られます。
`status`: `QUEUED` → `RUNNING` → `PAUSED_FOR_APPROVAL` →(再開)→ `RESUME_QUEUED` → `RUNNING` → `COMPLETED` / `REJECTED` / `ERROR`
(この遷移は、ワーカーのSQLが書き換えているもので、LangGraphの状態ではありません)

## 確認した結果

### Windows(Docker Desktop / PowerShell)

- `check_flow` を実行した瞬間に、ワーカー側ターミナルで `⚡ [NOTIFY受信]` が出て、ポーリング遅延なしで処理が始まった。
- `asyncpg` の非同期ループで、トリガー関数 `notify_job_created()` からの通知を受け取れた。
- `PAUSED_FOR_APPROVAL` → `COMPLETED` までの状態遷移を確認した(ワーカーがSQLで状態を書き換える形。LangGraphの `interrupt()` ではない)。

### Linux検証環境(2026-10-08 / Python 3.13 / PostgreSQL 16 / Redis 7 系 / 1台・localhost)

V2・V3・V4を同じ手順で測った(詳細は `V2_V3_V4_比較結果.pdf`)。

| 実験                                        | V3の結果                                                                                           |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 何もしない60秒のDB負荷                      | 問い合わせ6回(v2は120回)                                                                           |
| 仕事を出してから始まるまで(50回)            | 中央値38ms・最大49ms                                                                               |
| 同時に二重の `resume`                       | 10/10 が [202, 409]                                                                                |
| 同時に二重の `start`                        | 4/10 が [202, 409]、**6/10 が [202, 500]**(主キー制約が守るのでデータは重複しない)                 |
| 処理中にワーカーを `kill -9` して起動し直す | **70秒待っても進まず**、`jobs` が `RUNNING` のまま止まる(回収の仕組みがない)                       |
| DBを再起動                                  | 待っていた仕事は残る。ただし**通知は再接続されず**、30秒ごとの確認で拾うまで最大30秒(約20秒)遅れる |
| DBが45秒止まる                              | 30秒ごとの確認で例外が出て**ワーカーが落ちる**                                                     |
| ワーカー2台で20件(各2秒)                    | 20.8秒・重複実行なし                                                                               |

## Windows(PowerShell)でのつまずきやすい点

| 症状                                              | 原因                                                         | 対処                                            |
| ------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------- |
| `ModuleNotFoundError: No module named 'asyncpg'`  | `asyncpg` が未インストール                                   | `pip install asyncpg` を実行する                |
| `psycopg.errors.UndefinedTable: jobs`             | ワーカーをAPIより先に起動した(テーブルはAPI起動時に作られる) | 先にAPIを起動する                               |
| `KeyboardInterrupt` / `CancelledError` で停止する | 起動中のワーカー画面で `Ctrl+C` を押した                     | 中断せず `📡 [LISTEN開始]` のまま待機させる     |
| PowerShellで `>>` が出てコマンドが動かない        | 改行やコピペで入力待ちになっている                           | `Ctrl+C` でキャンセルし、1行ずつ実行する        |
| `psycopg.errors.InvalidPassword` (認証エラー)     | DB初期化中（5〜10秒）のアクセスまたは設定不一致              | `docker compose logs db` で準備完了を確認後実行 |

## 確かめていないこと・限界

- **LangGraph・CP-SATは、ワーカーから呼ばれていない。** `graphs/main_graph.py` は、存在しない `covershift_prototype_V3_listen_notify.main_solver` を読み込もうとするため、読み込みエラーになる(ソルバーの実体は `solver/main_solver.py`)。チェックポインター(状態の保存)もない。
- **落ちた仕事の回収がない。** 処理中にワーカーが死ぬと、`jobs` が `RUNNING` のまま残る(v2は期限切れで取り直す)。
- **同時の二重 `start` で 500 になることがある**(「確認してから書く」ため)。
- **通知の接続が切れても再接続しない。** DBの再起動後は、30秒ごとの確認だけで動く。DBが止まっている間に確認が走ると、例外でワーカーが終了する。
- 大量の同時リクエスト(通知ラッシュ)時の取りこぼし、本物のLINE・Claude APIとの連携は未確認。
- 上の穴を直した版は「V3改」(`covershift_prototype_V3_fixed`)として別に用意してある(回収・原子的な開始・DB停止への耐性・通知の張り直し)。

## 注意: 設定の一致について

`docker-compose.proto.yml` の環境変数（`covershift` / `covershift` / `covershift_proto`）と、各コード（`db.py`, `worker.py`, `config.py`）の `DATABASE_URL` が一致していることを確認して実行してください。
