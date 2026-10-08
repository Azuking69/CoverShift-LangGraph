from fastapi import FastAPI, HTTPException
from covershift_prototype_v5_notify.schemas import StartShiftRequest, ResumeShiftRequest
from covershift_prototype_v5_notify import db

app = FastAPI(title="CoverShift Prototype v5 (LISTEN/NOTIFY)")

@app.on_event("startup")
def startup():
    db.init_schema()

@app.get("/")
def read_root():
    return {"message": "CoverShift v5 API Ready"}

@app.post("/api/v1/shift/start", status_code=202)
def start_shift(req: StartShiftRequest):
    thread_id = db.create_run(req.store_id, req.period)
    if not thread_id:
        # 重複（None）時は 409 Conflict を返却
        raise HTTPException(status_code=409, detail="指定された期間のシフト編成は既に存在します。")
    return {"status": "QUEUED", "thread_id": thread_id}

@app.post("/api/v1/shift/resume", status_code=202)
def resume_shift(req: ResumeShiftRequest):
    run = db.get_run(req.thread_id)
    if not run:
        raise HTTPException(status_code=404, detail="指定された thread_id が見つかりません。")

    success = db.queue_resume(req.thread_id, req.approved)
    if not success:
        raise HTTPException(status_code=409, detail="承認待ち状態でないか、既に再開リクエストが送信されています。")
    return {"status": "RESUME_QUEUED", "thread_id": req.thread_id}

@app.get("/api/v1/shift/{thread_id}")
def get_shift_status(thread_id: str):
    run = db.get_run(thread_id)
    if not run:
        raise HTTPException(status_code=404, detail="指定された thread_id が見つかりません。")
    return run