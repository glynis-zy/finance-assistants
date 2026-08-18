"""基础数据接口（docs/api.md §6）：科目/部门/项目/客户/合同。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_perm
from app.core.perms import Permission
from app.db.session import get_db
from app.models.rbac import SysUser
from app.schemas.platform import (
    ContractOut,
    CostCategoryCreate,
    CostCategoryOut,
    CostCategoryUpdate,
    CustomerOut,
    DepartmentOut,
    ProjectOut,
)
from app.services import audit_service, base_data_service

router = APIRouter(tags=["基础数据"])


@router.get("/departments", response_model=list[DepartmentOut])
def departments(
    _: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DepartmentOut]:
    """部门列表（登录即可）。"""
    return [DepartmentOut.model_validate(d) for d in base_data_service.list_departments(db)]


@router.get("/projects", response_model=list[ProjectOut])
def projects(
    _: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    department_id: int | None = None,
) -> list[ProjectOut]:
    """项目列表（可按部门过滤）。"""
    return [
        ProjectOut.model_validate(p) for p in base_data_service.list_projects(db, department_id)
    ]


@router.get("/cost-categories", response_model=list[CostCategoryOut])
def cost_categories(
    _: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    enabled_only: bool = True,
    keyword: str | None = None,
) -> list[CostCategoryOut]:
    """科目列表（报销/预算下拉）。"""
    return [
        CostCategoryOut.model_validate(c)
        for c in base_data_service.list_cost_categories(
            db, enabled_only=enabled_only, keyword=keyword
        )
    ]


@router.post("/cost-categories", response_model=CostCategoryOut, status_code=201)
def create_cost_category(
    payload: CostCategoryCreate,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.COST_CATEGORY_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> CostCategoryOut:
    """新建科目（code 唯一）。"""
    category = base_data_service.create_cost_category(db, payload)
    audit_service.log_action(
        db,
        "cost_category.create",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="cost_category",
        object_id=str(category.id),
        after={"code": category.code, "name": category.name},
    )
    db.commit()
    db.refresh(category)
    return CostCategoryOut.model_validate(category)


@router.put("/cost-categories/{category_id}", response_model=CostCategoryOut)
def update_cost_category(
    category_id: int,
    payload: CostCategoryUpdate,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.COST_CATEGORY_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> CostCategoryOut:
    """更新科目（code 不可改）。"""
    category = base_data_service.update_cost_category(db, category_id, payload)
    audit_service.log_action(
        db,
        "cost_category.update",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="cost_category",
        object_id=str(category_id),
        after={"name": category.name, "enabled": category.enabled},
    )
    db.commit()
    db.refresh(category)
    return CostCategoryOut.model_validate(category)


@router.get("/customers", response_model=list[CustomerOut])
def customers(
    _: Annotated[SysUser, Depends(require_perm(Permission.AR_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    keyword: str | None = None,
) -> list[CustomerOut]:
    """客户列表（应收下拉）。"""
    return [CustomerOut.model_validate(c) for c in base_data_service.list_customers(db, keyword)]


@router.get("/contracts", response_model=list[ContractOut])
def contracts(
    _: Annotated[SysUser, Depends(require_perm(Permission.AR_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    customer_id: int | None = None,
) -> list[ContractOut]:
    """合同列表（可按客户过滤）。"""
    return [
        ContractOut.model_validate(c) for c in base_data_service.list_contracts(db, customer_id)
    ]
