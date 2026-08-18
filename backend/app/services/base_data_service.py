"""基础数据服务（docs/api.md §6）：科目/部门/项目/客户/合同/台账/用户/角色。

均为共享层直读 + 简单写操作；写操作带 audit_log（由路由层落库）。
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ResourceConflictError, ValidationError
from app.core.security import hash_password
from app.models.base_data import (
    Contract,
    CostCategory,
    Customer,
    ExpenseLedger,
    OrgDepartment,
    Project,
)
from app.models.rbac import SysRole, SysUser


def list_departments(db: Session) -> list[OrgDepartment]:
    """部门列表。"""
    return list(db.scalars(select(OrgDepartment).order_by(OrgDepartment.id)))


def list_projects(db: Session, department_id: int | None = None) -> list[Project]:
    """项目列表（可按部门过滤）。"""
    stmt = select(Project).order_by(Project.id)
    if department_id is not None:
        stmt = stmt.where(Project.department_id == department_id)
    return list(db.scalars(stmt))


def list_cost_categories(
    db: Session, *, enabled_only: bool = True, keyword: str | None = None
) -> list[CostCategory]:
    """科目列表。"""
    stmt = select(CostCategory).order_by(CostCategory.id)
    if enabled_only:
        stmt = stmt.where(CostCategory.enabled.is_(True))
    if keyword:
        stmt = stmt.where(CostCategory.name.contains(keyword) | CostCategory.code.contains(keyword))
    return list(db.scalars(stmt))


def create_cost_category(db: Session, payload: Any) -> CostCategory:
    """新建科目（code 唯一）。"""
    exists = db.scalar(select(CostCategory.id).where(CostCategory.code == payload.code))
    if exists is not None:
        raise ResourceConflictError("科目编码已存在")
    category = CostCategory(
        code=payload.code,
        name=payload.name,
        parent_id=payload.parent_id,
        enabled=payload.enabled,
        invoice_type_map=payload.invoice_type_map,
        keyword_map=payload.keyword_map,
    )
    db.add(category)
    db.flush()
    return category


def update_cost_category(db: Session, category_id: int, payload: Any) -> CostCategory:
    """更新科目（code 不可改；停用后新报销/新预算不可引用）。"""
    category = db.get(CostCategory, category_id)
    if category is None:
        raise NotFoundError("科目不存在")
    if payload.name is not None:
        category.name = payload.name
    if payload.parent_id is not None:
        category.parent_id = payload.parent_id
    if payload.enabled is not None:
        category.enabled = payload.enabled
    if payload.invoice_type_map is not None:
        category.invoice_type_map = payload.invoice_type_map
    if payload.keyword_map is not None:
        category.keyword_map = payload.keyword_map
    db.flush()
    return category


def list_customers(db: Session, keyword: str | None = None) -> list[Customer]:
    """客户列表。"""
    stmt = select(Customer).order_by(Customer.id)
    if keyword:
        stmt = stmt.where(Customer.name.contains(keyword) | Customer.code.contains(keyword))
    return list(db.scalars(stmt))


def list_contracts(db: Session, customer_id: int | None = None) -> list[Contract]:
    """合同列表（可按客户过滤）。"""
    stmt = select(Contract).order_by(Contract.id)
    if customer_id is not None:
        stmt = stmt.where(Contract.customer_id == customer_id)
    return list(db.scalars(stmt))


# ---------------------------------------------------------------- 台账


def list_ledger(
    db: Session,
    *,
    source: str | None = None,
    department_id: int | None = None,
    project_id: int | None = None,
    cost_category_id: int | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ExpenseLedger], int, dict[int, str], dict[int, str], dict[int, str]]:
    """台账分页查询（返回行 + 名称映射）。"""
    filters: list[Any] = []
    if source is not None:
        filters.append(ExpenseLedger.source == source)
    if department_id is not None:
        filters.append(ExpenseLedger.department_id == department_id)
    if project_id is not None:
        filters.append(ExpenseLedger.project_id == project_id)
    if cost_category_id is not None:
        filters.append(ExpenseLedger.cost_category_id == cost_category_id)
    if period_from is not None:
        filters.append(ExpenseLedger.period >= period_from)
    if period_to is not None:
        filters.append(ExpenseLedger.period <= period_to)

    count_q = select(ExpenseLedger.id)
    items_q = select(ExpenseLedger)
    for f in filters:
        count_q = count_q.where(f)  # type: ignore[arg-type]
        items_q = items_q.where(f)  # type: ignore[arg-type]
    total = len(db.scalars(count_q).all())
    rows = list(
        db.scalars(
            items_q.order_by(ExpenseLedger.period.desc(), ExpenseLedger.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    depts = {d.id: d.name for d in db.scalars(select(OrgDepartment)).all()}
    projs = {p.id: p.name for p in db.scalars(select(Project)).all()}
    cats = {c.id: c.name for c in db.scalars(select(CostCategory)).all()}
    return rows, total, depts, projs, cats


def import_ledger_csv(
    db: Session, content: str, actor_name: str
) -> tuple[int, list[dict[str, object]]]:
    """CSV 台账导入（列：cost_category_code/department_code/project_code/period 等）。

    幂等：ref_no 已存在则跳过；非法行记入 failed_rows 不中断。
    """
    import csv
    import io

    categories = {c.code: c.id for c in db.scalars(select(CostCategory)).all()}
    departments = {d.code: d.id for d in db.scalars(select(OrgDepartment)).all()}
    projects = {p.code: p.id for p in db.scalars(select(Project)).all()}

    reader = csv.DictReader(io.StringIO(content))
    expected = {
        "cost_category_code",
        "department_code",
        "project_code",
        "period",
        "amount",
        "occurred_at",
        "ref_no",
    }
    if reader.fieldnames is None or not expected.issubset(set(reader.fieldnames)):
        raise ValidationError(
            "CSV 列缺失，需包含 cost_category_code/department_code/project_code/"
            "period/amount/occurred_at/ref_no"
        )

    imported = 0
    failed: list[dict[str, object]] = []
    for idx, row in enumerate(reader, start=2):
        try:
            cat_id = categories.get(row["cost_category_code"])
            dept_id = departments.get(row["department_code"])
            proj_id = projects.get(row["project_code"])
            if cat_id is None or dept_id is None:
                failed.append({"row": idx, "reason": "科目/部门编码不存在"})
                continue
            amount = Decimal(row["amount"])
            if amount <= 0:
                raise ValueError
            occurred = datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00"))
            period = row["period"]
            exists = db.scalar(
                select(ExpenseLedger.id).where(ExpenseLedger.ref_no == row["ref_no"])
            )
            if exists is not None:
                continue  # 幂等跳过
            db.add(
                ExpenseLedger(
                    source="import",
                    cost_category_id=cat_id,
                    department_id=dept_id,
                    project_id=proj_id,
                    period=period,
                    amount=amount,
                    occurred_at=occurred,
                    ref_no=row["ref_no"] or None,
                )
            )
            imported += 1
        except (ValueError, KeyError):
            failed.append({"row": idx, "reason": "字段非法（金额/时间/必填列）"})
    return imported, failed


# ---------------------------------------------------------------- 用户/角色


def list_users(db: Session, role: str | None = None) -> list[dict[str, object]]:
    """用户列表（含角色名）。"""
    users = list(db.scalars(select(SysUser).order_by(SysUser.id)))
    out: list[dict[str, object]] = []
    for u in users:
        roles = [r.code for r in u.roles]
        if role is not None and role not in roles:
            continue
        out.append(
            {
                "id": u.id,
                "username": u.username,
                "name": u.name,
                "roles": roles,
                "enabled": u.enabled,
            }
        )
    return out


def create_user(db: Session, payload: Any) -> SysUser:
    """新建用户（用户名唯一 + 角色校验）。"""
    exists = db.scalar(select(SysUser.id).where(SysUser.username == payload.username))
    if exists is not None:
        raise ResourceConflictError("用户名已存在")
    role_objs: list[SysRole] = []
    for code in payload.roles:
        role = db.scalar(select(SysRole).where(SysRole.code == code))
        if role is None:
            raise ValidationError(f"角色不存在: {code}")
        role_objs.append(role)
    user = SysUser(
        username=payload.username,
        name=payload.name,
        password_hash=hash_password(payload.password),
    )
    user.roles.extend(role_objs)
    db.add(user)
    db.flush()
    return user


def list_roles(db: Session) -> list[dict[str, object]]:
    """角色列表（含权限码）。"""
    roles = list(db.scalars(select(SysRole).order_by(SysRole.id)))
    return [
        {"code": r.code, "name": r.name, "permissions": [p.code for p in r.permissions]}
        for r in roles
    ]
