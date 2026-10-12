"""C案(最小版)の設定。V6と同じ環境変数名を、できるだけそのまま使う。"""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://covershift:covershift@localhost:5434/covershift_proto")

# メッセージキュー(SQS方式)。試験ではElasticMQ(SQS互換の代用品)をdockerで動かす。
SQS_ENDPOINT = os.getenv("SQS_ENDPOINT", "http://localhost:9324")

# ダミーのソルバーを、わざと待たせる秒数(V6と同じ。重い計算の代わり)
MOCK_SOLVER_SLEEP = float(os.getenv("MOCK_SOLVER_SLEEP") or os.getenv("EXP_SLEEP") or "0")

# メッセージを受け取ってから、処理が終わらないとき「死んだ」とみなして別の人に渡し直すまでの秒数。
# V6の JOB_TIMEOUT_SEC(期限切れ回収)に当たる。同じ環境変数名でも指定できる。
VISIBILITY_TIMEOUT_SEC = int(float(os.getenv("VISIBILITY_TIMEOUT_SEC") or os.getenv("JOB_TIMEOUT_SEC") or "10"))

# 何回受け取っても失敗したメッセージを、隔離キュー(DLQ)へ移す回数
MAX_RECEIVE = int(os.getenv("MAX_RECEIVE", "3"))

# 送信箱を、通知が来なくても確認する間隔(保険)。V6の WORKER_FALLBACK_SEC(10秒)とは別。C案の資料は5秒。
RELAY_POLL_SEC = float(os.getenv("RELAY_POLL_SEC", "5"))

# キューを待つ秒数(ロングポーリング)。DBには何もしない。
QUEUE_WAIT_SEC = int(os.getenv("QUEUE_WAIT_SEC", "5"))
