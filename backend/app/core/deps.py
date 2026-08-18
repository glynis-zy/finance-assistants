"""FastAPI 依赖注入：当前用户解析与 L1 权限校验（责任链第一环）。"""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.perms import user_permissions
from app.core.security import decode_token
from app.db.session import get_db
from app.models.rbac import SysUser

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> SysUser:
    """从 Bearer token 解析当前用户（含角色与权限，selectin 预载）。"""
    if credentials is None:
        raise UnauthorizedError()
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise UnauthorizedError() from None
    subject = payload.get("sub")
    if not subject:
        raise UnauthorizedError()
    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise UnauthorizedError() from None
    user = db.get(SysUser, user_id)
    if user is None or not user.enabled:
        raise UnauthorizedError()
    return user


def require_perm(*required: str) -> Callable[..., SysUser]:
    """L1 角色权限依赖工厂：要求当前用户拥有全部指定权限码。"""

    def checker(current_user: Annotated[SysUser, Depends(get_current_user)]) -> SysUser:
        if not set(required).issubset(user_permissions(current_user)):
            raise ForbiddenError()
        return current_user

    return checker
