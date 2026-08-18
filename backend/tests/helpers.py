# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""测试辅助：创建用户、登录获取 token。"""

from app.core.perms import ROLE_PERMISSIONS
from app.core.security import hash_password
from app.models.base_data import SysParam
from app.models.rbac import SysPermission, SysRole, SysUser
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


def make_user(db: Session, username: str, role_code: str, password: str = "123456") -> SysUser:
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
    user = SysUser(username=username, name=username, password_hash=hash_password(password))
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
