# CoverShift 試作 v2 — APIとワーカーを分ける

教授(10/1)の指摘「LangGraphはWeb APIの中ではなく別プロセスで。どう通信するのか」を、小さな試作で確かめるための版です。

## v1 → v2 で変えたこと

|                     | v1(今までの試作)                      | v2                                     |
| ------------------- | ------------------------------------- | -------------------------------------- |
| LangGraphが動く場所 | `main.py`(API)の中                    | **別プロセス `worker.py`**             |
| 状態の保存先        | `MemorySaver`(メモリ。再起動で消える) | **`PostgresSaver`(PostgreSQL)**        |
| APIとワーカーの通信 | (同じプロセス)                        | **DBの依頼箱 `jobs` を介する**         |
| `start` の返事      | 承認待ちまで待って返す                | **すぐ 202 を返す。状況は GET で読む** |
| 二重の再開の合図    | 完了後だけ400                         | **同時に2回来ても片方だけ通る(409)**   |
| 却下                | 無限に solver に戻れる                | **`MAX_REJECTS`(既定2)で打ち切り**     |
| thread_id           | `店舗ID-session` 固定                 | `店舗ID-期間`(例: `store-101-2026-10`) |

```
 ブラウザ/curl ──HTTP──▶ API(main.py) ──SQL──▶ PostgreSQL ◀──SQL── ワーカー(worker.py)
                          受付だけ              runs / jobs          LangGraphを動かす
                                                 + checkp

                                                 oint        (ソルバー・LLM・LINEもここ)
```

## 動かし方(Windows / PowerShell)

`covershift_prototype_v2` フォルダの**親フォルダ**(`LangGraph`)で実行します。コマンドの中のフォルダ名は、`covershift_prototype_v2` です(`covershift_prototype` はv1)。

```powershell
# 1. DBを起動(試作専用。ポート5434。既存の docker-compose.yml とは別ファイル)
docker compose -f docker-compose.proto.yml up -d

# 2. ライブラリを入れる(venvの中で。requirements.txt は LangGraph フォルダ直下)
pip install -r requirements.txt

# 3. ターミナルを3つ開く(どれも LangGraph フォルダで)。ワーカーを起動し忘れると、依頼が QUEUED のまま進まない
#   ターミナルA: API(受付)。ポート8000が使用中なら8001など別のポートにする
uvicorn covershift_prototype_v2.main:app --port 8001
#   ターミナルB: ワーカー(厨房)
python -m covershift_prototype_v2.worker
#   ターミナルC: 動作確認
$env:API_BASE="http://127.0.0.1:8001"
python -m covershift_prototype_v2.check_flow
```

別のDBを使うときは、APIとワーカーの両方で `$env:DATABASE_URL="postgresql://ユーザー:パスワード@localhost:5433/DB名"` を設定します。

## 教授の5項目との対応

| 確かめたいこと                               | 確かめ方                                                                    |
| -------------------------------------------- | --------------------------------------------------------------------------- |
| ① APIとは別プロセスでLangGraphが動く         | ターミナルAとBが別。ワーカーのターミナルにだけ `job=...` が出る             |
| ② 応答待ちで止まっても状態がDBに残る         | `start` → `PAUSED_FOR_APPROVAL` を確認 → **AとBを両方 Ctrl+C で止める**     |
| ③ APIの合図で続きから動く                    | `POST /api/v1/shift/resume` → `COMPLETED` になる                            |
| ④ 再起動しても再開できる                     | ②のあとA・Bを起動し直し、状態がまだ `PAUSED_FOR_APPROVAL` か確認 → `resume` |
| ⑤ 再開の合図が2回来ても二重に動かない        | `check_flow` の [C]。同時に2回送って 202 と 409 になる                      |
| (追加)計算が重くてもAPIが止まらない          | ワーカーだけ `$env:MOCK_SOLVER_SLEEP="8"` で起動 → 計算中に `GET /` を叩く  |
| (追加)計算の途中でワーカーが死んでも復旧する | 上の状態でワーカーを強制終了 → `$env:JOB_TIMEOUT_SEC="5"` で起動し直す      |

状況は `GET http://127.0.0.1:8001/api/v1/shift/{thread_id}` で見られます(ポートは、起動時の `--port` に合わせる)。
`status`: `QUEUED` → `RUNNING` → `PAUSED_FOR_APPROVAL` →(再開)→ `RESUME_QUEUED` → `RUNNING` → `COMPLETED` / `REJECTED` / `ERROR`

## 確認した結果

### Windows(Docker Desktop)

- `check_flow` の [A]〜[E] がすべて通った(ポート8001)。
- 承認待ちで止めたあと、**APIとワーカーを両方止めて起動し直した**(プロセスIDと開始時刻が変わったことを `Get-CimInstance` で確認)。状態は `PAUSED_FOR_APPROVAL` のまま残り、`resume` で `COMPLETED` になった(`updated_at` は再起動後の時刻)。
- `jobs` はすべて `done`、`attempts` は1(二重処理なし)。

### Linux検証環境(Python 3.13.13 / PostgreSQL 16.15 / langgraph 1.2.12)

- 上と同じ確認に加えて、次を確認した。
  - ワーカーが8秒の計算をしている間も、`GET /` は約1ミリ秒で返る(APIが止まらない)。
  - 計算の途中でワーカーを `kill -9` → 新しいワーカーを起動すると、依頼が取り直されて(`attempts=2`)承認待ちまで進む。
  - ワーカー2つ+依頼6件で、二重処理は0件(ただし片方のワーカーが全部取った)。

2026-10-08に、V3・V4と同じ手順で測り直した(詳細は `V2_V3_V4_比較結果.pdf`)。

- 何もしない60秒のDB負荷: 問い合わせ120回・接続59回(ワーカー1台)。
- 仕事を出してから始まるまで(50回): 中央値528ms・最大1035ms(1秒ごとに聞くので、その範囲内)。
- 処理中にワーカーを `kill -9` して起動し直す: 期限10秒の設定で、再起動後 **18.3秒**で取り直して承認待ちまで進んだ(`attempts=2`)。
- 同時に二重の `start`・二重の `resume`: どちらも 10/10 が [202, 409]。
- ワーカー2台で20件(各2秒): 22.2秒、重複実行なし。承認20/20 成功。
- DBを再起動: 待っていた仕事は残った。

## Windows(PowerShell)でのつまずきやすい点

| 症状                                                          | 原因                                          | 対処                                           |
| ------------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------- |
| `docker compose` で `dockerDesktopLinuxEngine` が見つからない | Docker Desktop が起動していない               | 起動して、エンジンが動くまで待つ               |
| `No module named covershift_prototype.worker`                 | フォルダ名と違う名前で呼んだ                  | `covershift_prototype_v2` で呼ぶ               |
| `[WinError 10048]`                                            | ポート8000が使用中                            | `--port 8001` にし、`$env:API_BASE` を合わせる |
| `check_flow` が `QUEUED` のまま止まる                         | ワーカーを起動していない                      | ワーカーを起動する(依頼はDBに残っている)       |
| `Invoke-RestMethod` の日本語が化ける                          | PowerShell の文字コード。DBの値は壊れていない | `curl.exe -s URL` で取得する                   |
| `curl.exe -d` で `json_invalid`                               | PowerShell が `\"` のクォートを消す           | `Invoke-RestMethod ... -Body '{"..."}'` を使う |

## 確かめていないこと・限界

- Windows では、「重い計算中のAPI応答」と「計算の途中でのワーカー強制終了」は未確認(Linuxでのみ確認)。
- 依頼の取り出しは、1秒ごとに聞きに行く方式(ポーリング)です。LISTEN/NOTIFYでの即時通知は、まだです。
- ソルバー・LLM・LINEは、すべてダミーです。本物のCP-SAT(数秒〜)・Claude API・LINE送信で、同じように動くかは未確認です。
- 同じ編成について、2つのワーカーが同時に別々の依頼を処理するのを防ぐ仕組みは、入れていません(今の流れでは、起きにくいはずです)。
- 画面(Vue)との接続、認証、DBの業務テーブルは、含みません。

## 注意: 元のファイルについて

v2 の `schemas.py` と `solver/mock_solver.py` は、v1 の `.pyc` から復元して作成した(辞書のキー名などは一部推測)。v1 の元ファイルと見比べて、差分を確認すること。
