# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""认证接口测试（登录 / me / 未认证 401）。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import login, make_user


def test_login_success(client: TestClient, db_session: Session) -> None:
    make_user(db_session, "admin", "admin", "admin123")
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "admin"
    assert "admin" in body["user"]["roles"]


def test_login_wrong_password(client: TestClient, db_session: Session) -> None:
    make_user(db_session, "zhang", "applicant")
    resp = client.post("/api/auth/login", json={"username": "zhang", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_me_requires_token(client: TestClient) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_user(client: TestClient, db_session: Session) -> None:
    make_user(db_session, "zhang", "applicant")
    token = login(client, "zhang")
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "zhang"
    assert "reimb:create" in body["permissions"]
