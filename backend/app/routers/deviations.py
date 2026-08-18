"""预算偏差查询接口（docs/api.md §3：deviations / summary / monitor/status）。"""

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_perm
from app.core.perms import Permission
from app.db.session import get_db
from app.domain.deviation_engine.engine import DEFAULT_THRESHOLDS, level_for_ratio
from app.models.base_data import CostCategory, OrgDepartment, Project, SysParam
from app.models.budget_domain import BudgetDeviation
from app.models.rbac import SysUser
from app.schemas.budget import DeviationGroupOut, DeviationOut, MonitorStatusOut
from app.schemas.common import PageResult
from app.services import monitor_service

router = APIRouter(tags=["预算偏差"])


def _names(db: Session) -> tuple[dict[int, str], dict[int, str], dict[int, str]]:
    depts = {d.id: d.name for d in db.scalars(select(OrgDepartment)).all()}
    projs = {p.id: p.name for p in db.scalars(select(Project)).all()}
    cats = {c.id: c.name for c in db.scalars(select(CostCategory)).all()}
    return depts, projs, cats


@router.get("/deviations", response_model=PageResult[DeviationOut])
def list_deviations(
    _: Annotated[SysUser, Depends(require_perm(Permission.BUDGET_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    department_id: int | None = None,
    project_id: int | None = None,
    cost_category_id: int | None = None,
    level: str | None = Query(default=None, pattern=r"^(low|medium|high)$"),
    period_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    period_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResult[DeviationOut]:
    """偏差明细（维度/等级/期间过滤，budget:view）。"""
    depts, projs, cats = _names(db)
    filters: list[Any] = []
    if department_id is not None:
        filters.append(BudgetDeviation.department_id == department_id)
    if project_id is not None:
        filters.append(BudgetDeviation.project_id == project_id)
    if cost_category_id is not None:
        filters.append(BudgetDeviation.cost_category_id == cost_category_id)
    if level is not None:
        filters.append(BudgetDeviation.level == level)
    if period_from is not None:
        filters.append(BudgetDeviation.period >= period_from)
    if period_to is not None:
        filters.append(BudgetDeviation.period <= period_to)

    count_q = select(BudgetDeviation.id)
    items_q = select(BudgetDeviation)
    for f in filters:
        count_q = count_q.where(f)  # type: ignore[arg-type]
        items_q = items_q.where(f)  # type: ignore[arg-type]
    total = len(db.scalars(count_q).all())
    rows = db.scalars(
        items_q.order_by(BudgetDeviation.period.desc(), BudgetDeviation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        DeviationOut(
            id=d.id,
            department_id=d.department_id,
            department_name=depts.get(d.department_id, str(d.department_id)),
            project_id=d.project_id,
            project_name=projs.get(d.project_id, str(d.project_id)),
            cost_category_id=d.cost_category_id,
            cost_category_name=cats.get(d.cost_category_id, str(d.cost_category_id)),
            period=d.period,
            budget_amount=d.budget_amount,
            actual_amount=d.actual_amount,
            deviation_amount=d.deviation_amount,
            deviation_ratio=d.deviation_ratio,
            level=d.level,
            owner=d.owner,
            trigger_reason=d.trigger_reason,
        )
        for d in rows
    ]
    return PageResult(total=total, page=page, page_size=page_size, items=items)


@router.get("/deviations/summary", response_model=list[DeviationGroupOut])
def deviations_summary(
    _: Annotated[SysUser, Depends(require_perm(Permission.BUDGET_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    group_by: str = Query(pattern=r"^(department|project|cost_category)$"),
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    level: str | None = Query(default=None, pattern=r"^(low|medium|high)$"),
) -> list[DeviationGroupOut]:
    """偏差汇总（查询层 group_by 聚合）。"""
    dim_col = {
        "department": BudgetDeviation.department_id,
        "project": BudgetDeviation.project_id,
        "cost_category": BudgetDeviation.cost_category_id,
    }[group_by]
    stmt = select(
        dim_col,
        func.sum(BudgetDeviation.budget_amount),
        func.sum(BudgetDeviation.actual_amount),
        func.sum(BudgetDeviation.deviation_amount),
    )
    if period is not None:
        stmt = stmt.where(BudgetDeviation.period == period)
    if level is not None:
        stmt = stmt.where(BudgetDeviation.level == level)
    stmt = stmt.group_by(dim_col)

    depts, projs, cats = _names(db)
    names = {"department": depts, "project": projs, "cost_category": cats}[group_by]

    # 聚合判级阈值从 sys_param 读（缺失用默认）
    low = DEFAULT_THRESHOLDS["threshold.budget.level_low"]
    high = DEFAULT_THRESHOLDS["threshold.budget.level_high"]
    for key, attr in (
        ("threshold.budget.level_low", "low"),
        ("threshold.budget.level_high", "high"),
    ):
        p = db.scalar(select(SysParam).where(SysParam.key == key))
        if p is not None:
            try:
                if attr == "low":
                    low = float(p.value)
                else:
                    high = float(p.value)
            except ValueError:
                pass

    out: list[DeviationGroupOut] = []
    for row in db.execute(stmt).all():
        key, budget_total, actual_total, deviation_amount = row
        key_int = int(key)
        ratio = deviation_amount / budget_total if budget_total > 0 else Decimal(0)
        out.append(
            DeviationGroupOut(
                key=key_int,
                name=names.get(key_int, str(key_int)),
                budget_total=budget_total,
                actual_total=actual_total,
                deviation_amount=deviation_amount,
                deviation_ratio=ratio.quantize(Decimal("0.0001")),
                level=level_for_ratio(ratio, low, high),
            )
        )
    out.sort(key=lambda x: x.key)
    return out


@router.get("/monitor/status", response_model=MonitorStatusOut)
def monitor_status(
    _: Annotated[SysUser, Depends(require_perm(Permission.BUDGET_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
) -> MonitorStatusOut:
    """最近一次监控任务状态/快照。"""
    info = monitor_service.latest_status(db)
    if info is None:
        return MonitorStatusOut(last_run_at=None, status="never_run", snapshot=None)
    return MonitorStatusOut(
        last_run_at=info["last_run_at"],  # type: ignore[arg-type]
        status=str(info["status"]),
        snapshot=info["snapshot"],  # type: ignore[arg-type]
    )
