# CoverShift-LangGraph

日本のシフト編成を支援する AI Agent「**CoverShift(カバーシフト)**」のうち、**LangGraph まわりの試作と実験**を置いたリポジトリです。大学のキャップストーン課題の一部です。

作るのは、特定の業種に限らない**日本のシフト編成全般**のための仕組みです。ドラッグストアでの実務経験を、要件の元(実証の土台)にしています。

> **これは完成品ではありません。** 「APIとは別のプロセスで LangGraph を動かすとき、どうやって通信するか」を、小さな試作で比べて確かめるための場所です。**採用する構成はまだ決まっていません。**

## 何を確かめているのか

教授から「LangGraph は Web API の中ではなく、別のプロセスで動かすこと。そのとき API とどう通信するのか」という指摘(2026-10-01)がありました。そこで、通信のしかたを変えた試作をいくつか作り、同じ試験で測って比べています。

- 仕事を渡す方法(DBを定期的に見る / DBの通知 / Redis / メッセージキュー)
- 途中で止まる・落ちる・二重に来る、といったときの動き
- 変更前後の数字の差

ルールは、**AIは提案だけ。最終確定は人(管理者)** です。

## フォルダの案内

### 試作(通信のしかたの違い)

| フォルダ | 内容 | 状態 |
|---|---|---|
| `covershift_prototype` | v1。API の中で LangGraph を動かす最初の試作 | 比較の出発点 |
| `covershift_prototype_v2` | API と**ワーカー**を分ける。DBの `jobs` 表を1秒ごとに見る(ポーリング) | 比較用 |
| `covershift_prototype_V3_listen_notify` | PostgreSQL の `LISTEN/NOTIFY` で即時通知。**LangGraph・CP-SAT は実際には動かしていない** | 比較用 |
| `covershift_prototype_V4_celery_redis` | Celery + Redis のタスクキュー。状態はメモリ(`MemorySaver`) | 比較用 |
| `covershift_prototype_v5_notify` | V3 の通知方式に OR-Tools(CP-SAT)を載せた版 | 比較用 |
| `covershift_prototype_v6_langgraph` | V5 の仕事の取り方 + LangGraph + `PostgresSaver`。承認待ち(`interrupt`)は本物 | 比較用(「V6(仮)」) |
| `covershift_prototype_v6_min` | V6 の最小版(試験用の補強) | 試験用 |
| `covershift_prototype_v6_gen` | V6 + **世代番号**(古いワーカーの二重書き込みを止める)。`fencing.py` を追加 | 試験用 |
| `covershift_prototype_v6_gen_changed_only` | 上の変更3ファイルだけ(`fencing.py`・`worker.py`・`graphs/main_graph.py`) | 差分確認用 |
| `covershift_prototype_c_queue` | **C案(最小版)**。状態はDB、受け渡しは発信箱 → メッセージキュー(ElasticMQ)。LangGraph・CP-SAT・LINE はなし | 比較用 |

各版の詳しい説明・動かし方は、フォルダの中の `README.md` を見てください(`c_queue` には README がまだありません)。

### 実験・測定

| フォルダ / ファイル | 内容 |
|---|---|
| `harness/` | V2・V6 などの測定スクリプトと結果(E1〜E8)。ログは `harness/logs/` |
| `harness_c/` | C案(最小版)の測定(E1・E2・E3・E5・E6・E9) |
| `harness_v6real/` | V6 側の同じ試験(E1・E2・E3・E5・E6・E9) |
| `results_cv6/` | C案(最小版)と V6 を交互に測った結果。まとめは `summary.md` |
| `crash_lab/` | 計算の途中でワーカーを落とす実験(使い方は `README.txt`) |
| `sched_lab/` | スケジューラーを分けるか(別プロセス / ワーカーの中)を比べる実験 |
| `run_ab_e2.ps1` | V6 と v6_min を交互に E2 測定 |
| `run_c_vs_v6.ps1` | C案(最小版)と V6 を交互に測定 |
| `summarize_cv6.py` | `results_cv6/` の結果をまとめる |

### 試験の名前

| 記号 | 見ること |
|---|---|
| E1 | 何もしない60秒の、DBへの問い合わせ数 |
| E2 | 仕事を出してから始まるまでの遅れ |
| E3 | 処理中にワーカーを強制終了したときの復旧 |
| E4 | 同じ操作を同時に2回送ったとき |
| E5 | DB(やキュー)が止まったとき |
| E6 | ワーカーを2台にしたとき |
| E8 | 承認待ちのまま全部を再起動したとき |
| E9 | 計算の途中でDBだけが再起動したとき(二重に計算されないか) |

### その他

| フォルダ / ファイル | 内容 |
|---|---|
| `001-Concept/` | LangGraph の練習(グラフ・LLMパイプライン・`interrupt`) |
| `002-api_integration/` | LangGraph を FastAPI から使う練習 |
| `docker-compose.proto.yml` | 試作用のDB(PostgreSQL 16、ポート **5434**) |
| `docker-compose.proto_V4.yml` | V4 用(Redis など) |
| `docker-compose.proto_c.yml` | C案用(PostgreSQL + ElasticMQ。キューは 9324 / 画面は 9325) |
| `docker-compose.yml` | 最初に作った開発用コンテナ |
| `requirements.txt` | 必要なライブラリ |

## 動かし方(Windows / PowerShell)

試作を1つ動かす最短の手順です(例は v2。他の版もフォルダ名を替えるだけですが、版ごとの違いは各 `README.md` を見てください)。

```powershell
# 1. 試作用のDBを起動(ポート5434)
docker compose -f docker-compose.proto.yml up -d

# 2. ライブラリを入れる(venv の中で)
pip install -r requirements.txt

# 3. ターミナルを3つ開く(どれもこのフォルダで)
uvicorn covershift_prototype_v2.main:app --port 8001      # A: API(受付)
python -m covershift_prototype_v2.worker                  # B: ワーカー
$env:API_BASE="http://127.0.0.1:8001"                     # C: 動作確認
python -m covershift_prototype_v2.check_flow
```

- ワーカーを起動し忘れると、依頼が `QUEUED` のまま進みません。
- **版を切り替えるときは、DBを作り直してください**(`docker compose -f docker-compose.proto.yml down -v`)。版ごとに表の作りが違うためです。
- C案は `docker-compose.proto_c.yml` を使い、`python -m covershift_prototype_c_queue.flow`・`.relay`・`.solver` を別々のターミナルで起動します。

## 測定について(読む前に)

- 測定は、私の **Windows + Docker Desktop** で行いました。回数は少なく(E1・E2・E6は3回、E3・E5は1回など)、**数字は目安**です。
- 他のメンバーの環境(Mac + Docker)での測定とは、条件が違うので、**数字の大きさを比べないでください**。
- **C案(最小版)は、資料から作った簡易版**で、チームメンバー(スンヒョク)の `prototype_c` のコードではありません。計算は待つだけの模擬で、LangGraph・CP-SAT・LINE は入っていません。
- ソルバーはダミーのものが多く、**実際の1か月分の計算時間は未測定**です。
- **AWS での動作・費用は未確認**です(キューは ElasticMQ / moto の代用)。
- 公開してよい内容かを確認してから、ログ(`logs/`)や結果(`*.json`)を追加してください。

## このプロジェクトの全体像(参考)

対象は日本のシフト編成全般です。ドラッグストアでの経験を土台に、まず1店舗を想定した「時間帯 × 業務で本当に回るか」の確認から始めています。

本番に向けた構成として、Python(FastAPI)・PostgreSQL・Vue3・OR-Tools(CP-SAT)・LangGraph・Claude API・LINE・AWS を使う計画です。**このリポジトリには、そのうち LangGraph 周辺の試作しか入っていません**(画面・LINE・Claude API は含まれていません)。

## チーム

- イ・スンヒョク(リーダー)
- 池田 愛都稀(技術担当・このリポジトリの作成者)
- イ・ヒョクジュン(記録)
