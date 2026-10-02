# CoverShift — LangGraph 試作リポジトリ

ドラッグストアのシフト編成を支援する **CoverShift** のうち、**LangGraph を使った「非同期 Human-in-the-Loop（人の承認待ち）シフト生成パイプライン」**を検証・試作するためのリポジトリです。

> 目的：「時間帯 × 業務」で本当に回るかを確かめる AI Agent の、中核部分（ソルバー → AI解説 → 店長承認 → 確定）を、小さく動かして確かめる。
> 原則：**AI は提案だけ。最終確定は人（管理者）。**

---

## 1. 設計の考え方

| 役割 | 担当 |
|---|---|
| 厳密なシフト配置の計算 | 数理最適化ソルバー（OR-Tools / CP-SAT）。**現在はダミー（モック）** |
| 配置結果の解釈・人向けの解説文 | LLM（個人情報は仮名化して渡し、検証して、実名に戻す）。**現在はダミー文** |
| 窓口 | FastAPI |
| 承認待ち（HITL） | LangGraph の `interrupt()` と `Command(resume=...)` |
| 最終確定 | 人（店長・管理者） |

---

## 2. フォルダ構成

```
LangGraph/
├── 001-Concept/                概念検証（1つずつ動かして確かめる小さなスクリプト）
│   ├── 01_simple_graph.py        最小の LangGraph（ノードと分岐）
│   ├── 02_llm_pipeline.py        LLM の処理の流れ（AI 解説・ガードレール）
│   └── 03_interrupt_demo.py      interrupt() で止まり、再開する動き
├── 002-api_integration/        API 連携の検証（FastAPI と非同期 HITL の連動）
│   ├── app.py                    FastAPI のアプリ
│   └── test_api.py               API の動作確認
├── covershift_prototype/       試作 v1（役割ごとにモジュール分割。API の中でグラフを動かす）
│   ├── graphs/main_graph.py      LangGraph 本体（solver → explain → manager_review → finalize）
│   ├── solver/mock_solver.py     ダミーのソルバー
│   ├── schemas.py                データの型
│   └── main.py                   FastAPI の窓口（start / resume）
├── covershift_prototype_v2/    試作 v2（API とワーカーを別プロセスに分離。状態を PostgreSQL に保存）
│   ├── config.py                 設定（環境変数）
│   ├── schemas.py                データの型
│   ├── db.py                     DB 操作（runs / jobs）
│   ├── main.py                   FastAPI の窓口（受付だけ。グラフは動かさない）
│   ├── worker.py                 ワーカー（LangGraph を動かす）
│   ├── check_flow.py             動作確認スクリプト
│   ├── graphs/main_graph.py      LangGraph 本体
│   ├── solver/mock_solver.py     ダミーのソルバー
│   └── README.md                 v2 の詳しい説明・動かし方
├── docker-compose.yml          元からあるファイル（web サービス）
├── docker-compose.proto.yml    v2 用の PostgreSQL（ポート 5434）
├── requirements.txt            ライブラリ一覧（v1・v2 共通）
├── README.md                   このファイル
└── .gitignore
```

### 概念検証（`001-Concept`、`002-api_integration`）

| ファイル | 内容（ファイル名からの推測を含む） |
|---|---|
| `001-Concept/01_simple_graph.py` | 最小の LangGraph。ノードと分岐（ルーティング）を確かめる |
| `001-Concept/02_llm_pipeline.py` | LLM を使った解説文の流れ。個人情報の仮名化・検証・実名復元（ガードレール）を確かめる |
| `001-Concept/03_interrupt_demo.py` | `interrupt()` で人の承認待ちに止まり、`Command(resume=...)` で再開する動き |
| `002-api_integration/app.py` | 上の流れを FastAPI から呼ぶ（非同期 HITL との連動） |
| `002-api_integration/test_api.py` | `app.py` の動作確認 |

実行方法：【要確認：各ファイルの実行コマンドを記入】

---

## 3. v1 と v2 の違い

| | v1 `covershift_prototype/` | v2 `covershift_prototype_v2/` |
|---|---|---|
| LangGraph が動く場所 | API（`main.py`）の中 | **別プロセス `worker.py`** |
| 状態の保存先 | `MemorySaver`（メモリ。再起動で消える） | **`PostgresSaver`（PostgreSQL）** |
| API とグラフの通信 | 同じプロセスで関数呼び出し | **DB の依頼箱 `jobs` を介する** |
| `start` の応答 | 承認待ちまで待って返す | **すぐ 202 を返し、状況は GET で読む** |
| 再開の合図が 2 回来たとき | 完了後の 2 回目だけ 400 | **同時に 2 回来ても片方だけ通る（409）** |
| 却下 | 無限に `solver` へ戻れる | **`MAX_REJECTS`（既定 2）で打ち切り** |
| `thread_id` | `店舗ID-session` 固定 | `店舗ID-期間`（例：`store-101-2026-10`） |

```
 [v2]
 ブラウザ/curl ──HTTP──▶ API (main.py) ──SQL──▶ PostgreSQL ◀──SQL── ワーカー (worker.py)
                          受付だけ              runs / jobs           LangGraph を動かす
                                                 + checkpoint
```

---

## 4. 準備

- Python 3.13 / Docker Desktop（v2 のみ）

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 5. 動かし方（Windows / PowerShell、`LangGraph` フォルダで）

### v1

```powershell
uvicorn covershift_prototype.main:app --port 8002
```

別のターミナルで：

```powershell
# 開始 → PAUSED_FOR_APPROVAL（承認待ち）で止まる
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/api/v1/shift/start -ContentType "application/json" -Body '{"store_id":"store-101"}'

# 承認 → COMPLETED
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/api/v1/shift/resume -ContentType "application/json" -Body '{"thread_id":"store-101-session","approved":true}'
```

### v2

```powershell
# DB（v2 専用。既存の docker-compose.yml とは別ファイル）
docker compose -f docker-compose.proto.yml up -d

# ターミナル A: API
uvicorn covershift_prototype_v2.main:app --port 8001
# ターミナル B: ワーカー
python -m covershift_prototype_v2.worker
# ターミナル C: 動作確認
$env:API_BASE="http://127.0.0.1:8001"
python -m covershift_prototype_v2.check_flow
```

詳しい説明・確認項目・つまずきやすい点は、[`covershift_prototype_v2/README.md`](covershift_prototype_v2/README.md) を参照してください。

> **注意：** `docker compose up` だけだと、元からある `docker-compose.yml`（`web` サービス）が起動します。v2 の DB は、必ず `-f docker-compose.proto.yml` を付けて起動します。

---

## 6. 確認済みのこと・未確認のこと

| | 状態 |
|---|---|
| v1：start → `interrupt()` で停止 → resume → `COMPLETED` | 確認済み（Windows） |
| v2：別プロセスで動く／止まっても状態が DB に残る／続きから動く／再起動しても再開できる／再開の合図が 2 回来ても二重に動かない | 確認済み（Windows + Docker） |
| v2：重い計算中も API が止まらない／計算の途中でワーカーが死んでも復旧する | Linux 環境のみ確認 |
| 本物のソルバー（CP-SAT）・LLM・LINE での動作 | **未確認**（現在はすべてダミー） |
| 複数ワーカーでの分担、スケジューラー（締切で編成を開始） | **未実装・未確認** |

---

## 7. 今後の予定

1. 構成図の描き直し（API・ワーカー・スケジューラー・DB）
2. スケジューラーの試作（締切での編成開始、応答待ちの時限）
3. `mock_solver.py` を OR-Tools / CP-SAT へ段階的に置き換え
4. LLM 呼び出しの実装（AI 解説：仮名化 → 呼び出し → 形式・内容の検査 → 実名復元）
5. LINE 送信ノードを「送信」と「待機」に分割
6. 複数ワーカー対応（同じ編成の排他）、コネクションプール、マイグレーションの導入

---

## 8. 開発メモ

- コミットメッセージは、`種別: 内容` の形式（種別：`feat` `fix` `refactor` `docs` `chore` `test`）。
- `__pycache__/`、`*.pyc`、`venv/`、`.env` は Git に入れない（`.gitignore` で除外）。
- `config.py` の DB パスワードの既定値は、開発用です。**本番では使いません。**
- 設計書・仕様書は、このリポジトリの外で管理しています。【要確認：置き場所を記入】

---

## 9. チーム

| 役割 | 担当 |
|---|---|
| リーダー | イ・スンヒョク |
| 技術担当 | アズキ |
| 記録 | イ・ヒョクジュン |
