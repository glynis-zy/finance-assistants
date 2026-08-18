"""预警中心服务（docs/api.md §5）。

- GET 列表：alert:view + 角色业务域过滤（admin 全量；finance/budget_manager 见 budget；
  finance/ar_specialist 见 ar）
- 标记已读：域内用户可标记（alert:view），admin 全量；幂等
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.alert import Alert
from app.models.rbac import SysUser


def visible_alert_types(user: SysUser) -> set[str] | None:
    """用户可见的预警域；admin 返回 None 表示全量。"""
    roles = {r.code for r in user.roles}
    if "admin" in roles:
        return None
    types: set[str] = set()
    if roles & {"finance", "budget_manager"}:
        types.add("budget")
    if roles & {"finance", "ar_specialist"}:
        types.add("ar")
    return types


def list_alerts(
    db: Session,
    user: SysUser,
    *,
    alert_type: str | None = None,
    level: str | None = None,
    read: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Alert], int]:
    """预警列表（分页 + 域过滤 + 可选类型/等级/已读过滤）。"""
    visible = visible_alert_types(user)
    stmt = select(Alert)
    if visible is not None:
        stmt = stmt.where(Alert.alert_type.in_(sorted(visible)))
    if alert_type is not None:
        stmt = stmt.where(Alert.alert_type == alert_type)
    if level is not None:
        stmt = stmt.where(Alert.level == level)
    if read is not None:
        stmt = stmt.where(Alert.read == read)
    count_stmt = select(Alert.id)
    if visible is not None:
        count_stmt = count_stmt.where(Alert.alert_type.in_(sorted(visible)))
    if alert_type is not None:
        count_stmt = count_stmt.where(Alert.alert_type == alert_type)
    if level is not None:
        count_stmt = count_stmt.where(Alert.level == level)
    if read is not None:
        count_stmt = count_stmt.where(Alert.read == read)
    total = len(db.scalars(count_stmt).all())
    items = list(
        db.scalars(
            stmt.order_by(Alert.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return items, total


def mark_read(db: Session, user: SysUser, alert_id: int) -> Alert:
    """标记已读（域内校验 + 幂等）。"""
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError("预警不存在")
    visible = visible_alert_types(user)
    if visible is not None and alert.alert_type not in visible:
        from app.core.exceptions import ForbiddenError

        raise ForbiddenError("无权操作该预警")
    alert.read = True
    db.commit()
    db.refresh(alert)
    return alert
