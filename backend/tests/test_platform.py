# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""平台共享接口测试（Stage 5）：预警权限域过滤 / 已读 / 基础数据 / 台账 / 用户角色 / 静态页。"""

from app.models.alert import Alert
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import login, make_user, seed_base


def _tokens(client: TestClient, db_session: Session) -> dict[str, str]:
    """创建各角色用户并返回 token。"""
    for username, role in [
        ("app", "applicant"),
        ("fin", "finance"),
        ("bm", "budget_manager"),
        ("ar", "ar_specialist"),
        ("adm", "admin"),
    ]:
        make_user(db_session, username, role)
    return {
        r: login(client, u)
        for u, r in [("app", "app"), ("fin", "fin"), ("bm", "bm"), ("ar", "ar"), ("adm", "adm")]
    }


def _seed_alerts(db_session: Session) -> None:
    """budget + ar 各一条预警。"""
    db_session.add(
        Alert(
            alert_type="budget",
            level="critical",
            unique_key="budget:2026-06:1",
            summary="预算高偏差",
        )
    )
    db_session.add(
        Alert(alert_type="ar", level="critical", unique_key="ar:1:2026-08-18", summary="应收高风险")
    )
    db_session.commit()


def test_alerts_applicant_forbidden(client: TestClient, db_session: Session) -> None:
    """applicant 无 alert:view → 403。"""
    tokens = _tokens(client, db_session)
    resp = client.get("/api/alerts", headers={"Authorization": f"Bearer {tokens['app']}"})
    assert resp.status_code == 403, resp.text


def test_alerts_domain_filter(client: TestClient, db_session: Session) -> None:
    """域过滤：finance/budget_manager 见 budget；finance/ar_specialist 见 ar；admin 全量。"""
    _seed_alerts(db_session)
    tokens = _tokens(client, db_session)
    for user, expected_types in [
        ("fin", {"budget", "ar"}),  # finance 双域
        ("bm", {"budget"}),
        ("ar", {"ar"}),
        ("adm", {"budget", "ar"}),
    ]:
        resp = client.get("/api/alerts", headers={"Authorization": f"Bearer {tokens[user]}"})
        assert resp.status_code == 200, resp.text
        types = {item["alert_type"] for item in resp.json()["items"]}
        assert types == expected_types, f"{user}: {types}"


def test_alerts_filter_by_type_and_read(client: TestClient, db_session: Session) -> None:
    """alert_type/read 过滤。"""
    _seed_alerts(db_session)
    tokens = _tokens(client, db_session)
    resp = client.get(
        "/api/alerts?alert_type=budget&read=false",
        headers={"Authorization": f"Bearer {tokens['adm']}"},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1 and items[0]["alert_type"] == "budget" and items[0]["read"] is False


def test_alert_mark_read_domain_scoped(client: TestClient, db_session: Session) -> None:
    """标记已读：域内可标记；跨域 403；幂等。"""
    _seed_alerts(db_session)
    tokens = _tokens(client, db_session)
    budget = db_session.query(Alert).filter(Alert.alert_type == "budget").first()
    ar_alert = db_session.query(Alert).filter(Alert.alert_type == "ar").first()
    assert budget is not None and ar_alert is not None
    budget_id = budget.id
    ar_id = ar_alert.id

    # ar_specialist 不能标记 budget 预警（跨域）
    resp = client.post(
        f"/api/alerts/{budget_id}/read", headers={"Authorization": f"Bearer {tokens['ar']}"}
    )
    assert resp.status_code == 403, resp.text
    # finance 可标记 budget；ar_specialist 可标记 ar
    resp = client.post(
        f"/api/alerts/{budget_id}/read", headers={"Authorization": f"Bearer {tokens['fin']}"}
    )
    assert resp.status_code == 200 and resp.json()["read"] is True
    resp = client.post(
        f"/api/alerts/{ar_id}/read", headers={"Authorization": f"Bearer {tokens['ar']}"}
    )
    assert resp.status_code == 200 and resp.json()["read"] is True
    # 幂等
    resp = client.post(
        f"/api/alerts/{budget_id}/read", headers={"Authorization": f"Bearer {tokens['fin']}"}
    )
    assert resp.status_code == 200 and resp.json()["read"] is True


def test_base_data_endpoints(client: TestClient, db_session: Session) -> None:
    """基础数据接口（登录即可 / ar:view）。"""
    seed_base(db_session)
    tokens = _tokens(client, db_session)
    headers = {"Authorization": f"Bearer {tokens['app']}"}
    assert client.get("/api/departments", headers=headers).status_code == 200
    assert client.get("/api/projects", headers=headers).status_code == 200
    resp = client.get("/api/cost-categories", headers=headers)
    assert resp.status_code == 200 and len(resp.json()) >= 2
    # customers/contracts 需 ar:view
    assert client.get("/api/customers", headers=headers).status_code == 403
    ar_headers = {"Authorization": f"Bearer {tokens['ar']}"}
    assert client.get("/api/customers", headers=ar_headers).status_code == 200
    assert client.get("/api/contracts", headers=ar_headers).status_code == 200


def test_ledger_query_and_import(client: TestClient, db_session: Session) -> None:
    """台账查询（ledger:view）+ CSV 导入（ledger:import，幂等）。"""
    base = seed_base(db_session)
    tokens = _tokens(client, db_session)
    fin_headers = {"Authorization": f"Bearer {tokens['fin']}"}
    resp = client.get("/api/ledger", headers=fin_headers)
    assert resp.status_code == 200, resp.text

    csv_content = (
        "cost_category_code,department_code,project_code,period,amount,occurred_at,ref_no\n"
        f"{base.travel.code},{base.dept.code},{base.proj.code},2026-07,5000.00,2026-07-15T00:00:00Z,E2E-IMP-001\n"
    )
    resp = client.post(
        "/api/ledger/import",
        headers={"Authorization": f"Bearer {tokens['fin']}"},
        files={"file": ("ledger.csv", csv_content.encode("utf-8"), "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["imported_count"] == 1
    # 幂等：同 ref_no 再导入不重复
    resp2 = client.post(
        "/api/ledger/import",
        headers={"Authorization": f"Bearer {tokens['fin']}"},
        files={"file": ("ledger.csv", csv_content.encode("utf-8"), "text/csv")},
    )
    assert resp2.json()["imported_count"] == 0
    # applicant 无 ledger:view
    resp3 = client.get("/api/ledger", headers={"Authorization": f"Bearer {tokens['app']}"})
    assert resp3.status_code == 403


def test_users_roles_endpoints(client: TestClient, db_session: Session) -> None:
    """用户/角色接口（user:manage / role:manage）。"""
    tokens = _tokens(client, db_session)
    adm = {"Authorization": f"Bearer {tokens['adm']}"}
    app = {"Authorization": f"Bearer {tokens['app']}"}
    assert client.get("/api/users", headers=adm).status_code == 200
    assert client.get("/api/roles", headers=adm).status_code == 200
    assert client.get("/api/users", headers=app).status_code == 403

    resp = client.post(
        "/api/users",
        json={"username": "li.si", "name": "李四", "password": "123456", "roles": ["finance"]},
        headers=adm,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["roles"] == ["finance"]
    # 用户名重复 → 409
    resp2 = client.post(
        "/api/users",
        json={"username": "li.si", "name": "李四2", "password": "123456", "roles": ["finance"]},
        headers=adm,
    )
    assert resp2.status_code == 409


def test_index_and_static_assets(client: TestClient, db_session: Session) -> None:
    """FastAPI 静态首页与静态资源可访问（未登录）。"""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "财务智能助手平台" in resp.text
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_unauth_api_returns_401(client: TestClient, db_session: Session) -> None:
    """未登录访问受保护 API → 401。"""
    for path in ["/api/reimbursements", "/api/budgets", "/api/ar/risk-ranking", "/api/alerts"]:
        resp = client.get(path)
        assert resp.status_code == 401, f"{path}: {resp.status_code}"
