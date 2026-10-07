# Pydantic スキーマ定義from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class ShiftCreateRequest(BaseModel):
    thread_id: str = Field(..., example="store001-2026-10")
    store_id: str = Field(default="store001")
    target_month: str = Field(default="2026-10")

class ShiftResumeRequest(BaseModel):
    approved: bool = Field(..., description="承認: true / 却下: false")
    comments: Optional[str] = Field(None, description="店長からのコメント")