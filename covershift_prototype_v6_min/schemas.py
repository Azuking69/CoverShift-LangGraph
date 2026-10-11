from typing import Any, Dict, Optional, TypedDict

from pydantic import BaseModel

class StartShiftRequest(BaseModel):
    store_id: str
    period: str = "2026-10"

class ResumeShiftRequest(BaseModel):
    thread_id: str
    approved: bool


class CoverShiftState(TypedDict):
    """LangGraph(main_graph.py)の状態。V2と同じ。"""
    store_id: str
    status: str
    draft_shift: Optional[Any]
    llm_explanation: Optional[str]
    manager_approved: Optional[bool]
    raw_input_names: Dict[str, str]
    retry_count: int
