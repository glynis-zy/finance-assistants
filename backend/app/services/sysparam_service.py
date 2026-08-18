"""系统参数服务。

权限收口（v1.0 冻结）：`threshold.*` 键允许 `threshold:manage` 或 `sys:manage` 修改，
其余键仅 `sys:manage`（docs/api.md §0.4）。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.perms import user_permissions
from app.models.base_data import SysParam
from app.models.rbac import SysUser

THRESHOLD_PREFIX = "threshold."


def _can_modify(user: SysUser, key: str) -> bool:
    perms = user_permissions(user)
    if key.startswith(THRESHOLD_PREFIX):
        return "threshold:manage" in perms or "sys:manage" in perms
    return "sys:manage" in perms


def list_params(db: Session, key: str | None = None) -> list[SysParam]:
    """按 key 精确查询（可选）参数列表。"""
    stmt = select(SysParam).order_by(SysParam.key)
    if key is not None:
        stmt = stmt.where(SysParam.key == key)
    return list(db.scalars(stmt))


def update_param(db: Session, user: SysUser, key: str, value: str) -> SysParam:
    """更新参数值（阈值键权限规则 + 审计由路由层落库）。"""
    if not _can_modify(user, key):
        raise ForbiddenError()
    param = db.scalar(select(SysParam).where(SysParam.key == key))
    if param is None:
        raise NotFoundError("参数不存在")
    param.value = value
    param.updated_by = user.username
    return param
