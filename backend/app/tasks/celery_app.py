"""Celery 应用与 beat 调度配置。

Redis 仅作 broker，任务状态与结论全落 DB（docs/DESIGN.md 原则 1.7）。
Stage 1 仅建基础设施；预算/应收日调度任务在 Stage 2 填充 beat_schedule。
"""

# celery 无 py.typed，第三方无类型边界豁免（dev-standards 允许适配层边界放宽）
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from celery import Celery

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
    # Stage 1 占位；Stage 2 填充：
    # "budget-monitor": {"task": "app.tasks.budget.run_monitor", "schedule": crontab(...)},
    # "ar-warning": {"task": "app.tasks.ar.run_warning", "schedule": crontab(...)},
    beat_schedule={},
)
