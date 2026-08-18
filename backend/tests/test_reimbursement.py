# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportArgumentType=false, reportOptionalMemberAccess=false, reportMissingParameterType=false, reportUnknownParameterType=false
"""报销审核核心链路集成测试（docs/requirements.md §7.1）。"""

from copy import deepcopy
from decimal import Decimal

from app.clients.ocr import OCRClient, OCRResult
from app.clients.presets import PRESETS
from app.models.base_data import Budget, ExpenseLedger
from app.models.reimbursement import Reimbursement
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.helpers import (
    add_attachment,
    create_reimb,
    login,
    make_user,
    seed_base,
    submit,
)


def _patch_ocr(monkeypatch, fields_by_type=None, confidence: float = 0.95) -> None:
    """monkeypatch OCR，返回可定制的预设字段与置信度。"""

    class StubOCR(OCRClient):
        def parse(self, doc_type: str, file_name: str, content: bytes | None) -> OCRResult:
            fields = deepcopy(PRESETS.get(doc_type, {}))
            if fields_by_type and doc_type in fields_by_type:
                fields.update(fields_by_type[doc_type])
            return OCRResult(doc_type=doc_type, fields=fields, confidence=confidence, mode="preset")

    monkeypatch.setattr("app.clients.ocr.get_ocr_client", lambda: StubOCR())


def _applicant_and_finance(db: Session):
    applicant = make_user(db, "zhang", "applicant", name="张三")
    make_user(db, "finance", "finance")
    return applicant


def _full_materials(db: Session, rid: int) -> None:
    """差旅类报销所需三附件：发票 + 行程单 + 审批单。"""
    add_attachment(db, rid, "invoice")
    add_attachment(db, rid, "travel")
    add_attachment(db, rid, "approval")


def test_approved_writes_ledger(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)

    reimb = db_session.get(Reimbursement, rid)
    assert reimb.status == "approved"
    ledger = db_session.scalar(
        select(func.count()).select_from(ExpenseLedger).where(ExpenseLedger.ref_no == reimb.no)
    )
    assert ledger == 1


def test_amount_mismatch_returned(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base, total="800.00")
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "returned"


def test_title_mismatch_returned(client: TestClient, db_session: Session, monkeypatch) -> None:
    _patch_ocr(monkeypatch, fields_by_type={"invoice": {"buyer_name": "其他公司"}})
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "returned"


def test_low_confidence_manual_review(client: TestClient, db_session: Session, monkeypatch) -> None:
    _patch_ocr(monkeypatch, confidence=0.5)
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "manual_review"


def test_missing_field_manual_review(client: TestClient, db_session: Session, monkeypatch) -> None:
    _patch_ocr(monkeypatch, fields_by_type={"invoice": {"amount": ""}})
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "manual_review"


def test_duplicate_invoice_blocked(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    # 第一单通过
    rid1 = create_reimb(client, token, base, invoice_key="INV-DUP")
    _full_materials(db_session, rid1)
    submit(client, token, rid1)
    assert db_session.get(Reimbursement, rid1).status == "approved"
    # 第二单同发票号 → 重复拦截
    rid2 = create_reimb(client, token, base, invoice_key="INV-DUP")
    _full_materials(db_session, rid2)
    submit(client, token, rid2)
    assert db_session.get(Reimbursement, rid2).status == "returned"


def test_returned_can_resubmit_same_invoice(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    # 缺行程单 → 退回
    rid = create_reimb(client, token, base, invoice_key="INV-REUSE")
    add_attachment(db_session, rid, "invoice")
    add_attachment(db_session, rid, "approval")
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "returned"
    # 补行程单后重新提交，同一发票不被重复拦截
    add_attachment(db_session, rid, "travel")
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "approved"


def test_budget_overrun_returned(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    # 收紧预算至 500，报销 1000 → 超支
    budget = db_session.scalar(select(Budget).where(Budget.cost_category_id == base.travel.id))
    assert budget is not None
    budget.amount = Decimal("500")
    db_session.commit()
    token = login(client, "zhang")
    rid = create_reimb(client, token, base, total="1000.00")
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "returned"


def test_approval_mismatch_returned(client: TestClient, db_session: Session, monkeypatch) -> None:
    _patch_ocr(monkeypatch, fields_by_type={"approval": {"applicant_name": "李四"}})
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "returned"


def test_rule_category_hit(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)  # 发票 description 含「高铁」→ 规则命中 TRAVEL
    _full_materials(db_session, rid)
    submit(client, token, rid)
    reimb = db_session.get(Reimbursement, rid)
    assert reimb.status == "approved"
    detail = client.get(
        f"/api/reimbursements/{rid}", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert detail["conclusion"]["recommended_category"]["name"] == "差旅费"


def test_llm_category_fallback(client: TestClient, db_session: Session, monkeypatch) -> None:
    _patch_ocr(monkeypatch, fields_by_type={"invoice": {"description": "其他费用"}})
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "approved"


def test_llm_failure_degrades(client: TestClient, db_session: Session, monkeypatch) -> None:
    from app.clients.llm import LLMClient

    class FailingLLM(LLMClient):
        def extract(self, doc_type: str, fields):
            raise RuntimeError("LLM 失败")

        def recommend_category(self, description: str):
            raise RuntimeError("LLM 失败")

    monkeypatch.setattr("app.clients.llm.get_llm_client", lambda: FailingLLM())
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "manual_review"


def test_permission_forbidden(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    zhang = login(client, "zhang")
    rid = create_reimb(client, zhang, base)
    # 另一申请人访问他人单据 → 403 数据越权
    make_user(db_session, "lisi", "applicant", name="李四")
    lisi = login(client, "lisi")
    resp = client.get(f"/api/reimbursements/{rid}", headers={"Authorization": f"Bearer {lisi}"})
    assert resp.status_code == 403
    # 申请人访问系统参数 → 403 无权限
    resp = client.get("/api/sys-params", headers={"Authorization": f"Bearer {zhang}"})
    assert resp.status_code == 403


def test_invalid_state_operation(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)
    assert db_session.get(Reimbursement, rid).status == "approved"
    # approved 终态再提交 → 409
    resp = client.post(
        f"/api/reimbursements/{rid}/submit", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 409


def test_manual_review_flow(client: TestClient, db_session: Session, monkeypatch) -> None:
    _patch_ocr(monkeypatch, confidence=0.5)
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    zhang = login(client, "zhang")
    finance = login(client, "finance")
    rid = create_reimb(client, zhang, base)
    _full_materials(db_session, rid)
    submit(client, zhang, rid)
    assert db_session.get(Reimbursement, rid).status == "manual_review"
    # 财务裁决 approved
    resp = client.post(
        f"/api/reimbursements/{rid}/manual-review",
        json={"conclusion": "approved", "reason": "人工复核通过"},
        headers={"Authorization": f"Bearer {finance}"},
    )
    assert resp.status_code == 200
    assert db_session.get(Reimbursement, rid).status == "approved"


def test_manual_review_returned(client: TestClient, db_session: Session, monkeypatch) -> None:
    _patch_ocr(monkeypatch, confidence=0.5)
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    zhang = login(client, "zhang")
    finance = login(client, "finance")
    rid = create_reimb(client, zhang, base)
    _full_materials(db_session, rid)
    submit(client, zhang, rid)
    assert db_session.get(Reimbursement, rid).status == "manual_review"
    resp = client.post(
        f"/api/reimbursements/{rid}/manual-review",
        json={"conclusion": "returned", "reason": "材料不实"},
        headers={"Authorization": f"Bearer {finance}"},
    )
    assert resp.status_code == 200
    assert db_session.get(Reimbursement, rid).status == "returned"


def test_html_report(client: TestClient, db_session: Session) -> None:
    base = seed_base(db_session)
    _applicant_and_finance(db_session)
    token = login(client, "zhang")
    rid = create_reimb(client, token, base)
    _full_materials(db_session, rid)
    submit(client, token, rid)
    resp = client.get(
        f"/api/reimbursements/{rid}/report", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert "报销审核报告" in resp.text
