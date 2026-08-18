"""认证接口（docs/api.md §1）。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.perms import user_permissions
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.rbac import SysUser
from app.schemas.auth import LoginRequest, LoginResponse, UserInfo
from app.services import audit_service, auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


def _user_info(user: SysUser) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        name=user.name,
        roles=[r.code for r in user.roles],
        permissions=sorted(user_permissions(user)),
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> LoginResponse:
    """用户名密码登录，返回 JWT 与用户信息。"""
    user = auth_service.authenticate(db, payload.username, payload.password)
    settings = get_settings()
    token = create_access_token(str(user.id))
    audit_service.log_action(db, "login", actor_id=user.id, actor_name=user.username)
    db.commit()
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
        user=_user_info(user),
    )


@router.get("/me", response_model=UserInfo)
def me(current_user: Annotated[SysUser, Depends(get_current_user)]) -> UserInfo:
    """返回当前用户信息。"""
    return _user_info(current_user)


@router.post("/logout", status_code=204)
def logout(
    current_user: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """登出（V1 仅前端丢弃 token，服务端记审计）。"""
    audit_service.log_action(
        db, "logout", actor_id=current_user.id, actor_name=current_user.username
    )
    db.commit()
