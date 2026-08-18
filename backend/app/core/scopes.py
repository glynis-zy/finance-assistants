"""L2 数据权限基础机制（责任链第二环）。

行级过滤：报销按申请人、应收/预警按业务域。service 查询层调用这些 helper 强制过滤，
非前端拼 SQL。越权抛 `ForbiddenScopeError`。
"""

from app.core.exceptions import ForbiddenScopeError
from app.core.perms import user_permissions
from app.models.rbac import SysUser


def ensure_owner(user: SysUser, owner_id: int) -> None:
    """资源仅本人可见（如报销单申请人本人）。"""
    if user.id != owner_id:
        raise ForbiddenScopeError()


def has_perm(user: SysUser, *required: str) -> bool:
    """用户是否拥有全部指定权限码（用于 L2 数据域判断）。"""
    return set(required).issubset(user_permissions(user))
