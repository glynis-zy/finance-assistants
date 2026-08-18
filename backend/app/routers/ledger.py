"""支出台账接口（docs/api.md §6）：查询 + CSV 导入。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import require_perm
from app.core.perms import Permission
from app.db.session import get_db
from app.models.rbac import SysUser
from app.schemas.common import PageResult
from app.schemas.platform import LedgerImportResult, LedgerOut
from app.services import audit_service, base_data_service

router = APIRouter(prefix="/ledger", tags=["台账"])


@router.get("", response_model=PageResult[LedgerOut])
def list_ledger(
    _: Annotated[SysUser, Depends(require_perm(Permission.LEDGER_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    source: str | None = Query(default=None, pattern=r"^(reimb|import)$"),
    department_id: int | None = None,
    project_id: int | None = None,
    cost_category_id: int | None = None,
    period_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    period_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResult[LedgerOut]:
    """台账查询（台账为单一权威来源，财务 ledger:view）。"""
    rows, total, depts, projs, cats = base_data_service.list_ledger(
        db,
        source=source,
        department_id=department_id,
        project_id=project_id,
        cost_category_id=cost_category_id,
        period_from=period_from,
        period_to=period_to,
        page=page,
        page_size=page_size,
    )
    items = [
        LedgerOut(
            id=e.id,
            source=e.source,
            cost_category_id=e.cost_category_id,
            cost_category_name=cats.get(e.cost_category_id, str(e.cost_category_id)),
            department_id=e.department_id,
            department_name=depts.get(e.department_id, str(e.department_id)),
            project_id=e.project_id,
            project_name=projs.get(e.project_id) if e.project_id else None,
            period=e.period,
            amount=e.amount,
            occurred_at=e.occurred_at,
            ref_no=e.ref_no,
        )
        for e in rows
    ]
    return PageResult(total=total, page=page, page_size=page_size, items=items)


@router.post("/import", response_model=LedgerImportResult, status_code=201)
def import_ledger(
    current_user: Annotated[SysUser, Depends(require_perm(Permission.LEDGER_IMPORT.value))],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> LedgerImportResult:
    """CSV 台账导入（模拟采购/工资等支出源；ref_no 幂等跳过）。"""
    content = file.file.read().decode("utf-8-sig")
    imported, failed = base_data_service.import_ledger_csv(db, content, current_user.username)
    audit_service.log_action(
        db,
        "ledger.import",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="expense_ledger",
        after={"imported_count": imported, "failed_count": len(failed)},
    )
    db.commit()
    return LedgerImportResult(imported_count=imported, failed_rows=failed)
