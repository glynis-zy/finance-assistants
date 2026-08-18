# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportArgumentType=false, reportOptionalMemberAccess=false, reportMissingParameterType=false, reportUnknownParameterType=false
"""规则引擎单元测试 + 解析快照重放 + 台账幂等。"""

from datetime import date
from decimal import Decimal

from app.clients.ocr import OCRClient, OCRResult
from app.domain.risk_engine.rules import (
    check_amount_match,
    check_budget_within,
    check_duplicate_invoice,
    check_invoice_exists,
    check_title_match,
)
from app.domain.risk_engine.types import BudgetCheck, ParsedDocument, RuleContext
from app.models.base_data import CostCategory
from app.models.enums import AuditResult, TaskStatus
from app.models.reimbursement import AuditTask, Reimbursement, ReimbursementItem
from app.schemas.documents import InvoiceData
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.helpers import add_attachment, seed_base


def _reimb(total: str = "1000.00") -> Reimbursement:
    return Reimbursement(
        no="REIM-T", applicant_id=1, department_id=1, project_id=1, total_amount=Decimal(total)
    )


def _item(category_id: int = 1, invoice_key: str = "INV-1") -> ReimbursementItem:
    return ReimbursementItem(
        cost_category_id=category_id, amount=Decimal("1000.00"), invoice_key=invoice_key
    )


def _invoice(
    amount: str = "1000.00", buyer: str = "某某科技有限公司", desc: str = "差旅费-高铁票"
) -> ParsedDocument:
    return ParsedDocument(
        category="invoice",
        confidence=0.95,
        low_confidence=False,
        data=InvoiceData(
            invoice_no="INV-1",
            amount=Decimal(amount),
            buyer_name=buyer,
            invoice_date=date(2026, 8, 1),
            invoice_type="增值税普通发票",
            description=desc,
        ),
    )


def _ctx(**kwargs) -> RuleContext:
    defaults = {
        "reimbursement": _reimb(),
        "items": [_item()],
        "parsed_docs": [_invoice()],
        "categories": [CostCategory(code="TRAVEL", name="差旅费", enabled=True)],
        "budget_checks": [BudgetCheck(1, Decimal("100000"), Decimal("0"), Decimal("1000.00"))],
        "company_name": "某某科技有限公司",
        "thresholds": {"threshold.reimb.over_amount": "5000.00"},
        "existing_invoice_keys": set(),
        "project_name": "华东大区",
        "applicant_name": "张三",
    }
    defaults.update(kwargs)
    return RuleContext(**defaults)


def test_amount_match_failed() -> None:
    ctx = _ctx(reimbursement=_reimb("800.00"))
    r = check_amount_match(ctx)
    assert r.status == "failed"


def test_title_match_failed() -> None:
    ctx = _ctx(parsed_docs=[_invoice(buyer="其他公司")])
    assert check_title_match(ctx).status == "failed"


def test_duplicate_invoice_failed() -> None:
    ctx = _ctx(existing_invoice_keys={"INV-1"})
    assert check_duplicate_invoice(ctx).status == "failed"


def test_budget_overrun_failed() -> None:
    ctx = _ctx(budget_checks=[BudgetCheck(1, Decimal("500"), Decimal("0"), Decimal("1000.00"))])
    assert check_budget_within(ctx).status == "failed"


def test_budget_missing_uncertain() -> None:
    ctx = _ctx(budget_checks=[])
    assert check_budget_within(ctx).status == "uncertain"


def test_invoice_exists_failed_no_attachment() -> None:
    ctx = _ctx(parsed_docs=[])
    assert check_invoice_exists(ctx).status == "failed"


def test_invoice_exists_uncertain_low_confidence() -> None:
    doc = ParsedDocument(category="invoice", confidence=0.5, low_confidence=True, data=None)
    ctx = _ctx(parsed_docs=[doc])
    assert check_invoice_exists(ctx).status == "uncertain"


def test_parse_snapshot_replay(db_session: Session, monkeypatch) -> None:
    """解析快照重放：第二次解析不重新调用 OCR。"""
    base = seed_base(db_session)
    reimb = Reimbursement(
        no="REIM-R",
        applicant_id=1,
        department_id=base.dept.id,
        project_id=base.proj.id,
        total_amount=Decimal("1000.00"),
    )
    db_session.add(reimb)
    db_session.flush()
    add_attachment(db_session, reimb.id, "invoice")
    from app.models.base_data import Attachment
    from app.services import parse_service

    att = db_session.scalar(select(Attachment))
    calls = {"n": 0}

    class CountingOCR(OCRClient):
        def parse(self, doc_type: str, file_name: str, content: bytes | None) -> OCRResult:
            calls["n"] += 1
            return OCRResult(
                doc_type=doc_type,
                fields={
                    "invoice_no": "INV-1",
                    "amount": "1000.00",
                    "buyer_name": "某某科技有限公司",
                    "invoice_date": "2026-08-01",
                    "invoice_type": "增值税普通发票",
                    "description": "差旅费-高铁票",
                },
                confidence=0.95,
                mode="preset",
            )

    monkeypatch.setattr("app.clients.ocr.get_ocr_client", lambda: CountingOCR())
    parse_service.parse_attachments(db_session, reimb, [att])
    db_session.commit()
    parse_service.parse_attachments(db_session, reimb, [att])
    assert calls["n"] == 1


def test_ledger_idempotent(db_session: Session) -> None:
    """重复执行 run_audit（任务已终态）不重复写台账。"""
    from app.models.base_data import ExpenseLedger
    from app.services import audit_flow_service

    from tests.helpers import make_user

    base = seed_base(db_session)
    applicant = make_user(db_session, "zhang", "applicant", name="张三")
    reimb = Reimbursement(
        no="REIM-L",
        applicant_id=applicant.id,
        department_id=base.dept.id,
        project_id=base.proj.id,
        total_amount=Decimal("1000.00"),
    )
    db_session.add(reimb)
    db_session.flush()
    db_session.add(
        ReimbursementItem(
            reimbursement_id=reimb.id,
            cost_category_id=base.travel.id,
            amount=Decimal("1000.00"),
            invoice_key="INV-L",
            description="差旅费-高铁票",
        )
    )
    db_session.flush()
    for cat in ("invoice", "travel", "approval"):
        add_attachment(db_session, reimb.id, cat)
    task = AuditTask(reimbursement_id=reimb.id, status=TaskStatus.QUEUED.value)
    db_session.add(task)
    db_session.flush()

    audit_flow_service.run_audit(db_session, reimb.id, task.id)
    assert db_session.get(Reimbursement, reimb.id).status == AuditResult.APPROVED.value
    audit_flow_service.run_audit(db_session, reimb.id, task.id)  # 幂等：已 done 直接返回

    count = db_session.scalar(
        select(func.count()).select_from(ExpenseLedger).where(ExpenseLedger.ref_no == reimb.no)
    )
    assert count == 1
