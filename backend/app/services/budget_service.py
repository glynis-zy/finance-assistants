"""预算管理服务（docs/api.md §3）。

- POST：同年度同维度重复 → RESOURCE_CONFLICT（应走 PUT 调整）
- PUT：写 BudgetAdjustment 留痕 + audit_log（由调用方事务提交）
- allocation_curve 校验：长度 12 / 每项 >= 0 / 合计 = 1（±0.0001）
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ResourceConflictError
from app.models.base_data import (
    Budget,
    BudgetAdjustment,
    CostCategory,
    OrgDepartment,
    Project,
)
from app.schemas.budget import (
    BudgetCreateRequest,
    BudgetUpdateRequest,
    validate_allocation_curve,
)


def _ensure_refs(db: Session, department_id: int, project_id: int, cost_category_id: int) -> None:
    if db.get(OrgDepartment, department_id) is None:
        raise NotFoundError("部门不存在")
    if db.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")
    if db.get(CostCategory, cost_category_id) is None:
        raise NotFoundError("科目不存在")


def create_budget(
    db: Session,
    payload: BudgetCreateRequest,
    actor_name: str,
) -> Budget:
    """新建年度预算（同维度同年度已存在 → 409）。"""
    validate_allocation_curve(payload.allocation_curve)
    _ensure_refs(db, payload.department_id, payload.project_id, payload.cost_category_id)
    exists = db.scalar(
        select(Budget.id).where(
            Budget.department_id == payload.department_id,
            Budget.project_id == payload.project_id,
            Budget.cost_category_id == payload.cost_category_id,
            Budget.budget_year == payload.budget_year,
        )
    )
    if exists is not None:
        raise ResourceConflictError("同部门×项目×科目×年度预算已存在，应走 PUT 调整")
    budget = Budget(
        department_id=payload.department_id,
        project_id=payload.project_id,
        cost_category_id=payload.cost_category_id,
        budget_year=payload.budget_year,
        amount=payload.amount,
        allocation_curve=[float(x) for x in payload.allocation_curve],
    )
    db.add(budget)
    db.flush()
    return budget


def adjust_budget(
    db: Session,
    budget_id: int,
    payload: BudgetUpdateRequest,
    actor_name: str,
) -> tuple[Budget, BudgetAdjustment]:
    """调整预算并留痕（amount/allocation_curve 可选，至少一项）。"""
    budget = db.get(Budget, budget_id)
    if budget is None:
        raise NotFoundError("预算不存在")
    if payload.amount is None and payload.allocation_curve is None:
        raise ResourceConflictError("至少提供 amount 或 allocation_curve 之一")
    if payload.allocation_curve is not None:
        validate_allocation_curve(payload.allocation_curve)

    adjustment = BudgetAdjustment(
        budget_id=budget.id,
        before_amount=budget.amount,
        after_amount=payload.amount if payload.amount is not None else budget.amount,
        allocation_curve=(
            [float(x) for x in payload.allocation_curve]
            if payload.allocation_curve is not None
            else None
        ),
        reason=payload.reason,
        adjusted_by=actor_name,
    )
    db.add(adjustment)
    if payload.amount is not None:
        budget.amount = payload.amount
    if payload.allocation_curve is not None:
        budget.allocation_curve = [float(x) for x in payload.allocation_curve]
    db.flush()
    return budget, adjustment


def list_budgets(
    db: Session,
    *,
    department_id: int | None = None,
    project_id: int | None = None,
    cost_category_id: int | None = None,
    year_from: str | None = None,
    year_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Budget], int]:
    """预算列表（分页）。"""
    filters: list[object] = []
    if department_id is not None:
        filters.append(Budget.department_id == department_id)
    if project_id is not None:
        filters.append(Budget.project_id == project_id)
    if cost_category_id is not None:
        filters.append(Budget.cost_category_id == cost_category_id)
    if year_from is not None:
        filters.append(Budget.budget_year >= year_from)
    if year_to is not None:
        filters.append(Budget.budget_year <= year_to)

    count_query = select(Budget.id)
    items_query = select(Budget)
    for f in filters:
        count_query = count_query.where(f)  # type: ignore[arg-type]
        items_query = items_query.where(f)  # type: ignore[arg-type]
    total = len(db.scalars(count_query).all())
    items = list(
        db.scalars(
            items_query.order_by(Budget.budget_year.desc(), Budget.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total
