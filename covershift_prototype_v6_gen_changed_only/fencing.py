"""世代番号(フェンシング)の確認。V6補強3(v6_gen)。

仕事を取るたびに jobs.attempts が1ずつ増える。これを「世代番号」として使う。
ワーカーは自分が取ったときの世代番号を持ち、結果を書く前に「いまのjobs.attemptsと同じか」を確かめる。
違えば、別のワーカーに取り直された(自分の仕事ではなくなった)ので、何も書かずに引き下がる。

限界(正直に): ・確認から書き込みまでの間に取り直されると、すり抜ける可能性がある(確認と書き込みが同じ取引ではない)
              ・二重の「計算」そのものは防げない(防ぐには生存報告=ハートビートが要る)。防ぐのは二重の「書き込み」。
"""
import psycopg

from .config import settings


class StaleJob(Exception):
    """この仕事は、別のワーカーに取り直された(世代番号が古い)"""


def assert_current(config) -> None:
    c = (config or {}).get("configurable", {}) or {}
    job_id, mine = c.get("job_id"), c.get("attempt")
    if job_id is None or mine is None:
        return  # 世代番号が渡されていない(テストなど)ときは確認しない
    with psycopg.connect(settings.DATABASE_URL, connect_timeout=5) as conn:
        row = conn.execute("SELECT attempts FROM jobs WHERE id = %s", (job_id,)).fetchone()
    if row is None or row[0] != mine:
        raise StaleJob(f"job={job_id} 自分の世代={mine} / いまの世代={None if row is None else row[0]}")
