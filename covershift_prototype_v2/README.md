# CoverShift 試作 v2 — APIとワーカーを分ける

教授(10/1)の指摘「LangGraphはWeb APIの中ではなく別プロセスで。どう通信するのか」を、小さな試作で確かめるための版です。

## v1 → v2 で変えたこと

| | v1(今までの試作) | v2 |
|---|---|---|
| LangGraphが動く場所 | `main.py`(API)の中 | **別プロセス `worker.py`** |
| 状態の保存先 | `MemorySaver`(メモリ。再起動で消える) | **`PostgresSaver`(PostgreSQL)** |
| APIとワーカーの通信 | (同じプロセス) | **DBの依頼箱 `jobs` を介する** |
| `start` の返事 | 承認待ちまで待って返す | **すぐ 202 を返す。状況は GET で読む** |
| 二重の再開の合図 | 完了後だけ400 | **同時に2回来ても片方だけ通る(409)** |
| 却下 | 無限に solver に戻れる | **`MAX_REJECTS`(既定2)で打ち切り** |
| thread_id | `店舗ID-session` 固定 | `店舗ID-期間`(例: `store-101-2026-10`) |

```
 ブラウザ/curl ──HTTP──▶ API(main.py) ──SQL──▶ PostgreSQL ◀──SQL── ワーカー(worker.py)
                          受付だけ              runs / jobs          LangGraphを動かす
                                                 + checkpoint        (ソルバー・LLM・LINEもここ)
```

## 動かし方(Windows / PowerShell)

`covershift_prototype` フォルダの**親フォルダ**(`LangGraph`)で実行します。

```powershell
# 1. DBを起動(試作専用。ポート5434)
docker compose up -d

# 2. ライブラリを入れる(venvの中で)
pip install -r requirements.txt

# 3. ターミナルを3つ開く(どれも LangGraph フォルダで)
#   ターミナルA: API(受付)
uvicorn covershift_prototype.main:app --port 8000
#   ターミナルB: ワーカー(厨房)
python -m covershift_prototype.worker
#   ターミナルC: 動作確認
python -m covershift_prototype.check_flow
```

別のDBを使うときは、APIとワーカーの両方で `$env:DATABASE_URL="postgresql://ユーザー:パスワード@localhost:5433/DB名"` を設定します。

## 教授の5項目との対応

| 確かめたいこと | 確かめ方 |
|---|---|
| ① APIとは別プロセスでLangGraphが動く | ターミナルAとBが別。`worker.log` にだけ `job=...` が出る |
| ② 応答待ちで止まっても状態がDBに残る | `start` → `PAUSED_FOR_APPROVAL` を確認 → **AとBを両方 Ctrl+C で止める** |
| ③ APIの合図で続きから動く | `POST /api/v1/shift/resume` → `COMPLETED` になる |
| ④ 再起動しても再開できる | ②のあとA・Bを起動し直し、状態がまだ `PAUSED_FOR_APPROVAL` か確認 → `resume` |
| ⑤ 再開の合図が2回来ても二重に動かない | `check_flow` の [C]。同時に2回送って 202 と 409 になる |
| (追加)計算が重くてもAPIが止まらない | ワーカーだけ `$env:MOCK_SOLVER_SLEEP="8"` で起動 → 計算中に `GET /` を叩く |
| (追加)計算の途中でワーカーが死んでも復旧する | 上の状態でワーカーを強制終了 → `$env:JOB_TIMEOUT_SEC="5"` で起動し直す |

状況は `GET http://127.0.0.1:8000/api/v1/shift/{thread_id}` で見られます。
`status`: `QUEUED` → `RUNNING` → `PAUSED_FOR_APPROVAL` →(再開)→ `RESUME_QUEUED` → `RUNNING` → `COMPLETED` / `REJECTED` / `ERROR`

## 私の環境で確かめた結果

Linux・PostgreSQL 16・Python 3.13.13・langgraph 1.2.12 で、実際に動かして確かめました。

- `check_flow` の [A]〜[E] がすべて通った。
- 承認待ちで止めたあと、**APIもワーカーも `kill -9` で終了 → 起動し直し**、状態が残っていて、`resume` で `COMPLETED` になった。
- ワーカーが8秒の計算をしている間、`GET /` は約1ミリ秒で返った(APIが止まらない)。
- 計算の途中でワーカーを `kill -9` → 新しいワーカーを起動 → 依頼が取り直され(`attempts=2`)、`PAUSED_FOR_APPROVAL` まで進んだ。
- ワーカー2つ+依頼6件で、二重に処理された依頼は0件(ただし依頼が一瞬で終わるため、片方のワーカーが全部取った)。

## 確かめていないこと・限界

- **Windows と Docker での実行は、私は試していません。**
- 依頼の取り出しは、1秒ごとに聞きに行く方式(ポーリング)です。LISTEN/NOTIFYでの即時通知は、まだです。
- ソルバー・LLM・LINEは、すべてダミーです。本物のCP-SAT(数秒〜)・Claude API・LINE送信で、同じように動くかは未確認です。
- 同じ編成について、2つのワーカーが同時に別々の依頼を処理するのを防ぐ仕組みは、入れていません(今の流れでは、起きにくいはずです)。
- 画面(Vue)との接続、認証、DBの業務テーブルは、含みません。

## 注意: 元のファイルについて

v1のコードは `.pyc` から復元しました。`schemas.py` / `solver/mock_solver.py` は、元のファイルと見比べてください(復元できなかった部分は、辞書のキー名などを推測で補いました)。
