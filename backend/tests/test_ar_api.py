# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportOptionalMemberAccess=false, reportAttributeAccessIssue=false, reportFunctionMemberAccess=false, reportUnusedVariable=false, reportMissingParameterType=false
"""应收接口与集成测试（22-32 项验收）。"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.alert import Alert
from app.models.ar_domain import ArPayment, ArReceivable, ArRiskRun, ArRiskScore, CollectionRecord
from app.models.base_data import Contract, Customer, SysParam
from app.services import ar_service
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.helpers import login, make_user

TODAY = datetime.now(UTC).date()


def _seed_customer(
    db: Session, code: str = "CUS-1", name: str = "测试客户"
) -> tuple[Customer, Contract]:
    customer = Customer(code=code, name=name)
    db.add(customer)
    db.flush()
    contract = Contract(
        contract_no=f"HT-{code}",
        customer_id=customer.id,
        amount=Decimal("500000.00"),
        payment_term=30,
    )
    db.add(contract)
    db.commit()
    return customer, contract


def _ar_token(client: TestClient, db_session: Session) -> str:
    make_user(db_session, "ar", "ar_specialist")
    return login(client, "ar")


def _create_receivable(
    client: TestClient,
    token: str,
    customer_id: int,
    contract_id: int,
    amount: str = "1000.00",
    due: date | None = None,
) -> int:
    resp = client.post(
        "/api/ar/receivables",
        json={
            "customer_id": customer_id,
            "contract_id": contract_id,
            "invoice_no": f"FP-{customer_id}-{amount}",
            "amount": amount,
            "due_date": (due or TODAY).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["id"])


def _high_risk_customer(db: Session) -> tuple[Customer, Contract, int]:
    """构造高风险客户：未结逾期 200 天 + 历史逾期结清 + 催收后未回款 → total 86。"""
    customer, contract = _seed_customer(db, "CUS-H", "高风险客户")
    settled = ArReceivable(
        customer_id=customer.id,
        contract_id=contract.id,
        invoice_no="FP-H-1",
        amount=Decimal("100000.00"),
        due_date=date(2025, 12, 1),
        status="settled",
    )
    db.add(settled)
    db.flush()
    db.add(
        ArPayment(
            receivable_id=settled.id,
            customer_id=customer.id,
            amount=Decimal("100000.00"),
            received_at=datetime(2026, 1, 30, tzinfo=UTC),
        )
    )
    open_rec = ArReceivable(
        customer_id=customer.id,
        contract_id=contract.id,
        invoice_no="FP-H-2",
        amount=Decimal("200000.00"),
        due_date=date(2026, 1, 1),
        status="open",
    )
    db.add(open_rec)
    db.flush()
    db.add(
        CollectionRecord(
            customer_id=customer.id,
            channel="电话",
            result="承诺回款",
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    db.commit()
    return customer, contract, open_rec.id


def test_create_receivable_default_open(client: TestClient, db_session: Session) -> None:
    """1. 创建应收默认 open。"""
    customer, contract = _seed_customer(db_session)
    token = _ar_token(client, db_session)
    rid = _create_receivable(client, token, customer.id, contract.id)
    row = db_session.get(ArReceivable, rid)
    assert row is not None and row.status == "open"


def test_contract_customer_mismatch_rejected(client: TestClient, db_session: Session) -> None:
    """2. contract 与 customer 不匹配拒绝。"""
    customer, _ = _seed_customer(db_session, "CUS-A")
    other, other_contract = _seed_customer(db_session, "CUS-B")
    token = _ar_token(client, db_session)
    resp = client.post(
        "/api/ar/receivables",
        json={
            "customer_id": customer.id,
            "contract_id": other_contract.id,
            "amount": "1000.00",
            "due_date": TODAY.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


def test_partial_payment_status(client: TestClient, db_session: Session) -> None:
    """3. 部分回款 → partial。"""
    customer, contract = _seed_customer(db_session)
    token = _ar_token(client, db_session)
    rid = _create_receivable(client, token, customer.id, contract.id, amount="1000.00")
    resp = client.post(
        "/api/ar/payments",
        json={"receivable_id": rid, "customer_id": customer.id, "amount": "400.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert db_session.get(ArReceivable, rid).status == "partial"


def test_full_payment_settled(client: TestClient, db_session: Session) -> None:
    """4. 全额回款 → settled。"""
    customer, contract = _seed_customer(db_session)
    token = _ar_token(client, db_session)
    rid = _create_receivable(client, token, customer.id, contract.id, amount="1000.00")
    client.post(
        "/api/ar/payments",
        json={"receivable_id": rid, "customer_id": customer.id, "amount": "1000.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert db_session.get(ArReceivable, rid).status == "settled"


def test_over_payment_rejected(client: TestClient, db_session: Session) -> None:
    """5. 超额回款拒绝。"""
    customer, contract = _seed_customer(db_session)
    token = _ar_token(client, db_session)
    rid = _create_receivable(client, token, customer.id, contract.id, amount="1000.00")
    resp = client.post(
        "/api/ar/payments",
        json={"receivable_id": rid, "customer_id": customer.id, "amount": "1500.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


def test_receivable_overdue_days_api(client: TestClient, db_session: Session) -> None:
    """6. overdue_days 正确（API 列表）。"""
    customer, contract = _seed_customer(db_session)
    token = _ar_token(client, db_session)
    due = TODAY - timedelta(days=30)
    _create_receivable(client, token, customer.id, contract.id, due=due)
    resp = client.get(
        f"/api/ar/receivables?customer_id={customer.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["overdue_days"] == 30
    assert items[0]["status"] == "open"


def test_high_risk_ranking(client: TestClient, db_session: Session) -> None:
    """22/23. high risk 排名 + overdue_amount。"""
    customer, _, _ = _high_risk_customer(db_session)
    ar_service.score_customer(db_session, customer.id, TODAY)
    token = _ar_token(client, db_session)
    resp = client.get("/api/ar/risk-ranking", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["customer_id"] == customer.id
    assert items[0]["risk_score"] >= 70
    assert items[0]["overdue_amount"] == "200000.00"
    assert items[0]["collection_priority"] == 1


def test_high_risk_alert_and_idempotent(client: TestClient, db_session: Session) -> None:
    """24/25. high risk 创建 alert；重复评分不重复 alert。"""
    customer, _, _ = _high_risk_customer(db_session)
    ar_service.score_customer(db_session, customer.id, TODAY)
    ar_service.score_customer(db_session, customer.id, TODAY)
    alerts = list(db_session.scalars(select(Alert).where(Alert.alert_type == "ar")).all())
    assert len(alerts) == 1
    assert alerts[0].level == "critical"
    assert alerts[0].unique_key == f"ar:{customer.id}:{TODAY.isoformat()}"


def test_same_day_upsert(db_session: Session) -> None:
    """26. 同日评分 upsert（每客户每日一条）。"""
    customer, _, _ = _high_risk_customer(db_session)
    ar_service.score_customer(db_session, customer.id, TODAY)
    ar_service.score_customer(db_session, customer.id, TODAY)
    count = db_session.scalar(
        select(func.count()).select_from(ArRiskScore).where(ArRiskScore.customer_id == customer.id)
    )
    assert count == 1


def test_payment_triggers_rescore(
    client: TestClient, db_session: Session, monkeypatch: object
) -> None:
    """27. 登记回款后触发单客户重算。"""
    customer, contract = _seed_customer(db_session)
    token = _ar_token(client, db_session)
    rid = _create_receivable(client, token, customer.id, contract.id, amount="1000.00")

    calls: list[int] = []
    original = ar_service.score_customer

    def spy(db: Session, customer_id: int, score_date: date | None = None) -> object:
        calls.append(customer_id)
        return original(db, customer_id, score_date)

    monkeypatch.setattr(ar_service, "score_customer", spy)
    resp = client.post(
        "/api/ar/payments",
        json={"receivable_id": rid, "customer_id": customer.id, "amount": "1000.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert customer.id in calls


def test_collection_triggers_rescore(
    client: TestClient, db_session: Session, monkeypatch: object
) -> None:
    """28. 登记催收记录后触发单客户重算。"""
    customer, _ = _seed_customer(db_session)
    token = _ar_token(client, db_session)
    calls: list[int] = []
    original = ar_service.score_customer

    def spy(db: Session, customer_id: int, score_date: date | None = None) -> object:
        calls.append(customer_id)
        return original(db, customer_id, score_date)

    monkeypatch.setattr(ar_service, "score_customer", spy)
    resp = client.post(
        "/api/ar/collection-records",
        json={"customer_id": customer.id, "channel": "电话", "result": "承诺"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert customer.id in calls


def test_beat_full_scoring_and_status(client: TestClient, db_session: Session) -> None:
    """29/30. 全量评分任务（beat 链路）+ risk-status。"""
    _high_risk_customer(db_session)
    from app.tasks.ar import run_risk_task

    run_risk_task.delay(TODAY.isoformat())
    run = db_session.scalar(select(ArRiskRun).order_by(ArRiskRun.id.desc()).limit(1))
    assert run is not None and run.status == "done"
    assert run.customer_count >= 1
    assert run.high_risk_count >= 1

    token = _ar_token(client, db_session)
    resp = client.get("/api/ar/risk-status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done"
    assert body["high_risk_count"] >= 1


def test_ar_permissions(client: TestClient, db_session: Session) -> None:
    """31. ar:view / ar:manage 权限（applicant 403）。"""
    customer, _ = _seed_customer(db_session)
    make_user(db_session, "app", "applicant")
    app_token = login(client, "app")
    resp = client.get("/api/ar/risk-ranking", headers={"Authorization": f"Bearer {app_token}"})
    assert resp.status_code == 403, resp.text
    resp = client.post(
        "/api/ar/receivables",
        json={
            "customer_id": customer.id,
            "contract_id": 1,
            "amount": "100.00",
            "due_date": TODAY.isoformat(),
        },
        headers={"Authorization": f"Bearer {app_token}"},
    )
    assert resp.status_code == 403, resp.text
    # ar_specialist 可读
    ar_token = _ar_token(client, db_session)
    resp = client.get("/api/ar/risk-ranking", headers={"Authorization": f"Bearer {ar_token}"})
    assert resp.status_code == 200


def test_sys_param_weight_effective_next_round(db_session: Session) -> None:
    """32. sys_param 修改归一参数后下一轮生效（delay_cap 90→45）。"""
    customer, contract = _seed_customer(db_session, "CUS-W", "归一客户")
    settled = ArReceivable(
        customer_id=customer.id,
        contract_id=contract.id,
        invoice_no="FP-W-1",
        amount=Decimal("1000.00"),
        due_date=date(2026, 5, 1),
        status="settled",
    )
    db_session.add(settled)
    db_session.flush()
    from app.models.ar_domain import ArPayment

    db_session.add(
        ArPayment(
            receivable_id=settled.id,
            customer_id=customer.id,
            amount=Decimal("1000.00"),
            received_at=datetime(2026, 7, 1, tzinfo=UTC),  # 延迟 61 天
        )
    )
    db_session.commit()
    r1 = ar_service.score_customer(db_session, customer.id, TODAY)
    assert r1.factors["payment"].detail["delay_score"] == pytest.approx(
        round(61 / 90 * 100, 2)
    )  # 61 天

    param = db_session.scalar(
        select(SysParam).where(SysParam.key == "threshold.ar.history_delay_cap_days")
    )
    if param is None:
        param = SysParam(key="threshold.ar.history_delay_cap_days", value="60", value_type="int")
        db_session.add(param)
    else:
        param.value = "60"
    db_session.commit()
    r2 = ar_service.score_customer(db_session, customer.id, TODAY)
    assert r2.factors["payment"].detail["delay_score"] == pytest.approx(100.0)  # 61/60 归一满
    assert r2.factors["payment"].raw_score != r1.factors["payment"].raw_score
