from covershift_prototype_V4_celery_redis.cel_app import celery_app
from covershift_prototype_V4_celery_redis.graphs.main_graph import graph

@celery_app.task(name="tasks.process_shift_job", bind=True)
def process_shift_job(self, thread_id: str, payload: dict):
    """
    新規シフト作成 Celery タスク
    """
    print(f"🚀 [Celery Worker] タスク受領: Task ID={self.request.id}, Thread ID={thread_id}")
    
    initial_state = {
        "thread_id": thread_id,
        "store_id": payload.get("store_id", "store001"),
        "target_month": payload.get("target_month", "2026-10"),
        "approved": False,
        "status": "QUEUED"
    }
    
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(initial_state, config=config)
    
    # JSONシリアライズ可能な辞書だけを返す
    return {
        "status": "PAUSED_FOR_APPROVAL",
        "thread_id": thread_id,
        "shift_plan": result.get("shift_plan", {})
    }

@celery_app.task(name="tasks.resume_shift_job", bind=True)
def resume_shift_job(self, thread_id: str, approval_data: dict):
    """
    店長承認(HITL)再開 Celery タスク
    """
    print(f"🔄 [Celery Worker] 再開タスク受領: Thread ID={thread_id}")
    
    from langgraph.types import Command
    config = {"configurable": {"thread_id": thread_id}}
    
    result = graph.invoke(Command(resume=approval_data), config=config)
    
    return {
        "status": result.get("status", "COMPLETED"),
        "thread_id": thread_id,
        "approved": result.get("approved", False)
    }