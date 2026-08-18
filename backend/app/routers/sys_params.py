"""系统参数接口（docs/api.md §6）。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_perm
from app.core.perms import Permission
from app.db.session import get_db
from app.models.rbac import SysUser
from app.schemas.sys_param import SysParamOut, SysParamUpdateRequest
from app.services import audit_service, sysparam_service

router = APIRouter(prefix="/sys-params", tags=["系统参数"])


@router.get("", response_model=list[SysParamOut])
def list_params(
    _: Annotated[SysUser, Depends(require_perm(Permission.SYS_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
    key: str | None = None,
) -> list[SysParamOut]:
    """参数列表（仅 sys:manage，管理功能）。"""
    return [SysParamOut.model_validate(p) for p in sysparam_service.list_params(db, key)]


@router.put("/{key}", response_model=SysParamOut)
def update_param(
    key: str,
    payload: SysParamUpdateRequest,
    current_user: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SysParamOut:
    """更新参数（阈值键权限规则在 service 内判定，变更必审）。"""
    param = sysparam_service.update_param(db, current_user, key, payload.value)
    audit_service.log_action(
        db,
        "sys_param.update",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="sys_param",
        object_id=key,
        after={"value": payload.value},
    )
    db.commit()
    db.refresh(param)
    return SysParamOut.model_validate(param)
