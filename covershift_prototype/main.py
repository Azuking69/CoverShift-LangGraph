# covershift_prototype/main.py
"""
役割: 外部(フロントエンドやWebブラウザ)とのやり取りを担当する「窓口」
やること: HTTPリクエスト(POST /api/v1/shift/start 等）を受け取り、
         リクエストデータのバリデーション(schemas.py によるチェック）を行い、
         結果を JSON 形式で画面に返すことだけに集中
"""
from fastapi import FastAPI, HTTPException
from langgraph.types import Command
from covershift_prototype.schemas import StartShiftRequest, ResumeShiftRequest
from covershift_prototype.graphs.main_graph import covershift_graph

app = FastAPI(title="CoverShift V6 Prototype API")

@app.get("/")
def read_root():
    return {"message": "CoverShift V6 API Ready"}

@app.post("/api/v1/shift/start")
def start_shift(req: StartShiftRequest):
    thread_id = f"{req.store_id}-session"
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "store_id": req.store_id,
        "status": "S0_開始",
        "draft_shift": "",
        "llm_explanation": None,
        "manager_approved": None,
        "raw_input_names": {},
        "retry_count": 0
    }
    
    # 実行 (manager_review の interrupt で一時停止)
    current_state = covershift_graph.invoke(initial_state, config)
    state_snapshot = covershift_graph.get_state(config)
    
    return {
        "status": "PAUSED_FOR_APPROVAL",
        "thread_id": thread_id,
        "current_status": current_state.get("status"),
        "draft_shift": current_state.get("draft_shift"),
        "llm_explanation": current_state.get("llm_explanation"),
        "interrupt_info": state_snapshot.tasks[0].interrupts[0].value if state_snapshot.tasks else None
    }

@app.post("/api/v1/shift/resume")
def resume_shift(req: ResumeShiftRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    
    state_snapshot = covershift_graph.get_state(config)
    if not state_snapshot.next:
        raise HTTPException(status_code=400, detail="停止中のプロセスが存在しないか、すでに完了しています。")
        
    final_state = covershift_graph.invoke(Command(resume=req.approved), config)
    
    return {
        "status": "COMPLETED" if final_state.get("manager_approved") else "RETRY_SOLVER",
        "thread_id": req.thread_id,
        "final_status": final_state.get("status"),
        "manager_approved": final_state.get("manager_approved")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)