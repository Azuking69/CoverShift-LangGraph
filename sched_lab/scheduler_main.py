"""A案: スケジューラーを別プロセスにする。  python -m sched_lab.scheduler_main <名前> <guard=1|0>"""
import sys

from .core import loop

if __name__ == "__main__":
    loop(sys.argv[1], sys.argv[2] == "1")
