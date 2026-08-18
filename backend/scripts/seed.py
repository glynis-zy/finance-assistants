"""seed 初始化脚本。

灌入用户 / 角色 / 权限 / 角色权限关系 / 部门 / 项目 / 费用科目 / 必要系统参数。
幂等：已存在则跳过。演示密码仅用于本地演示。
"""

from typing import TypedDict

import app.models  # noqa: F401  # type: ignore
from app.core.perms import ROLE_PERMISSIONS
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.base_data import CostCategory, OrgDepartment, Project, SysParam
from app.models.rbac import SysPermission, SysRole, SysUser
from sqlalchemy import select
from sqlalchemy.orm import Session

ROLES: dict[str, str] = {
    "applicant": "报销申请人",
    "finance": "财务审核",
    "budget_manager": "预算管理员",
    "ar_specialist": "应收专员",
    "admin": "系统管理员",
}


class SeedUser(TypedDict):
    """seed 用户条目结构。"""

    username: str
    name: str
    password: str
    roles: list[str]


USERS: list[SeedUser] = [
    {"username": "admin", "name": "系统管理员", "password": "admin123", "roles": ["admin"]},
    {"username": "zhang.san", "name": "张三", "password": "123456", "roles": ["applicant"]},
    {"username": "finance.li", "name": "李财务", "password": "123456", "roles": ["finance"]},
    {
        "username": "budget.wang",
        "name": "王预算",
        "password": "123456",
        "roles": ["budget_manager"],
    },
    {"username": "ar.zhao", "name": "赵应收", "password": "123456", "roles": ["ar_specialist"]},
]

DEPARTMENTS: list[dict[str, str]] = [
    {"code": "SALES", "name": "销售部", "manager": "王五"},
    {"code": "RND", "name": "研发部", "manager": "钱七"},
    {"code": "FIN", "name": "财务部", "manager": "李财务"},
]

PROJECTS: list[dict[str, str]] = [
    {"code": "PJ-HD", "name": "华东大区", "department_code": "SALES", "owner": "赵六"},
    {"code": "PJ-XC", "name": "新产品研发", "department_code": "RND", "owner": "钱七"},
]

CATEGORIES: list[dict[str, object]] = [
    {"code": "TRAVEL", "name": "差旅费", "keywords": ["高铁", "机票", "打车", "住宿", "差旅"]},
    {"code": "OFFICE", "name": "办公费", "keywords": ["办公", "文具", "打印"]},
    {"code": "ENTERTAIN", "name": "业务招待费", "keywords": ["招待", "餐饮", "宴请"]},
    {"code": "MEETING", "name": "会议费", "keywords": ["会议", "场地"]},
]

PARAMS: list[dict[str, str]] = [
    {
        "key": "threshold.reimb.date_window_days",
        "value": "180",
        "value_type": "int",
        "description": "发票允许报销区间（天）",
    },
    {
        "key": "threshold.reimb.over_amount",
        "value": "5000.00",
        "value_type": "decimal",
        "description": "单笔报销超标标准（元）",
    },
    {
        "key": "threshold.budget.progress_gap",
        "value": "0.15",
        "value_type": "float",
        "description": "进度异常阈值",
    },
    {
        "key": "threshold.budget.over_budget",
        "value": "0.20",
        "value_type": "float",
        "description": "超预算判定阈值",
    },
    {
        "key": "threshold.ar.high_score",
        "value": "70",
        "value_type": "int",
        "description": "高风险分数阈值",
    },
    {
        "key": "schedule.budget_monitor",
        "value": "0 0 8 * * *",
        "value_type": "str",
        "description": "预算监控调度",
    },
    {
        "key": "schedule.ar_warning",
        "value": "0 30 8 * * *",
        "value_type": "str",
        "description": "应收预警调度",
    },
]


def seed(db: Session) -> None:
    """写入种子数据（幂等）。"""
    # 权限
    perm_objs: dict[str, SysPermission] = {}
    for perms in ROLE_PERMISSIONS.values():
        for code in perms:
            if code not in perm_objs:
                obj = db.scalar(select(SysPermission).where(SysPermission.code == code))
                if obj is None:
                    obj = SysPermission(code=code, name=code)
                    db.add(obj)
                    db.flush()
                perm_objs[code] = obj

    # 角色
    role_objs: dict[str, SysRole] = {}
    for code, name in ROLES.items():
        role = db.scalar(select(SysRole).where(SysRole.code == code))
        if role is None:
            role = SysRole(code=code, name=name)
            db.add(role)
            db.flush()
        role_objs[code] = role

    # 角色-权限关系
    for code, role in role_objs.items():
        for perm_code in ROLE_PERMISSIONS[code]:
            if perm_objs[perm_code] not in role.permissions:
                role.permissions.append(perm_objs[perm_code])

    # 用户
    for item in USERS:
        user = db.scalar(select(SysUser).where(SysUser.username == item["username"]))
        if user is None:
            user = SysUser(
                username=item["username"],
                name=item["name"],
                password_hash=hash_password(item["password"]),
            )
            db.add(user)
            db.flush()
        for role_code in item["roles"]:
            if role_objs[role_code] not in user.roles:
                user.roles.append(role_objs[role_code])

    # 部门
    dept_objs: dict[str, OrgDepartment] = {}
    for d in DEPARTMENTS:
        dept = db.scalar(select(OrgDepartment).where(OrgDepartment.code == d["code"]))
        if dept is None:
            dept = OrgDepartment(code=d["code"], name=d["name"], manager=d["manager"])
            db.add(dept)
            db.flush()
        dept_objs[d["code"]] = dept

    # 项目
    for p in PROJECTS:
        proj = db.scalar(select(Project).where(Project.code == p["code"]))
        if proj is None:
            proj = Project(
                code=p["code"],
                name=p["name"],
                department_id=dept_objs[p["department_code"]].id,
                owner=p["owner"],
            )
            db.add(proj)

    # 科目
    for c in CATEGORIES:
        cat = db.scalar(select(CostCategory).where(CostCategory.code == c["code"]))
        if cat is None:
            cat = CostCategory(
                code=str(c["code"]),
                name=str(c["name"]),
                keyword_map=c.get("keywords"),
            )
            db.add(cat)

    # 系统参数
    for p in PARAMS:
        param = db.scalar(select(SysParam).where(SysParam.key == p["key"]))
        if param is None:
            param = SysParam(
                key=p["key"],
                value=p["value"],
                value_type=p["value_type"],
                description=p["description"],
            )
            db.add(param)

    db.commit()


def main() -> None:
    """建表 + 灌种子数据。"""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    print("seed 完成")


if __name__ == "__main__":
    main()
