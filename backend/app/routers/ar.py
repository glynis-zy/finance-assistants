"""应收接口（docs/api.md §4）。"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_perm
from app.core.exceptions import NotFoundError
from app.core.perms import Permission
from app.db.session import get_db
from app.models.base_data import Customer
from app.models.rbac import SysUser
from app.schemas.ar import (
    CollectionRecordCreateRequest,
    CreatedOut,
    CustomerDetailOut,
    PaymentCreateRequest,
    ReceivableCreateRequest,
    ReceivableOut,
    RiskRankingItemOut,
    RiskStatusOut,
)
from app.schemas.common import PageResult
from app.services import ar_service, audit_service

router = APIRouter(prefix="/ar", tags=["应收"])


def _trigger_rescore(customer_id: int) -> None:
    """登记回款/催收后异步重算该客户（幂等：同日 upsert）。"""
    from app.tasks.ar import trigger_customer_rescore

    trigger_customer_rescore(customer_id)


@router.get("/receivables", response_model=PageResult[ReceivableOut])
def list_receivables(
    _: Annotated[SysUser, Depends(require_perm(Permission.AR_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    customer_id: int | None = None,
    status: str | None = Query(default=None, pattern=r"^(open|partial|settled)$"),
    due_before: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResult[ReceivableOut]:
    """应收列表（status 由服务端维护；overdue_days 动态计算）。"""
    rows, total, customers, contracts = ar_service.list_receivables(
        db,
        customer_id=customer_id,
        status=status,
        due_before=due_before,
        page=page,
        page_size=page_size,
    )
    today = datetime.now(UTC).date()
    items: list[ReceivableOut] = []
    for r in rows:
        paid = ar_service.paid_total(db, r.id)
        items.append(
            ReceivableOut(
                receivable_id=r.id,
                customer_id=r.customer_id,
                customer_name=customers.get(r.customer_id, str(r.customer_id)),
                contract_no=contracts.get(r.contract_id, None) if r.contract_id else None,
                amount=r.amount,
                due_date=r.due_date,
                overdue_days=max(0, (today - r.due_date).days),
                status=r.status,
                outstanding_balance=r.amount - paid,
            )
        )
    return PageResult(total=total, page=page, page_size=page_size, items=items)


@router.post("/receivables", response_model=CreatedOut, status_code=201)
def create_receivable(
    payload: ReceivableCreateRequest,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.AR_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> CreatedOut:
    """登记应收（status 默认 open；合同必须属于客户）。"""
    receivable = ar_service.create_receivable(db, payload)
    audit_service.log_action(
        db,
        "ar.receivable.create",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="ar_receivable",
        object_id=str(receivable.id),
        after={"customer_id": receivable.customer_id, "amount": str(receivable.amount)},
    )
    db.commit()
    db.refresh(receivable)
    return CreatedOut(
        id=receivable.id, extra={"customer_id": receivable.customer_id, "status": receivable.status}
    )


@router.post("/payments", response_model=CreatedOut, status_code=201)
def create_payment(
    payload: PaymentCreateRequest,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.AR_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> CreatedOut:
    """登记回款（超额拒绝；重算 status；异步重算该客户风险分）。"""
    payment = ar_service.create_payment(db, payload)
    audit_service.log_action(
        db,
        "ar.payment.create",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="ar_payment",
        object_id=str(payment.id),
        after={"receivable_id": payment.receivable_id, "amount": str(payment.amount)},
    )
    db.commit()
    _trigger_rescore(payload.customer_id)
    return CreatedOut(id=payment.id, extra={"receivable_id": payment.receivable_id})


@router.post("/collection-records", response_model=CreatedOut, status_code=201)
def create_collection_record(
    payload: CollectionRecordCreateRequest,
    current_user: Annotated[SysUser, Depends(require_perm(Permission.AR_MANAGE.value))],
    db: Annotated[Session, Depends(get_db)],
) -> CreatedOut:
    """登记催收记录（异步重算该客户风险分）。"""
    record = ar_service.create_collection_record(db, payload)
    audit_service.log_action(
        db,
        "ar.collection.create",
        actor_id=current_user.id,
        actor_name=current_user.username,
        object_type="collection_record",
        object_id=str(record.id),
        after={"customer_id": record.customer_id},
    )
    db.commit()
    _trigger_rescore(payload.customer_id)
    return CreatedOut(id=record.id, extra={"customer_id": record.customer_id})


@router.get("/risk-ranking", response_model=list[RiskRankingItemOut])
def risk_ranking(
    _: Annotated[SysUser, Depends(require_perm(Permission.AR_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
    min_score: int = Query(default=70, ge=0, le=100),
) -> list[RiskRankingItemOut]:
    """高风险客户排名（最新评分，风险分降序）。"""
    rows = ar_service.risk_ranking(db, min_score=min_score, limit=limit)
    return [RiskRankingItemOut(**r) for r in rows]  # type: ignore[arg-type]


@router.get("/{customer_id}/detail", response_model=CustomerDetailOut)
def customer_detail(
    customer_id: int,
    _: Annotated[SysUser, Depends(require_perm(Permission.AR_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
) -> CustomerDetailOut:
    """客户应收明细 + 因子明细（raw/weight/weighted）+ 总分。"""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("客户不存在")
    score = ar_service.latest_score(db, customer_id)
    rows, _customer_names, _scored, contracts = ar_service.list_receivables(  # noqa: PERF401
        db, customer_id=customer_id
    )
    today = datetime.now(UTC).date()
    receivables: list[dict[str, object]] = []
    for r in rows:
        paid = ar_service.paid_total(db, r.id)
        receivables.append(
            {
                "receivable_id": r.id,
                "contract_no": contracts.get(r.contract_id) if r.contract_id else None,
                "amount": str(r.amount),
                "due_date": r.due_date.isoformat(),
                "overdue_days": max(0, (today - r.due_date).days),
                "status": r.status,
                "outstanding_balance": str(r.amount - paid),
            }
        )
    return CustomerDetailOut(
        customer_id=customer.id,
        customer_name=customer.name,
        receivables=receivables,
        factors=(score.factors if score and score.factors else {}),
        total_score=score.total_score if score else 0,
        risk_level=score.risk_level if score else "low",
        expected_payment_date=score.expected_payment_date if score else None,
        expected_overdue_days=score.expected_overdue_days if score else None,
        overdue_amount=score.overdue_amount if score else Decimal(0),
    )


@router.get("/risk-status", response_model=RiskStatusOut)
def risk_status(
    _: Annotated[SysUser, Depends(require_perm(Permission.AR_VIEW.value))],
    db: Annotated[Session, Depends(get_db)],
) -> RiskStatusOut:
    """最近一次全量评分任务状态。"""
    info = ar_service.latest_risk_run(db)
    if info is None:
        return RiskStatusOut(status="never_run")
    return RiskStatusOut(**info)  # type: ignore[arg-type]
