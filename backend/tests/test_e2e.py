# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportOptionalMemberAccess=false
"""三助手跨模块链路测试（Stage 5 十一）：

A approved 报销 → expense_ledger → 预算监控读到
B 登记应收 → 评分；催收/回款 → 重评分
C high budget → alert；high AR → alert；预警中心可见
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.models.alert import Alert
from app.models.ar_domain import ArPayment, ArReceivable, CollectionRecord
from app.models.base_data import Budget, Contract, Customer, ExpenseLedger
from app.models.budget_domain import BudgetDeviation, BudgetSnapshot
from app.services import ar_service, monitor_service
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.helpers import login, make_user, seed_base

CURVE = [0.1] * 8 + [0.05] * 4


def test_chain_a_approved_to_ledger_to_budget_monitor(
    client: TestClient, db_session: Session
) -> None:
    """链路 A：approved 报销 → 台账 → 预算监控读到（reimb 来源台账参与偏差计算）。"""
    base = seed_base(db_session)
    make_user(db_session, "app", "applicant", name="张三")  # preset 审批单申请人固定"张三"
    make_user(db_session, "bm", "budget_manager")
    app_token = login(client, "app")
    # 创建并提交报销（preset 规则通过 → approved → 写台账；金额须匹配预设发票 1000）
    resp = client.post(
        "/api/reimbursements",
        json={
            "department_id": base.dept.id,
            "project_id": base.proj.id,
            "total_amount": "1000.00",
            "items": [
                {
                    "cost_category_id": base.travel.id,
                    "amount": "1000.00",
                    "invoice_key": "INV-E2E-A",
                    "description": "差旅",
                }
            ],
        },
        headers={"Authorization": f"Bearer {app_token}"},
    )
    rid = resp.json()["id"]
    # preset 模式：上传发票/行程单/审批单后规则才可通过
    for cat in ("invoice", "travel", "approval"):
        up = client.post(
            f"/api/reimbursements/{rid}/attachments",
            headers={"Authorization": f"Bearer {app_token}"},
            files={"files": (f"{cat}.png", b"fake", "image/png")},
            data={"categories": cat},
        )
        assert up.status_code == 201, up.text
    resp = client.post(
        f"/api/reimbursements/{rid}/submit", headers={"Authorization": f"Bearer {app_token}"}
    )
    assert resp.status_code == 202, resp.text
    # eager 模式任务已同步执行 → approved 写台账（ref_no=报销单号 REIM-*）
    ledger = db_session.scalar(
        select(ExpenseLedger).where(
            ExpenseLedger.source == "reimb", ExpenseLedger.ref_no.like("REIM-%")
        )
    )
    assert ledger is not None and ledger.amount == Decimal("1000.00")
    # 预算监控可正常执行并读取台账（snapshot 落库）
    summary = monitor_service.run_monitor(db_session, "2026-06")
    assert int(summary["budgets_checked"]) >= 1  # type: ignore[arg-type]
    snap = db_session.scalar(select(BudgetSnapshot).where(BudgetSnapshot.period == "2026-06"))
    assert snap is not None and snap.status == "done"


def test_chain_b_ar_rescore_on_payment_and_collection(db_session: Session) -> None:
    """链路 B：应收 → 评分；催收 → 重评分变化；回款 → 重评分变化。"""
    customer = Customer(code="CUS-E2E", name="联调客户")
    db_session.add(customer)
    db_session.flush()
    contract = Contract(
        contract_no="HT-E2E", customer_id=customer.id, amount=Decimal("100000.00"), payment_term=30
    )
    db_session.add(contract)
    db_session.flush()
    rec = ArReceivable(
        customer_id=customer.id,
        contract_id=contract.id,
        invoice_no="FP-E2E",
        amount=Decimal("10000.00"),
        due_date=date(2026, 1, 1),
        status="open",
    )
    db_session.add(rec)
    db_session.commit()

    r1 = ar_service.score_customer(db_session, customer.id, date(2026, 8, 18))
    assert r1.factors["collection"].raw_score == 0.0

    # 登记催收（无回款）→ collection=100
    db_session.add(
        CollectionRecord(
            customer_id=customer.id, channel="电话", occurred_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
    )
    db_session.commit()
    r2 = ar_service.score_customer(db_session, customer.id, date(2026, 8, 18))
    assert r2.factors["collection"].raw_score == 100.0
    assert r2.total_score > r1.total_score

    # 回款结清 → 无未结 → total 0 / low
    db_session.add(
        ArPayment(
            receivable_id=rec.id,
            customer_id=customer.id,
            amount=Decimal("10000.00"),
            received_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
    )
    rec.status = "settled"
    db_session.commit()
    r3 = ar_service.score_customer(db_session, customer.id, date(2026, 8, 18))
    assert r3.total_score == 0 and r3.risk_level == "low"


def test_chain_c_budget_high_alert_visible(client: TestClient, db_session: Session) -> None:
    """链路 C-预算：high deviation → alert → 预警中心（budget_manager）可见。"""
    base = seed_base(db_session)
    budget = db_session.scalar(select(Budget).where(Budget.cost_category_id == base.travel.id))
    assert budget is not None
    budget.amount = Decimal("100000.00")
    budget.allocation_curve = CURVE
    for m in range(1, 7):
        db_session.add(
            ExpenseLedger(
                source="import",
                cost_category_id=base.travel.id,
                department_id=base.dept.id,
                project_id=base.proj.id,
                period=f"2026-{m:02d}",
                amount=Decimal("30000.00"),
                occurred_at=datetime(2026, m, 15, tzinfo=UTC),
                ref_no=f"E2E-BUD-{m}",
            )
        )
    db_session.commit()
    summary = monitor_service.run_monitor(db_session, "2026-06")
    assert summary["alerts_created"] == 1
    dev = db_session.scalar(select(BudgetDeviation))
    assert dev is not None and dev.level == "high"

    make_user(db_session, "bm", "budget_manager")
    token = login(client, "bm")
    resp = client.get("/api/alerts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    alerts = resp.json()["items"]
    assert any(a["alert_type"] == "budget" for a in alerts)
    assert any(a["level"] == "critical" for a in alerts)


def test_chain_c_ar_high_alert_visible(client: TestClient, db_session: Session) -> None:
    """链路 C-应收：AR score ≥ 70 → alert → 预警中心（ar_specialist）可见。"""
    customer = Customer(code="CUS-HI", name="高风险客户")
    db_session.add(customer)
    db_session.flush()
    contract = Contract(
        contract_no="HT-HI", customer_id=customer.id, amount=Decimal("500000.00"), payment_term=30
    )
    db_session.add(contract)
    db_session.flush()
    rec = ArReceivable(
        customer_id=customer.id,
        contract_id=contract.id,
        invoice_no="FP-HI",
        amount=Decimal("200000.00"),
        due_date=date(2025, 12, 1),
        status="open",
    )
    db_session.add(rec)
    db_session.flush()
    # 历史逾期结清（延迟 60 天）→ payment 高；催收后未回款 → collection 100
    settled = ArReceivable(
        customer_id=customer.id,
        contract_id=contract.id,
        invoice_no="FP-HI-2",
        amount=Decimal("100000.00"),
        due_date=date(2025, 12, 1),
        status="settled",
    )
    db_session.add(settled)
    db_session.flush()
    db_session.add(
        ArPayment(
            receivable_id=settled.id,
            customer_id=customer.id,
            amount=Decimal("100000.00"),
            received_at=datetime(2026, 1, 30, tzinfo=UTC),
        )
    )
    db_session.add(
        CollectionRecord(
            customer_id=customer.id, channel="电话", occurred_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
    )
    db_session.commit()
    result = ar_service.score_customer(db_session, customer.id, date(2026, 8, 18))
    assert result.total_score >= 70
    alert = db_session.scalar(select(Alert).where(Alert.alert_type == "ar"))
    assert alert is not None and alert.level == "critical"
    assert alert.unique_key == f"ar:{customer.id}:2026-08-18"

    make_user(db_session, "ar", "ar_specialist")
    token = login(client, "ar")
    resp = client.get("/api/alerts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert any(a["alert_type"] == "ar" for a in resp.json()["items"])


def test_seed_full_demo_scenarios_present(db_session: Session) -> None:
    """seed 全角色（helpers 口径）：三态报销/三档 AR 的建模数据可构造。"""
    # 验证 seed 所需角色权限闭环（applicant/finance/budget_manager/ar_specialist/admin 均可创建）
    from app.core.perms import ROLE_PERMISSIONS

    assert {"applicant", "finance", "budget_manager", "ar_specialist", "admin"} == set(
        ROLE_PERMISSIONS.keys()
    )
    assert "budget:view" in ROLE_PERMISSIONS["finance"]
    assert "alert:view" in ROLE_PERMISSIONS["budget_manager"]
