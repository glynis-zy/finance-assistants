"""Celery 应用与 beat 调度配置。

Redis 仅作 broker，任务状态与结论全落 DB（docs/DESIGN.md 原则 1.7）。
beat 调度：预算监控每日 08:00（默认，调度节奏可由 sys_param
`schedule.budget_monitor` 配置，V1 以默认 crontab 生效）；
应收预警任务在应收阶段（Stage 4+）填充。
"""

# celery 无 py.typed，第三方无类型边界豁免（dev-standards 允许适配层边界放宽）
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "finance_assistants",
    broker=_settings.celery_broker,
    backend=_settings.celery_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    include=["app.tasks.audit", "app.tasks.budget", "app.tasks.ar"],
    beat_schedule={
        "budget-monitor": {
            "task": "app.tasks.budget.run_monitor",
            "schedule": crontab(hour=8, minute=0),  # 每日 08:00（UTC 或本地由 timezone 决定）
        },
        "ar-risk-warning": {
            "task": "app.tasks.ar.run_risk",
            "schedule": crontab(hour=8, minute=30),  # 每日 08:30 全量应收评分
        },
    },
)
