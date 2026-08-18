"""预警中心接口（docs/api.md §5）。

域过滤：finance/budget_manager 见 budget 预警；finance/ar_specialist 见 ar 预警；
admin 全量；applicant 无 alert:view（403）。
标记已读权限为 alert:view + 域内（Stage 5 口径：域内用户可处理自己的预警）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_perm
from app.core.perms import Permission
from app.db.session import get_db
from app.models.rbac import SysUser
from app.schemas.common import PageResult
from app.schemas.platform import AlertOut, AlertReadOut
from app.services import alert_service

router = APIRouter(prefix="/alerts", tags=["预警"])


@router.get("", response_model=PageResult[AlertOut])
def list_alerts(
    current_user: Annotated[SysUser, Depends(require_perm(Permission.ALERT_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    alert_type: str | None = Query(default=None, pattern=r"^(budget|ar)$"),
    level: str | None = Query(default=None, pattern=r"^(info|warning|critical)$"),
    read: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResult[AlertOut]:
    """预警列表（业务域自动过滤）。"""
    items, total = alert_service.list_alerts(
        db,
        current_user,
        alert_type=alert_type,
        level=level,
        read=read,
        page=page,
        page_size=page_size,
    )
    return PageResult(
        total=total,
        page=page,
        page_size=page_size,
        items=[AlertOut.model_validate(a) for a in items],
    )


@router.post("/{alert_id}/read", response_model=AlertReadOut)
def mark_read(
    alert_id: int,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.ALERT_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
) -> AlertReadOut:
    """标记已读（幂等；域内校验）。"""
    alert = alert_service.mark_read(db, current_user, alert_id)
    return AlertReadOut(id=alert.id, read=alert.read)
