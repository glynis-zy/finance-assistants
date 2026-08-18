"""系统管理接口（docs/api.md §6）：用户/角色。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_perm
from app.core.perms import Permission
from app.db.session import get_db
from app.models.rbac import SysUser
from app.schemas.platform import RoleOut, UserCreate, UserOut
from app.services import audit_service, base_data_service

router = APIRouter(tags=["系统管理"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: Annotated[SysUser, Depends(require_perm(Permission.USER_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
    role: str | None = None,
) -> list[UserOut]:
    """用户列表（可按角色过滤）。"""
    return [UserOut(**u) for u in base_data_service.list_users(db, role)]  # type: ignore[arg-type]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.USER_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    """新建用户（用户名唯一）。"""
    user = base_data_service.create_user(db, payload)
    audit_service.log_action(
        db,
        "user.create",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="sys_user",
        object_id=str(user.id),
        after={"username": user.username, "roles": payload.roles},
    )
    db.commit()
    return UserOut(
        id=user.id,
        username=user.username,
        name=user.name,
        roles=[r.code for r in user.roles],
        enabled=user.enabled,
    )


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    _: Annotated[SysUser, Depends(require_perm(Permission.ROLE_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> list[RoleOut]:
    """角色列表（含权限码）。"""
    return [RoleOut(**r) for r in base_data_service.list_roles(db)]  # type: ignore[arg-type]
