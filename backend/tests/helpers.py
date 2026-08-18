# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""测试辅助：用户、基础数据、报销单、附件、登录。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.core.perms import ROLE_PERMISSIONS
from app.core.security import hash_password
from app.models.base_data import (
    Attachment,
    Budget,
    CostCategory,
    FileStore,
    OrgDepartment,
    Project,
    SysParam,
)
from app.models.rbac import SysPermission, SysRole, SysUser
from app.models.reimbursement import ReimbursementAttachment
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass
class BaseData:
    """报销审核基础数据引用。"""

    dept: OrgDepartment
    proj: Project
    travel: CostCategory
    office: CostCategory
    period: str


def make_user(
    db: Session,
    username: str,
    role_code: str,
    password: str = "123456",
    name: str | None = None,
) -> SysUser:
    """创建指定角色用户（含角色权限）。"""
    role = db.scalar(select(SysRole).where(SysRole.code == role_code))
    if role is None:
        role = SysRole(code=role_code, name=role_code)
        db.add(role)
        db.flush()
    for perm_code in ROLE_PERMISSIONS.get(role_code, []):
        perm = db.scalar(select(SysPermission).where(SysPermission.code == perm_code))
        if perm is None:
            perm = SysPermission(code=perm_code, name=perm_code)
            db.add(perm)
            db.flush()
        if perm not in role.permissions:
            role.permissions.append(perm)
    user = SysUser(username=username, name=name or username, password_hash=hash_password(password))
    user.roles.append(role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login(client: TestClient, username: str, password: str = "123456") -> str:
    """登录并返回 access_token。"""
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def make_param(db: Session, key: str, value: str = "1") -> SysParam:
    """创建系统参数。"""
    param = SysParam(key=key, value=value, value_type="str", description=key)
    db.add(param)
    db.commit()
    db.refresh(param)
    return param


def seed_base(db: Session) -> BaseData:
    """创建报销审核基础数据：部门/项目/科目/参数/预算。"""
    dept = OrgDepartment(code="SALES", name="销售部", manager="王五")
    db.add(dept)
    db.flush()
    proj = Project(code="PJ-HD", name="华东大区", department_id=dept.id, owner="赵六")
    db.add(proj)
    db.flush()
    travel = CostCategory(code="TRAVEL", name="差旅费", keyword_map=["高铁", "机票", "差旅"])
    db.add(travel)
    db.flush()
    office = CostCategory(code="OFFICE", name="办公费", keyword_map=["办公"])
    db.add(office)
    db.flush()
    for key, value, vt in [
        ("threshold.reimb.date_window_days", "180", "int"),
        ("threshold.reimb.over_amount", "5000.00", "decimal"),
    ]:
        if db.scalar(select(SysParam).where(SysParam.key == key)) is None:
            db.add(SysParam(key=key, value=value, value_type=vt))
    period = datetime.now(UTC).strftime("%Y-%m")
    db.add(
        Budget(
            department_id=dept.id,
            project_id=proj.id,
            cost_category_id=travel.id,
            budget_year=period[:4],
            amount=Decimal("100000.00"),
        )
    )
    db.commit()
    return BaseData(dept=dept, proj=proj, travel=travel, office=office, period=period)


def add_attachment(db: Session, rid: int, category: str, uploaded_by: int | None = None) -> int:
    """DB 直接创建附件（FileStore + Attachment + 关联），返回 attachment_id。"""
    fs = FileStore(
        file_name=f"{category}.png",
        storage_path=f"uploads/test-{uuid4().hex}",
        mime_type="image/png",
        size=10,
    )
    db.add(fs)
    db.flush()
    att = Attachment(file_store_id=fs.id, category=category, uploaded_by=uploaded_by)
    db.add(att)
    db.flush()
    db.add(ReimbursementAttachment(reimbursement_id=rid, attachment_id=att.id))
    db.commit()
    return att.id


def create_reimb(
    client: TestClient,
    token: str,
    base: BaseData,
    *,
    total: str = "1000.00",
    invoice_key: str = "INV-000001",
    description: str = "差旅费-高铁票",
) -> int:
    """通过 API 创建差旅类报销单，返回 reimbursement id。"""
    resp = client.post(
        "/api/reimbursements",
        json={
            "department_id": base.dept.id,
            "project_id": base.proj.id,
            "total_amount": total,
            "items": [
                {
                    "cost_category_id": base.travel.id,
                    "amount": total,
                    "invoice_key": invoice_key,
                    "description": description,
                }
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["id"])


def upload_files(client: TestClient, token: str, rid: int, categories: list[str]) -> None:
    """通过 API 上传附件（multipart，files 与 categories 一一对应）。"""
    files = [("files", (f"{c}.png", b"fake", "image/png")) for c in categories]
    data = {"categories": categories}
    resp = client.post(
        f"/api/reimbursements/{rid}/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
        data=data,
    )
    assert resp.status_code == 201, resp.text


def submit(client: TestClient, token: str, rid: int) -> dict[str, object]:
    """提交审核并返回 JSON。"""
    resp = client.post(
        f"/api/reimbursements/{rid}/submit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text
    return resp.json()
