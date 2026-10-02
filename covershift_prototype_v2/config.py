"""
設定(環境変数で上書きできる)。
- DATABASE_URL: 試作専用のPostgreSQL。docker-compose.yml の db(ポート5434)に合わせてある。
- JOB_TIMEOUT_SEC: ワーカーが処理中に死んだ依頼を、何秒たったら「やり直し可」とみなすか。
- MOCK_SOLVER_SLEEP: モックのソルバーに、わざと待ちを入れる秒数(重い計算の代わり)。
"""
import os

# PostgreSQLの接続URL。docker-compose.yml の db(ポート5434)に合わせてある。
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://covershift:covershift@localhost:5434/covershift_proto",
)
WORKER_POLL_SEC = float(os.getenv("WORKER_POLL_SEC", "1"))
JOB_TIMEOUT_SEC = float(os.getenv("JOB_TIMEOUT_SEC", "30"))
JOB_MAX_ATTEMPTS = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
MOCK_SOLVER_SLEEP = float(os.getenv("MOCK_SOLVER_SLEEP", "0"))
MAX_REJECTS = int(os.getenv("MAX_REJECTS", "2"))
