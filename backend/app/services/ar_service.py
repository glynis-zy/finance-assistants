"""应收预警服务（3.3.3）：业务操作 + 评分持久化（每日 upsert 幂等）+ 预警。

L1 在路由层；业务校验（合同归属/超额回款）与本层；评分结果落 ar_risk_score。
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.domain.scoring_engine import compute
from app.domain.scoring_engine.engine import DEFAULT_THRESHOLDS
from app.domain.scoring_engine.types import (
    CollectionInput,
    PaymentInput,
    ReceivableInput,
    ScoreResult,
)
from app.models.alert import Alert
from app.models.ar_domain import (
    ArPayment,
    ArReceivable,
    ArRiskRun,
    ArRiskScore,
    CollectionRecord,
)
from app.models.base_data import Contract, Customer, SysParam
from app.models.enums import ReceivableStatus
from app.schemas.ar import (
    CollectionRecordCreateRequest,
    PaymentCreateRequest,
    ReceivableCreateRequest,
)


def _load_thresholds(db: Session) -> dict[str, float]:
    out: dict[str, float] = dict(DEFAULT_THRESHOLDS)
    for p in db.scalars(select(SysParam).where(SysParam.key.like("threshold.ar.%"))).all():
        try:
            out[p.key] = float(p.value)
        except ValueError:
            continue
    return out


def create_receivable(db: Session, payload: ReceivableCreateRequest) -> ArReceivable:
    """登记应收（status 默认 open；contract 必须属于 customer）。"""
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise NotFoundError("客户不存在")
    contract = db.get(Contract, payload.contract_id)
    if contract is None:
        raise NotFoundError("合同不存在")
    if contract.customer_id != payload.customer_id:
        raise ValidationError("合同必须属于该客户")
    receivable = ArReceivable(
        customer_id=payload.customer_id,
        contract_id=payload.contract_id,
        invoice_no=payload.invoice_no,
        amount=payload.amount,
        due_date=payload.due_date,
        status=ReceivableStatus.OPEN.value,
    )
    db.add(receivable)
    db.flush()
    return receivable


def paid_total(db: Session, receivable_id: int) -> Decimal:
    """应收单累计到账金额。"""
    paid = db.scalar(
        select(func.coalesce(func.sum(ArPayment.amount), 0)).where(
            ArPayment.receivable_id == receivable_id
        )
    )
    return Decimal(str(paid or 0))


def _refresh_status(db: Session, receivable: ArReceivable) -> None:
    """按累计到账重算 status：0 → open；0<累计<金额 → partial；>=金额 → settled。"""
    paid = paid_total(db, receivable.id)
    if paid <= 0:
        receivable.status = ReceivableStatus.OPEN.value
    elif paid >= receivable.amount:
        receivable.status = ReceivableStatus.SETTLED.value
    else:
        receivable.status = ReceivableStatus.PARTIAL.value


def create_payment(db: Session, payload: PaymentCreateRequest) -> ArPayment:
    """登记回款（customer 匹配、超额拒绝、重算 status）。"""
    receivable = db.get(ArReceivable, payload.receivable_id)
    if receivable is None:
        raise NotFoundError("应收不存在")
    if receivable.customer_id != payload.customer_id:
        raise ValidationError("回款客户必须与应收一致")
    outstanding = receivable.amount - paid_total(db, receivable.id)
    if payload.amount > outstanding:
        raise ValidationError("回款金额超过未结余额")
    payment = ArPayment(
        receivable_id=receivable.id,
        customer_id=payload.customer_id,
        amount=payload.amount,
        received_at=payload.received_at or datetime.now(UTC),
        remark=payload.remark,
    )
    db.add(payment)
    db.flush()
    _refresh_status(db, receivable)
    return payment


def create_collection_record(
    db: Session, payload: CollectionRecordCreateRequest
) -> CollectionRecord:
    """登记催收记录。"""
    if db.get(Customer, payload.customer_id) is None:
        raise NotFoundError("客户不存在")
    record = CollectionRecord(
        customer_id=payload.customer_id,
        channel=payload.channel,
        action=payload.action,
        result=payload.result,
        remark=payload.remark,
        occurred_at=payload.occurred_at or datetime.now(UTC),
    )
    db.add(record)
    db.flush()
    return record


def list_receivables(
    db: Session,
    *,
    customer_id: int | None = None,
    status: str | None = None,
    due_before: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ArReceivable], int, dict[int, str], dict[int, str]]:
    """应收列表（分页）。"""
    filters: list[Any] = []
    if customer_id is not None:
        filters.append(ArReceivable.customer_id == customer_id)
    if status is not None:
        filters.append(ArReceivable.status == status)
    if due_before is not None:
        filters.append(ArReceivable.due_date <= due_before)
    count_q = select(ArReceivable.id)
    items_q = select(ArReceivable)
    for f in filters:
        count_q = count_q.where(f)  # type: ignore[arg-type]
        items_q = items_q.where(f)  # type: ignore[arg-type]
    total = len(db.scalars(count_q).all())
    rows = list(
        db.scalars(
            items_q.order_by(ArReceivable.due_date.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    customers = {c.id: c.name for c in db.scalars(select(Customer)).all()}
    contracts = {c.id: c.contract_no for c in db.scalars(select(Contract)).all()}
    return rows, total, customers, contracts


# ---------------------------------------------------------------- scoring


def _receivable_inputs(
    db: Session, customer_id: int
) -> tuple[list[ReceivableInput], list[PaymentInput], list[CollectionInput], dict[int, int]]:
    """装配该客户评分输入（含合同账期与累计到账）。"""
    receivables = list(
        db.scalars(select(ArReceivable).where(ArReceivable.customer_id == customer_id)).all()
    )
    payments = list(db.scalars(select(ArPayment).where(ArPayment.customer_id == customer_id)).all())
    collections = list(
        db.scalars(
            select(CollectionRecord).where(CollectionRecord.customer_id == customer_id)
        ).all()
    )
    term_map: dict[int, int] = {}
    for c in db.scalars(select(Contract)).all():
        term_map[c.id] = c.payment_term
    paid_by_rec: dict[int, Decimal] = {}
    for p in payments:
        paid_by_rec[p.receivable_id] = paid_by_rec.get(p.receivable_id, Decimal(0)) + p.amount

    rec_inputs = [
        ReceivableInput(
            receivable_id=r.id,
            customer_id=r.customer_id,
            contract_id=r.contract_id,
            amount=float(r.amount),
            paid_amount=float(paid_by_rec.get(r.id, Decimal(0))),
            due_date=r.due_date,
            status=r.status,
            payment_term_days=term_map.get(r.contract_id, 30) if r.contract_id else 30,
        )
        for r in receivables
    ]
    pay_inputs = [
        PaymentInput(
            receivable_id=p.receivable_id, amount=float(p.amount), received_at=p.received_at
        )
        for p in payments
    ]
    col_inputs = [CollectionInput(occurred_at=c.occurred_at) for c in collections]
    return rec_inputs, pay_inputs, col_inputs, term_map


def score_customer(db: Session, customer_id: int, score_date: date | None = None) -> ScoreResult:
    """计算并持久化客户当日评分（同日 upsert 幂等）；high 建预警（unique_key 幂等）。"""
    score_date = score_date or datetime.now(UTC).date()
    if db.get(Customer, customer_id) is None:
        raise NotFoundError("客户不存在")
    rec_inputs, pay_inputs, col_inputs, _ = _receivable_inputs(db, customer_id)
    result = compute(
        customer_id, score_date, rec_inputs, pay_inputs, col_inputs, _load_thresholds(db)
    )

    existing = db.scalar(
        select(ArRiskScore).where(
            ArRiskScore.customer_id == customer_id, ArRiskScore.score_date == score_date
        )
    )
    if existing is None:
        existing = ArRiskScore(
            customer_id=customer_id, score_date=score_date, total_score=0, risk_level="low"
        )
        db.add(existing)
    existing.total_score = result.total_score
    existing.risk_level = result.risk_level
    existing.factors = {
        name: {
            "raw_score": f.raw_score,
            "weight": f.weight,
            "weighted_score": f.weighted_score,
            "detail": f.detail,
        }
        for name, f in result.factors.items()
    }
    existing.expected_payment_date = result.expected_payment_date
    existing.expected_overdue_days = result.expected_overdue_days
    existing.overdue_amount = Decimal(str(result.overdue_amount))

    # high → alert（unique_key 幂等）
    high = _load_thresholds(db)["threshold.ar.high_score"]
    if result.total_score >= high:
        unique_key = f"ar:{customer_id}:{score_date.isoformat()}"
        exists = db.scalar(select(Alert.id).where(Alert.unique_key == unique_key))
        if exists is None:
            db.add(
                Alert(
                    alert_type="ar",
                    level="critical",
                    unique_key=unique_key,
                    summary=f"客户 {customer_id} 应收高风险（{score_date}）",
                    detail={
                        "customer_id": customer_id,
                        "score": result.total_score,
                        "risk_level": result.risk_level,
                        "overdue_amount": str(result.overdue_amount),
                        "score_date": score_date.isoformat(),
                    },
                )
            )
    db.commit()
    return result


def score_all(db: Session, score_date: date | None = None) -> dict[str, int]:
    """全量评分（beat 每日触发）：写 ar_risk_run，每客户每日 upsert，幂等。"""
    score_date = score_date or datetime.now(UTC).date()
    run = ArRiskRun(status="running")
    db.add(run)
    db.commit()
    customer_ids = list(
        db.scalars(
            select(ArReceivable.customer_id).distinct().order_by(ArReceivable.customer_id)
        ).all()
    )
    high_count = 0
    try:
        for cid in customer_ids:
            result = score_customer(db, cid, score_date)
            if result.risk_level == "high":
                high_count += 1
        run.status = "done"
        run.finished_at = datetime.now(UTC)
        run.customer_count = len(customer_ids)
        run.high_risk_count = high_count
        db.commit()
    except Exception as exc:
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error = str(exc)[:500]
        db.commit()
        raise
    return {"customers": len(customer_ids), "high_risk": high_count}


def latest_risk_run(db: Session) -> dict[str, object] | None:
    """最近一次全量评分运行状态。"""
    run = db.scalar(select(ArRiskRun).order_by(ArRiskRun.id.desc()).limit(1))
    if run is None:
        return None
    return {
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "customer_count": run.customer_count,
        "high_risk_count": run.high_risk_count,
        "error": run.error,
    }


def latest_score(db: Session, customer_id: int) -> ArRiskScore | None:
    """客户最新评分记录。"""
    return db.scalar(
        select(ArRiskScore)
        .where(ArRiskScore.customer_id == customer_id)
        .order_by(ArRiskScore.score_date.desc())
        .limit(1)
    )


def risk_ranking(db: Session, min_score: int = 70, limit: int = 20) -> list[dict[str, object]]:
    """高风险客户排名：每客户最新评分，risk_score 降序，overdue_amount 取评分快照。"""
    customers = {c.id: c.name for c in db.scalars(select(Customer)).all()}
    scores = list(db.scalars(select(ArRiskScore).order_by(ArRiskScore.score_date.desc())).all())
    latest: dict[int, ArRiskScore] = {}
    for s in scores:
        latest.setdefault(s.customer_id, s)
    rows: list[dict[str, object]] = []
    for cid, score in latest.items():
        if score.total_score < min_score:
            continue
        rows.append(
            {
                "customer_id": cid,
                "customer_name": customers.get(cid, str(cid)),
                "risk_score": score.total_score,
                "risk_level": score.risk_level,
                "overdue_amount": score.overdue_amount,
                "expected_payment_date": score.expected_payment_date,
                "expected_overdue_days": score.expected_overdue_days,
                "collection_priority": (
                    1 if score.total_score >= 70 else 2 if score.total_score >= 40 else 3
                ),
            }
        )
    rows.sort(key=lambda x: int(x["risk_score"]), reverse=True)  # type: ignore[arg-type]
    return rows[:limit]
