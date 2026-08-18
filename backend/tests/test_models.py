"""数据模型建表与关键约束测试。"""

from datetime import date
from decimal import Decimal

from app.models.ar_domain import ArReceivable
from app.models.base_data import CostCategory
from app.models.enums import ReceivableStatus, ReimbursementStatus
from app.models.reimbursement import Reimbursement, ReimbursementItem
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_cost_category_defaults(db_session: Session) -> None:
    cat = CostCategory(code="TRAVEL", name="差旅费")
    db_session.add(cat)
    db_session.commit()
    assert cat.id is not None
    assert cat.enabled is True


def test_reimbursement_decimal_and_status(db_session: Session) -> None:
    r = Reimbursement(
        no="REIM-001", applicant_id=1, department_id=1, total_amount=Decimal("1234.56")
    )
    db_session.add(r)
    db_session.commit()
    db_session.refresh(r)
    assert r.total_amount == Decimal("1234.56")
    assert r.status == ReimbursementStatus.DRAFT.value


def test_receivable_default_status(db_session: Session) -> None:
    r = ArReceivable(customer_id=1, amount=Decimal("100.00"), due_date=date(2026, 9, 15))
    db_session.add(r)
    db_session.commit()
    assert r.status == ReceivableStatus.OPEN.value


def test_reimbursement_item_invoice_key_not_unique(db_session: Session) -> None:
    """invoice_key 为普通索引，允许重复（冻结口径，非全表 UNIQUE）。"""
    r1 = Reimbursement(no="REIM-001", applicant_id=1, department_id=1, total_amount=Decimal("1"))
    r2 = Reimbursement(no="REIM-002", applicant_id=1, department_id=1, total_amount=Decimal("1"))
    db_session.add_all([r1, r2])
    db_session.flush()
    db_session.add_all(
        [
            ReimbursementItem(
                reimbursement_id=r1.id, cost_category_id=1, amount=Decimal("1"), invoice_key="INV-1"
            ),
            ReimbursementItem(
                reimbursement_id=r2.id, cost_category_id=1, amount=Decimal("1"), invoice_key="INV-1"
            ),
        ]
    )
    # 不抛 IntegrityError 即通过
    db_session.commit()


def test_cost_category_code_unique(db_session: Session) -> None:
    db_session.add(CostCategory(code="DUP", name="一"))
    db_session.commit()
    db_session.add(CostCategory(code="DUP", name="二"))
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return
    raise AssertionError("科目编码应唯一，但未抛出 IntegrityError")
