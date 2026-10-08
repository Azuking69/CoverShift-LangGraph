# CoverShift 試作 V6（仮）— V5(通知版) + LangGraph + PostgresSaver

V5（LISTEN/NOTIFY版）は、ワーカーが「固定の文をDBに書くだけ」で、LangGraphを動かしていませんでした。
V6は、V5の仕事の取り方（通知・10秒ごとの保険・期限切れ回収・再接続）はそのままに、
**V2のLangGraph（solver → 説明 → 承認待ち(interrupt) → 確定）と PostgresSaver** を載せた版です。

## V5 → V6 で変えたこと

| | V5 | V6 |
|---|---|---|
| ワーカーの中身 | 固定の文を `runs` に書くだけ | **LangGraph を動かす**（`graphs/main_graph.py`、V2と同じ） |
| グラフの途中状態 | なし | **PostgresSaver**（PostgreSQL に保存） |
| 承認待ち(interrupt) | 擬似（状態を書くだけ） | **本物**（止まって、再開の依頼で続きから動く） |
| 落ちた仕事の回収 | 期限切れRUNNINGを取り直す | 同じ + **最後のチェックポイントから続きを動かす**（`handle_job`） |
| DB再起動後 | （グラフ無し） | グラフ用の接続が古くなっても、**作り直して1回やり直す**（`GraphHolder`） |
| ソルバー | なし | V2の `mock_solver.py`（ダミー）。待ち時間は `MOCK_SOLVER_SLEEP` か `EXP_SLEEP` |

## 動くファイル

| ファイル | 役割 |
|---|---|
| `main.py` | API（受付だけ）。二重開始は 409、二重承認も 409 |
| `db.py` | 表の作成・トリガー(NOTIFY)・登録・`update_run`（ワーカーが結果を書く） |
| `worker.py` | 通知待ち + 10秒ごとの保険 → 仕事を取る → `handle_job`（LangGraph実行）→ 結果を `runs` に写す |
| `graphs/main_graph.py` | LangGraph 本体（V2と同じ） |
| `solver/mock_solver.py` | ダミーのソルバー（V2と同じ）。`solver/main_solver.py`（CP-SAT）は今は使っていない |
| `config.py` / `schemas.py` | 設定・型 |

## 動かし方（Windows / PowerShell）

`LangGraph` フォルダ（このフォルダの親）で。V2で使っている `docker-compose.proto.yml` のDB（ポート5434）をそのまま使えます。

```powershell
docker compose -f docker-compose.proto.yml up -d
pip install -r requirements.txt     # langgraph, langgraph-checkpoint-postgres, psycopg[binary,pool], asyncpg, fastapi, uvicorn など

# ターミナルA（先にAPI。表を作るのはAPI）
uvicorn covershift_prototype_v6_langgraph.main:app --port 8001
# ターミナルB
python -m covershift_prototype_v6_langgraph.worker
# ターミナルC
$env:API_BASE="http://127.0.0.1:8001"
python -m covershift_prototype_v6_langgraph.check_flow
```

## 環境変数

| 名前 | 既定 | 意味 |
|---|---|---|
| `DATABASE_URL` | `postgresql://covershift:covershift@localhost:5434/covershift_proto` | DB |
| `JOB_TIMEOUT_SEC` | 30 | 処理中のまま、この秒数を過ぎた仕事は「ワーカーが死んだ」とみなして取り直す。**ソルバーの最長時間より長くする**（短いと二重実行になる・推測です） |
| `JOB_MAX_ATTEMPTS` | 3 | 回収のやり直しの上限 |
| `WORKER_FALLBACK_SEC` | 10 | 通知を取りこぼしても、この秒数以内に拾う保険の確認の間隔 |
| `MOCK_SOLVER_SLEEP` / `EXP_SLEEP` | 0 | ダミーのソルバーに、わざと待たせる秒数（試験用） |
| `MAX_REJECTS` | 2 | 却下の上限回数 |

## まだ無いこと・注意

- ソルバーはダミー（本物のCP-SATではない）。LLM・LINEも未接続。
- DBが止まっている間に処理中だった仕事は、`JOB_TIMEOUT_SEC` 経過後に回収される（それまでRUNNINGのまま）。
- 通知が取れなくても、`WORKER_FALLBACK_SEC` 以内に拾う（通知は「速くするため」、保険は「確実にするため」）。
- 実験用の `EXP_SLEEP` は本番では使わない（既定0のまま）。
