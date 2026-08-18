# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""系统参数与权限收口测试（L1 + threshold.* 规则）。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import login, make_param, make_user


def test_list_params_requires_sys_manage(client: TestClient, db_session: Session) -> None:
    make_user(db_session, "zhang", "applicant")
    token = login(client, "zhang")
    resp = client.get("/api/sys-params", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


def test_list_params_admin_ok(client: TestClient, db_session: Session) -> None:
    make_user(db_session, "admin", "admin", "admin123")
    make_param(db_session, "threshold.reimb.date_window_days", "180")
    token = login(client, "admin", "admin123")
    resp = client.get("/api/sys-params", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert any(p["key"] == "threshold.reimb.date_window_days" for p in resp.json())


def test_threshold_key_editable_by_threshold_manage(
    client: TestClient, db_session: Session
) -> None:
    make_user(db_session, "budget", "budget_manager")
    make_param(db_session, "threshold.budget.progress_gap", "0.15")
    token = login(client, "budget")
    resp = client.put(
        "/api/sys-params/threshold.budget.progress_gap",
        json={"value": "0.20"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "0.20"


def test_non_threshold_key_requires_sys_manage(client: TestClient, db_session: Session) -> None:
    make_user(db_session, "budget", "budget_manager")
    make_param(db_session, "schedule.budget_monitor", "0 0 8 * * *")
    token = login(client, "budget")
    resp = client.put(
        "/api/sys-params/schedule.budget_monitor",
        json={"value": "0 0 9 * * *"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
