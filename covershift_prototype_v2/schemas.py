"""
データの形式・型チェック（ルール）
1. 画面(フロントエンド)からデータが届く
2. schemas.py がチェックする
3. LangGraph / ソルバーが処理する(= ワーカーの仕事)
4. DB(PostgreSQL)に保存する
※ pyc から復元した版。元のschemas.pyと見比べて、違うところがあれば元に合わせてください。
"""
from typing import TypedDict, Optional, Dict, Any
from pydantic import BaseModel


class CoverShiftState(TypedDict):
    store_id: str
    status: str
    draft_shift: Optional[Any]
    llm_explanation: Optional[str]
    manager_approved: Optional[bool]
    raw_input_names: Dict[str, str]
    retry_count: int


class StartShiftRequest(BaseModel):
    store_id: str
    # v2で追加: 同じ店で期間ごとに別の編成を持てるようにする(thread_id = store_id-period)
    period: str = "2026-10"


class ResumeShiftRequest(BaseModel):
    thread_id: str
    approved: bool
