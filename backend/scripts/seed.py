"""seed 初始化脚本。

灌入用户 / 角色 / 权限 / 角色权限关系 / 部门 / 项目 / 费用科目 / 必要系统参数 /
演示年度预算与台账 / 演示客户合同应收付款催收（覆盖高中低风险），并触发一次
预算监控与应收评分。幂等：已存在则跳过。演示密码仅用于本地演示。
"""

from datetime import UTC, date, datetime
from typing import TypedDict

import app.models  # noqa: F401  # type: ignore
from app.core.perms import ROLE_PERMISSIONS
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.ar_domain import ArPayment, ArReceivable, CollectionRecord
from app.models.base_data import (
    Budget,
    Contract,
    CostCategory,
    Customer,
    ExpenseLedger,
    OrgDepartment,
    Project,
    SysParam,
)
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
        "key": "threshold.budget.level_low",
        "value": "0.05",
        "value_type": "float",
        "description": "偏差等级 low 上界（<5% low）",
    },
    {
        "key": "threshold.budget.level_high",
        "value": "0.20",
        "value_type": "float",
        "description": "偏差等级 high 下界（>20% high）",
    },
    {
        "key": "threshold.budget.growth_mom",
        "value": "0.30",
        "value_type": "float",
        "description": "环比增幅阈值",
    },
    {
        "key": "threshold.budget.growth_yoy",
        "value": "0.50",
        "value_type": "float",
        "description": "同比增幅阈值",
    },
    {
        "key": "threshold.budget.signal_consecutive",
        "value": "2",
        "value_type": "int",
        "description": "统计信号连续期数升级阈值",
    },
    {
        "key": "threshold.budget.ewma_lambda",
        "value": "0.30",
        "value_type": "float",
        "description": "EWMA 平滑系数",
    },
    {
        "key": "threshold.budget.ewma_delta",
        "value": "0.30",
        "value_type": "float",
        "description": "EWMA 触发偏差阈值",
    },
    {
        "key": "threshold.budget.cusum_h",
        "value": "0.10",
        "value_type": "float",
        "description": "CUSUM 触发阈值（占年度预算比例）",
    },
    {
        "key": "threshold.budget.mad_z",
        "value": "3.0",
        "value_type": "float",
        "description": "MAD 修正 Z-score 离群阈值",
    },
    {
        "key": "threshold.budget.over_budget",
        "value": "0.20",
        "value_type": "float",
        "description": "超预算判定阈值（保留兼容）",
    },
    {
        "key": "threshold.ar.high_score",
        "value": "70",
        "value_type": "int",
        "description": "高风险分数阈值",
    },
    {
        "key": "threshold.ar.term_cap_days",
        "value": "120",
        "value_type": "int",
        "description": "账期因子归一上限（天）",
    },
    {
        "key": "threshold.ar.history_delay_cap_days",
        "value": "90",
        "value_type": "int",
        "description": "历史回款延迟归一上限（天）",
    },
    {
        "key": "threshold.ar.w_aging",
        "value": "0.4",
        "value_type": "float",
        "description": "评分权重：账龄",
    },
    {
        "key": "threshold.ar.w_term",
        "value": "0.2",
        "value_type": "float",
        "description": "评分权重：账期",
    },
    {
        "key": "threshold.ar.w_payment",
        "value": "0.3",
        "value_type": "float",
        "description": "评分权重：历史付款",
    },
    {
        "key": "threshold.ar.w_collection",
        "value": "0.1",
        "value_type": "float",
        "description": "评分权重：催收记录",
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

    # 演示年度预算（销售部 TRAVEL 120 万 / 研发部 TRAVEL 50 万，含 12 个月分摊曲线）
    curve = [0.1] * 8 + [0.05] * 4  # 12 项合计 1
    demo_budgets: list[dict[str, object]] = [
        {
            "department_code": "SALES",
            "project_code": "PJ-HD",
            "category_code": "TRAVEL",
            "budget_year": "2026",
            "amount": "1200000.00",
            "curve": curve,
        },
        {
            "department_code": "RND",
            "project_code": "PJ-XC",
            "category_code": "TRAVEL",
            "budget_year": "2026",
            "amount": "500000.00",
            "curve": curve,
        },
    ]
    db.flush()  # 确保部门/项目/科目已持久化，供演示预算/台账引用
    dept_by_code = {d.code: d for d in db.scalars(select(OrgDepartment)).all()}
    proj_by_code = {p.code: p for p in db.scalars(select(Project)).all()}
    cat_by_code = {c.code: c for c in db.scalars(select(CostCategory)).all()}
    for item in demo_budgets:
        exists = db.scalar(
            select(Budget.id).where(
                Budget.department_id == dept_by_code[str(item["department_code"])].id,
                Budget.project_id == proj_by_code[str(item["project_code"])].id,
                Budget.cost_category_id == cat_by_code[str(item["category_code"])].id,
                Budget.budget_year == str(item["budget_year"]),
            )
        )
        if exists is None:
            db.add(
                Budget(
                    department_id=dept_by_code[str(item["department_code"])].id,
                    project_id=proj_by_code[str(item["project_code"])].id,
                    cost_category_id=cat_by_code[str(item["category_code"])].id,
                    budget_year=str(item["budget_year"]),
                    amount=item["amount"],  # type: ignore[arg-type]
                    allocation_curve=item["curve"],
                )
            )

    # 演示台账：销售部 TRAVEL 2026-01~06 每月 10 万（累计 60 万 = 计划 60 万，验证不误报进度异常）
    sales_dept = dept_by_code["SALES"]
    pj_hd = proj_by_code["PJ-HD"]
    travel = cat_by_code["TRAVEL"]
    for month in range(1, 7):
        ref_no = f"SEED-BUDGET-2026-{month:02d}"
        exists = db.scalar(select(ExpenseLedger.id).where(ExpenseLedger.ref_no == ref_no))
        if exists is None:
            db.add(
                ExpenseLedger(
                    source="import",
                    cost_category_id=travel.id,
                    department_id=sales_dept.id,
                    project_id=pj_hd.id,
                    period=f"2026-{month:02d}",
                    amount="100000.00",
                    occurred_at=datetime(2026, month, 15, tzinfo=UTC),
                    ref_no=ref_no,
                )
            )

    # 演示应收数据（客户/合同/应收/付款/催收，覆盖高中低三档风险）
    demo_customers: list[dict[str, str]] = [
        {"code": "CUS-A", "name": "某某科技有限公司"},
        {"code": "CUS-B", "name": "某某信息技术有限公司"},
        {"code": "CUS-C", "name": "某某贸易有限公司"},
    ]
    customer_objs: dict[str, Customer] = {}
    for c in demo_customers:
        obj = db.scalar(select(Customer).where(Customer.code == c["code"]))
        if obj is None:
            obj = Customer(code=c["code"], name=c["name"], rating="A", credit=None)
            db.add(obj)
            db.flush()
        customer_objs[c["code"]] = obj

    demo_contracts: list[dict[str, object]] = [
        {"no": "HT-A-001", "customer": "CUS-A", "amount": "500000.00", "term": 30},
        {"no": "HT-B-001", "customer": "CUS-B", "amount": "300000.00", "term": 45},
        {"no": "HT-C-001", "customer": "CUS-C", "amount": "100000.00", "term": 30},
    ]
    contract_objs: dict[str, Contract] = {}
    for ct in demo_contracts:
        obj = db.scalar(select(Contract).where(Contract.contract_no == str(ct["no"])))
        if obj is None:
            obj = Contract(
                contract_no=str(ct["no"]),
                customer_id=customer_objs[str(ct["customer"])].id,
                amount=ct["amount"],  # type: ignore[arg-type]
                payment_term=int(ct["term"]),  # type: ignore[arg-type]
                status="executing",
            )
            db.add(obj)
            db.flush()
        contract_objs[str(ct["no"])] = obj

    # 应收：A 高风险（逾期 200+ 未结 + 历史逾期结清 + 催收后未回款）
    #       B 中风险（逾期 ~48 天未结 + 历史逾期结清）
    #       C 低风险（全部结清，无未结）
    demo_receivables: list[dict[str, object]] = [
        {"inv": "FP-A-001", "contract": "HT-A-001", "amount": "100000.00", "due": "2025-12-01"},
        {"inv": "FP-A-002", "contract": "HT-A-001", "amount": "200000.00", "due": "2026-01-01"},
        {"inv": "FP-B-001", "contract": "HT-B-001", "amount": "150000.00", "due": "2026-07-01"},
        {"inv": "FP-B-002", "contract": "HT-B-001", "amount": "80000.00", "due": "2026-06-01"},
        {"inv": "FP-C-001", "contract": "HT-C-001", "amount": "50000.00", "due": "2026-05-01"},
    ]
    rec_objs: dict[str, ArReceivable] = {}
    for r in demo_receivables:
        obj = db.scalar(select(ArReceivable).where(ArReceivable.invoice_no == str(r["inv"])))
        if obj is None:
            obj = ArReceivable(
                customer_id=contract_objs[str(r["contract"])].customer_id,
                contract_id=contract_objs[str(r["contract"])].id,
                invoice_no=str(r["inv"]),
                amount=r["amount"],  # type: ignore[arg-type]
                due_date=date.fromisoformat(str(r["due"])),
                status="open",
            )
            db.add(obj)
            db.flush()
        rec_objs[str(r["inv"])] = obj

    demo_payments: list[dict[str, object]] = [
        {"inv": "FP-A-001", "amount": "100000.00", "at": "2026-01-30T00:00:00Z"},
        {"inv": "FP-B-002", "amount": "80000.00", "at": "2026-07-01T00:00:00Z"},
        {"inv": "FP-C-001", "amount": "50000.00", "at": "2026-05-10T00:00:00Z"},
    ]
    for p in demo_payments:
        rec = rec_objs[str(p["inv"])]
        exists = db.scalar(
            select(ArPayment.id).where(
                ArPayment.receivable_id == rec.id, ArPayment.amount == p["amount"]
            )
        )
        if exists is None:
            db.add(
                ArPayment(
                    receivable_id=rec.id,
                    customer_id=rec.customer_id,
                    amount=p["amount"],  # type: ignore[arg-type]
                    received_at=datetime.fromisoformat(str(p["at"]).replace("Z", "+00:00")),
                )
            )
            # 结清后状态置 settled（演示数据直接定态）
            if rec.invoice_no in ("FP-A-001", "FP-B-002", "FP-C-001"):
                rec.status = "settled"

    demo_collections: list[dict[str, object]] = [
        {
            "customer": "CUS-A",
            "channel": "电话",
            "result": "承诺回款",
            "at": "2026-08-01T00:00:00Z",
        },
    ]
    for c in demo_collections:
        cust = customer_objs[str(c["customer"])]
        exists = db.scalar(
            select(CollectionRecord.id).where(
                CollectionRecord.customer_id == cust.id,
                CollectionRecord.occurred_at
                == datetime.fromisoformat(str(c["at"]).replace("Z", "+00:00")),
            )
        )
        if exists is None:
            db.add(
                CollectionRecord(
                    customer_id=cust.id,
                    channel=str(c["channel"]),
                    result=str(c["result"]),
                    occurred_at=datetime.fromisoformat(str(c["at"]).replace("Z", "+00:00")),
                )
            )

    db.commit()


def main() -> None:
    """建表 + 灌种子数据 + 触发一次监控与评分。"""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
        # 触发一次应收全量评分（幂等；仅演示链路可用，异常不阻断 seed）
        try:
            from app.services import ar_service

            summary = ar_service.score_all(db, datetime.now(UTC).date())
            print(f"应收评分完成：{summary}")
        except Exception as exc:  # noqa: BLE001 - seed 演示链路不阻断
            print(f"应收评分跳过：{exc}")
    print("seed 完成")


if __name__ == "__main__":
    main()
