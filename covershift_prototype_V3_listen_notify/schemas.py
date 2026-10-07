from pydantic import BaseModel

class StartShiftRequest(BaseModel):
    store_id: str
    period: str = "2026-10"

class ResumeShiftRequest(BaseModel):
    thread_id: str
    approved: bool