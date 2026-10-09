"""B案: スケジューラーを、ワーカーの中(同じプロセスの別スレッド)に入れる。
ワーカーの代わりに、重い計算を繰り返す。  python -m sched_lab.embedded <名前> <guard=1|0>"""
import sys
import threading

from .core import loop
from .heavy import heavy_solve

if __name__ == "__main__":
    t = threading.Thread(target=loop, args=(sys.argv[1], sys.argv[2] == "1"), daemon=True)
    t.start()
    while True:
        heavy_solve()
