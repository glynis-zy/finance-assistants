"""预算管理接口（docs/api.md §3：GET/POST/PUT /api/budgets）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_perm
from app.core.perms import Permission
from app.db.session import get_db
from app.models.rbac import SysUser
from app.schemas.budget import (
    BudgetCreatedOut,
    BudgetCreateRequest,
    BudgetOut,
    BudgetUpdateRequest,
)
from app.schemas.common import PageResult
from app.services import audit_service, budget_service

router = APIRouter(prefix="/budgets", tags=["预算"])


@router.get("", response_model=PageResult[BudgetOut])
def list_budgets(
    _: Annotated[SysUser, Depends(require_perm(Permission.BUDGET_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    department_id: int | None = None,
    project_id: int | None = None,
    cost_category_id: int | None = None,
    year_from: str | None = Query(default=None, pattern=r"^\d{4}$"),
    year_to: str | None = Query(default=None, pattern=r"^\d{4}$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResult[BudgetOut]:
    """预算列表（年度过滤）。"""
    items, total = budget_service.list_budgets(
        db,
        department_id=department_id,
        project_id=project_id,
        cost_category_id=cost_category_id,
        year_from=year_from,
        year_to=year_to,
        page=page,
        page_size=page_size,
    )
    return PageResult(
        total=total,
        page=page,
        page_size=page_size,
        items=[BudgetOut.model_validate(b) for b in items],
    )


@router.post("", response_model=BudgetCreatedOut, status_code=201)
def create_budget(
    payload: BudgetCreateRequest,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.BUDGET_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> BudgetCreatedOut:
    """新建年度预算（同维度同年度重复 → 409 RESOURCE_CONFLICT）。"""
    budget = budget_service.create_budget(db, payload, current_user.username)
    audit_service.log_action(
        db,
        "budget.create",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="budget",
        object_id=str(budget.id),
        after={
            "department_id": budget.department_id,
            "project_id": budget.project_id,
            "cost_category_id": budget.cost_category_id,
            "budget_year": budget.budget_year,
            "amount": str(budget.amount),
        },
    )
    db.commit()
    db.refresh(budget)
    return BudgetCreatedOut(
        budget_id=budget.id,
        budget_year=budget.budget_year,
        amount=budget.amount,
    )


@router.put("/{budget_id}", response_model=BudgetCreatedOut)
def adjust_budget(
    budget_id: int,
    payload: BudgetUpdateRequest,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.BUDGET_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> BudgetCreatedOut:
    """调整预算（写 BudgetAdjustment 留痕 + audit_log）。"""
    budget, adjustment = budget_service.adjust_budget(db, budget_id, payload, current_user.username)
    audit_service.log_action(
        db,
        "budget.adjust",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="budget",
        object_id=str(budget.id),
        before={"amount": str(adjustment.before_amount) if adjustment.before_amount else None},
        after={"amount": str(adjustment.after_amount), "reason": payload.reason},
    )
    db.commit()
    db.refresh(budget)
    return BudgetCreatedOut(
        budget_id=budget.id,
        budget_year=budget.budget_year,
        amount=budget.amount,
        adjustment_id=adjustment.id,
    )
