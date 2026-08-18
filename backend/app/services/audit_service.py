"""审计日志服务。

`log_action` 仅 `db.add`，由调用方在业务事务内 `commit`，保证审计与业务同事务。
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.base_data import AuditLog


def log_action(
    db: Session,
    action: str,
    actor_id: int | None = None,
    actor_name: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    before: Any = None,
    after: Any = None,
) -> AuditLog:
    """写入一条审计日志（不提交）。"""
    entry = AuditLog(
        actor_id=actor_id,
        actor_name=actor_name,
        action=action,
        object_type=object_type,
        object_id=object_id,
        before=before,
        after=after,
    )
    db.add(entry)
    return entry
