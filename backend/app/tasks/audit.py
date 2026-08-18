"""报销审核 Celery 任务（事件触发，非 beat）。"""

# celery task 装饰器无完整类型，第三方边界豁免
# pyright: reportUnknownMemberType=false, reportUntypedFunctionDecorator=false

from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.audit.run_audit")
def run_audit_task(reimbursement_id: int, task_id: int) -> None:
    """执行完整审核流水线。任务状态与结论全落 DB，失败可查 error。"""
    from app.db.session import SessionLocal
    from app.services.audit_flow_service import run_audit

    db = SessionLocal()
    try:
        run_audit(db, reimbursement_id, task_id)
    finally:
        db.close()
