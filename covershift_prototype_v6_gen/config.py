import os

class Settings:
    # DB接続設定
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://covershift:covershift@localhost:5434/covershift_proto"
    )

    # API設定
    API_PORT: int = 8001

    # LLM設定
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")

    # 目的関数のデフォルト重み設定 (合計 1.0)
    DEFAULT_WEIGHTS: dict[str, float] = {
        "respect_wishes": 0.3,          # 希望維持
        "min_staffing": 0.3,            # 最小人員確保
        "prioritize_experienced": 0.2,  # 経験者優先
        "education_placement": 0.1,    # 教育配置
        "fairness": 0.1                 # 公平性
    }

settings = Settings()

# ---- V6: V2のLangGraph(main_graph.py / mock_solver.py)が使う設定 ----
MAX_REJECTS = int(os.getenv("MAX_REJECTS", "2"))   # 却下の上限回数
# ダミーのソルバーに、わざと待たせる秒数(重い計算の代わり)。試験用に EXP_SLEEP でも指定できる(二重には待たない)
MOCK_SOLVER_SLEEP = float(os.getenv("MOCK_SOLVER_SLEEP") or os.getenv("EXP_SLEEP") or "0")
