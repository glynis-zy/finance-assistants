# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""预算管理接口测试（docs/api.md §3）：年度创建 / 曲线校验 / 冲突 / 调整留痕 / 权限。"""

from decimal import Decimal

from app.models.base_data import Budget, BudgetAdjustment
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.helpers import BaseData, login, make_user, seed_base

CURVE = [0.1] * 8 + [0.05] * 4  # 12 项，合计 1.0


def _bm_token(client: TestClient, db_session: Session) -> str:
    make_user(db_session, "bm", "budget_manager")
    return login(client, "bm")


def _payload(
    base: BaseData, year: str = "2027", curve: list[float] | None = None
) -> dict[str, object]:
    return {
        "department_id": base.dept.id,
        "project_id": base.proj.id,
        "cost_category_id": base.travel.id,
        "budget_year": year,
        "amount": "1200000.00",
        "allocation_curve": curve if curve is not None else CURVE,
    }


def test_create_year_budget(client: TestClient, db_session: Session) -> None:
    """1. 年度预算创建（budget_year + 曲线）。"""
    base = seed_base(db_session)
    token = _bm_token(client, db_session)
    resp = client.post(
        "/api/budgets", json=_payload(base), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["budget_year"] == "2027"
    assert body["amount"] == "1200000.00"
    row = db_session.get(Budget, body["budget_id"])
    assert row is not None and row.budget_year == "2027"


def test_allocation_curve_length_rejected(client: TestClient, db_session: Session) -> None:
    """2. allocation_curve 非 12 项拒绝（422）。"""
    base = seed_base(db_session)
    token = _bm_token(client, db_session)
    resp = client.post(
        "/api/budgets",
        json=_payload(base, curve=[0.1] * 11),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


def test_allocation_curve_sum_rejected(client: TestClient, db_session: Session) -> None:
    """3. allocation_curve 合计不为 1 拒绝（422）。"""
    base = seed_base(db_session)
    token = _bm_token(client, db_session)
    resp = client.post(
        "/api/budgets",
        json=_payload(base, curve=[0.2] * 12),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


def test_duplicate_budget_conflict(client: TestClient, db_session: Session) -> None:
    """4. 同维度同年度重复创建 → 409 RESOURCE_CONFLICT。"""
    base = seed_base(db_session)
    token = _bm_token(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/budgets", json=_payload(base), headers=headers)
    assert resp.status_code == 201, resp.text
    resp2 = client.post("/api/budgets", json=_payload(base), headers=headers)
    assert resp2.status_code == 409, resp2.text
    assert resp2.json()["code"] == "RESOURCE_CONFLICT"


def test_adjust_budget_keeps_trail(client: TestClient, db_session: Session) -> None:
    """5. 预算调整留痕（BudgetAdjustment + audit_log）。"""
    base = seed_base(db_session)
    token = _bm_token(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/api/budgets", json=_payload(base), headers=headers)
    budget_id = created.json()["budget_id"]
    resp = client.put(
        f"/api/budgets/{budget_id}",
        json={"amount": "1300000.00", "reason": "下半年扩编"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["amount"] == "1300000.00"
    assert body["adjustment_id"] is not None
    adj = db_session.get(BudgetAdjustment, body["adjustment_id"])
    assert adj is not None
    assert adj.before_amount == Decimal("1200000.00")
    assert adj.after_amount == Decimal("1300000.00")
    assert adj.reason == "下半年扩编"
    # audit_log 落库
    from app.models.base_data import AuditLog

    log = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "budget.adjust").order_by(AuditLog.id.desc())
    )
    assert log is not None and log.object_id == str(budget_id)


def test_budget_list_filter(client: TestClient, db_session: Session) -> None:
    """预算列表 + 年度过滤（year_from/year_to）。"""
    base = seed_base(db_session)
    token = _bm_token(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/budgets", json=_payload(base, year="2027"), headers=headers)
    resp = client.get(
        "/api/budgets?year_from=2027&year_to=2027",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["budget_year"] == "2027"


def test_budget_manage_permission(client: TestClient, db_session: Session) -> None:
    """27. 仅 budget:manage 可管理预算；applicant 403。"""
    base = seed_base(db_session)
    make_user(db_session, "app", "applicant")
    token = login(client, "app")
    resp = client.post(
        "/api/budgets", json=_payload(base), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403, resp.text
