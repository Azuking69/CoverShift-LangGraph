"""
役割: 外部(フロントエンドやブラウザ)とのやり取りを担当する「窓口(受付)」。
v2の変更: ここではグラフを動かさない。
  - start  : 編成を作り、依頼箱(jobs)に「開始」を書いて 202 を返す。
  - resume : 依頼箱に「再開」を書いて 202 を返す。
  - GET    : runs テーブルの状況を返す。
グラフを動かすのは別プロセスのワーカー(worker.py)。
起動: LangGraph フォルダ(covershift_prototype の親)で
    uvicorn covershift_prototype.main:app --port 8000
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from .db import create_run, get_run, init_schema, queue_resume
from .schemas import ResumeShiftRequest, StartShiftRequest


# asynccontextmanager: FastAPI の lifespan イベントで使うためのデコレーター
@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB のスキーマを初期化する
    init_schema()
    # yield で FastAPI の起動後の処理を待つ
    yield


# FastAPI アプリケーションの作成
app = FastAPI(title="CoverShift V6 Prototype API (v2: API/ワーカー分離)", lifespan=lifespan)


# ルートエンドポイント: API の稼働確認用
@app.get("/")
def read_root():
    return {"message": "CoverShift V6 API Ready"}


@app.post("/api/v1/shift/start", status_code=202)
def start_shift(req: StartShiftRequest):
    thread_id = f"{req.store_id}-{req.period}"

    # 編成を新しく作って「開始」の依頼を出す。同じthread_idが既にあれば False
    if not create_run(thread_id, req.store_id):
        raise HTTPException(status_code=409, detail=f"この編成はすでに存在します: {thread_id}")
    return {"status": "QUEUED", "thread_id": thread_id}


@app.post("/api/v1/shift/resume", status_code=202)
# resume_shift: 承認待ち(PAUSED_FOR_APPROVAL)のときだけ受け付ける。
def resume_shift(req: ResumeShiftRequest):
    result = queue_resume(req.thread_id, req.approved)

    if result == "not_found":
        raise HTTPException(status_code=404, detail="その編成は存在しません。")
    
    if result == "conflict":
        raise HTTPException(status_code=409, detail="停止中(承認待ち)ではないか、すでに再開の依頼が出ています。")

    # result が "queued" の場合は、再開の依頼が正常にキューに入ったので 202 を返す
    return {"status": "RESUME_QUEUED", "thread_id": req.thread_id}


@app.get("/api/v1/shift/{thread_id}")
# get_shift: thread_id で runs を1件取得する。なければ 404
def get_shift(thread_id: str):
    run = get_run(thread_id)

    if run is None:
        raise HTTPException(status_code=404, detail="その編成は存在しません。")
    
    return run
