"""应收评分 Celery 任务。

- score_customer_task：单客户重算（回款/催收登记后触发）
- run_risk_task：全量评分（beat 每日 08:30），状态落 ar_risk_run

幂等：每客户每评分日 upsert；alert 以 unique_key 查重，重复执行不重复产生。
"""

# celery task 装饰器无完整类型，第三方边界豁免
# pyright: reportUnknownMemberType=false, reportUntypedFunctionDecorator=false, reportFunctionMemberAccess=false

from datetime import UTC, datetime

from app.tasks.celery_app import celery_app


def trigger_customer_rescore(customer_id: int) -> None:
    """登记回款/催收后触发单客户重算（幂等：同日 upsert）。"""
    score_customer_task.delay(customer_id)


@celery_app.task(name="app.tasks.ar.score_customer", bind=True)
def score_customer_task(self: object, customer_id: int) -> dict[str, object]:
    """重算单个客户当日风险分（幂等 upsert）。"""
    from app.db.session import SessionLocal
    from app.services import ar_service

    with SessionLocal() as db:
        result = ar_service.score_customer(db, customer_id)
        return {
            "customer_id": customer_id,
            "score": result.total_score,
            "risk_level": result.risk_level,
        }


@celery_app.task(name="app.tasks.ar.run_risk", bind=True)
def run_risk_task(self: object, score_date: str | None = None) -> dict[str, int]:
    """全量应收评分（beat 每日 08:30；状态落 ar_risk_run）。"""
    score_date = score_date or datetime.now(UTC).date().isoformat()
    from datetime import date

    from app.db.session import SessionLocal
    from app.services import ar_service

    with SessionLocal() as db:
        return ar_service.score_all(db, date.fromisoformat(score_date))
