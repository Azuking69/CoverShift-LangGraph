"""ワーカーの代わり: 重い計算を、ずっと繰り返す。  python -m sched_lab.busy_worker"""
from .heavy import heavy_solve

if __name__ == "__main__":
    while True:
        heavy_solve()
