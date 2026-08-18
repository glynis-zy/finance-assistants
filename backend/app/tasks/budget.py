"""预算监控 Celery 任务（beat 每日 08:00 触发，事件触发亦可）。

任务内自行建 session 与事务；状态通过 budget_snapshot.status 迁移表达
（queued → running → done/failed），查询走 GET /api/monitor/status。
幂等：同一核算期重复执行 → 偏差/快照 upsert、预警 unique_key 查重，不无限累积。
"""

# celery task 装饰器无完整类型，第三方边界豁免
# pyright: reportUnknownMemberType=false, reportUntypedFunctionDecorator=false

from datetime import UTC, datetime

from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.budget.run_monitor", bind=True)
def run_monitor_task(self: object, period: str | None = None) -> dict[str, object]:
    """执行一次预算监控。period 缺省取当前核算月。"""
    period = period or datetime.now(UTC).strftime("%Y-%m")

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.budget_domain import BudgetSnapshot
    from app.services import monitor_service

    with SessionLocal() as db:
        snapshot = db.scalar(select(BudgetSnapshot).where(BudgetSnapshot.period == period))
        if snapshot is None:
            snapshot = BudgetSnapshot(period=period, status="running")
            db.add(snapshot)
            db.commit()
        else:
            snapshot.status = "running"
            snapshot.error = None
            db.commit()
        try:
            summary = monitor_service.run_monitor(db, period)
        except Exception as exc:  # 任务失败可查询 error（budget_snapshot.error）
            snapshot.status = "failed"
            snapshot.error = str(exc)[:500]
            db.commit()
            raise
        snapshot.status = "done"
        db.commit()
        return summary
