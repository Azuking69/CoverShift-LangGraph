# FastAPI APIサーバー (celery.send_task で投げる)
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from covershift_prototype_V4_celery_redis.tasks import process_shift_job, resume_shift_job

app = FastAPI(title="CoverShift Prototype V4 (Celery + Redis)")

class ShiftRequest(BaseModel):
    thread_id: str
    data: dict = {}

@app.post("/api/v1/shift", status_code=status.HTTP_202_ACCEPTED)
async def create_shift(req: ShiftRequest):
    # Redisキューへ非同期タスクを送信（即時復帰）
    task = process_shift_job.delay(req.thread_id, req.data)
    return {
        "message": "Shift generation job queued",
        "task_id": task.id,
        "thread_id": req.thread_id,
        "status": "QUEUED"
    }

@app.post("/api/v1/shift/{thread_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_shift(thread_id: str, payload: dict):
    task = resume_shift_job.delay(thread_id, payload)
    return {
        "message": "Resume job queued",
        "task_id": task.id,
        "thread_id": thread_id,
        "status": "RESUME_QUEUED"
    }