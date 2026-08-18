"""报销合规规则（确定性，docs/requirements.md §4.2.4）。

每条规则纯函数：输入 `RuleContext`，输出可解释的 `RuleResult`。
uncertain（字段缺失/置信度低/无法判定）由上层 fail-closed 汇总为 manual_review。
"""

from datetime import date
from decimal import Decimal

from app.domain.risk_engine.types import RuleContext, RuleResult, RuleStatus
from app.models.enums import AlertLevel

_PASS = RuleStatus.PASSED.value
_FAIL = RuleStatus.FAILED.value
_UNCERTAIN = RuleStatus.UNCERTAIN.value
_INFO = AlertLevel.INFO.value
_WARN = AlertLevel.WARNING.value
_CRIT = AlertLevel.CRITICAL.value


def _threshold(ctx: RuleContext, key: str, default: str) -> str:
    return ctx.thresholds.get(key, default)


def _is_travel(ctx: RuleContext) -> bool:
    """是否差旅类报销（明细含 TRAVEL 科目）。"""
    travel_ids = {c.id for c in ctx.categories if c.code == "TRAVEL"}
    return any(i.cost_category_id in travel_ids for i in ctx.items)


# --------------------------------------------------------------------------- #
# 材料完整性
# --------------------------------------------------------------------------- #
def check_invoice_exists(ctx: RuleContext) -> RuleResult:
    """发票存在：至少 1 张有效发票。"""
    has_attachment = ctx.has_category_attachment("invoice")
    if not has_attachment:
        return RuleResult(
            "invoice_exists",
            "发票存在",
            _FAIL,
            _CRIT,
            "未上传发票附件",
            actual_value=0,
            expected_value=">= 1",
            threshold=1,
        )
    if ctx.has_low_confidence("invoice") or not ctx.invoices():
        return RuleResult(
            "invoice_exists",
            "发票存在",
            _UNCERTAIN,
            _WARN,
            "发票附件存在但解析失败或置信度低，无法确认有效性",
            actual_value="无法解析",
            expected_value="有效发票",
        )
    return RuleResult(
        "invoice_exists",
        "发票存在",
        _PASS,
        _INFO,
        "发票存在且解析成功",
        actual_value=len(ctx.invoices()),
        expected_value=">= 1",
        threshold=1,
    )


def check_travel_exists(ctx: RuleContext) -> RuleResult:
    """行程单存在：差旅类报销必须携带。"""
    if not _is_travel(ctx):
        return RuleResult(
            "travel_exists",
            "行程单存在",
            _PASS,
            _INFO,
            "非差旅类，不适用",
        )
    if not ctx.has_category_attachment("travel"):
        return RuleResult(
            "travel_exists",
            "行程单存在",
            _FAIL,
            _CRIT,
            "差旅类报销缺少行程单",
            actual_value="无",
            expected_value="行程单",
        )
    return RuleResult(
        "travel_exists",
        "行程单存在",
        _PASS,
        _INFO,
        "行程单已提供",
    )


def check_approval_exists(ctx: RuleContext) -> RuleResult:
    """审批单存在：差旅类报销必须携带。"""
    if not _is_travel(ctx):
        return RuleResult(
            "approval_exists",
            "审批单存在",
            _PASS,
            _INFO,
            "非差旅类，不适用",
        )
    if not ctx.has_category_attachment("approval"):
        return RuleResult(
            "approval_exists",
            "审批单存在",
            _FAIL,
            _CRIT,
            "差旅类报销缺少审批单",
            actual_value="无",
            expected_value="审批单",
        )
    return RuleResult(
        "approval_exists",
        "审批单存在",
        _PASS,
        _INFO,
        "审批单已提供",
    )


def check_amount_match(ctx: RuleContext) -> RuleResult:
    """金额一致：发票金额合计 = 报销金额。"""
    invoices = ctx.invoices()
    if not invoices:
        return RuleResult(
            "amount_match",
            "金额一致",
            _UNCERTAIN,
            _WARN,
            "发票金额无法解析，无法比对",
        )
    total = sum(i.amount for i in invoices)
    expected = ctx.reimbursement.total_amount
    if total != expected:
        return RuleResult(
            "amount_match",
            "金额一致",
            _FAIL,
            _CRIT,
            "发票金额合计与报销金额不一致",
            actual_value=str(total),
            expected_value=str(expected),
        )
    return RuleResult(
        "amount_match",
        "金额一致",
        _PASS,
        _INFO,
        "发票金额与报销金额一致",
        actual_value=str(total),
        expected_value=str(expected),
    )


def check_title_match(ctx: RuleContext) -> RuleResult:
    """抬头一致：发票购买方 = 本公司。"""
    invoices = ctx.invoices()
    if not invoices:
        return RuleResult(
            "title_match",
            "抬头一致",
            _UNCERTAIN,
            _WARN,
            "发票抬头无法解析，无法比对",
        )
    bad = [i.buyer_name for i in invoices if i.buyer_name != ctx.company_name]
    if bad:
        return RuleResult(
            "title_match",
            "抬头一致",
            _FAIL,
            _CRIT,
            "发票抬头与本公司不符",
            actual_value=bad[0],
            expected_value=ctx.company_name,
        )
    return RuleResult(
        "title_match",
        "抬头一致",
        _PASS,
        _INFO,
        "发票抬头与本公司一致",
        actual_value=ctx.company_name,
        expected_value=ctx.company_name,
    )


def check_date_valid(ctx: RuleContext) -> RuleResult:
    """日期合理：发票日期在允许报销区间（默认 180 天）内。"""
    invoices = ctx.invoices()
    if not invoices:
        return RuleResult(
            "date_valid",
            "日期合理",
            _UNCERTAIN,
            _WARN,
            "发票日期无法解析，无法比对",
        )
    window = int(_threshold(ctx, "threshold.reimb.date_window_days", "180"))
    today = date.today()
    expired = [i for i in invoices if (today - i.invoice_date).days > window]
    if expired:
        return RuleResult(
            "date_valid",
            "日期合理",
            _FAIL,
            _WARN,
            "发票日期超出允许报销区间",
            actual_value=str(expired[0].invoice_date),
            threshold=f"{window} 天",
        )
    return RuleResult(
        "date_valid",
        "日期合理",
        _PASS,
        _INFO,
        "发票日期在允许区间内",
        threshold=f"{window} 天",
    )


# --------------------------------------------------------------------------- #
# 财务合规
# --------------------------------------------------------------------------- #
def check_budget_within(ctx: RuleContext) -> RuleResult:
    """预算内：累计台账 + 本次拟报销 <= 预算。"""
    if not ctx.budget_checks:
        return RuleResult(
            "budget_within",
            "预算内",
            _UNCERTAIN,
            _WARN,
            "无对应预算记录，无法判定",
        )
    for bc in ctx.budget_checks:
        used = bc.ledger_amount + bc.item_amount
        if used > bc.budget_amount:
            return RuleResult(
                "budget_within",
                "预算内",
                _FAIL,
                _CRIT,
                "超出预算额度",
                actual_value=str(used),
                expected_value=str(bc.budget_amount),
            )
    return RuleResult(
        "budget_within",
        "预算内",
        _PASS,
        _INFO,
        "预算内",
    )


def check_category_valid(ctx: RuleContext) -> RuleResult:
    """科目合法：推荐科目存在且未停用。"""
    cat = ctx.recommended_category
    if cat is None:
        return RuleResult(
            "category_valid",
            "科目合法",
            _UNCERTAIN,
            _WARN,
            "未推荐出费用科目",
        )
    if not cat.enabled:
        return RuleResult(
            "category_valid",
            "科目合法",
            _FAIL,
            _CRIT,
            "推荐科目已停用",
            actual_value=cat.name,
        )
    return RuleResult(
        "category_valid",
        "科目合法",
        _PASS,
        _INFO,
        "推荐科目存在且启用",
        actual_value=cat.name,
    )


def check_duplicate_invoice(ctx: RuleContext) -> RuleResult:
    """重复发票：invoice_key 在已生效台账 + 未终结报销单中已存在。"""
    dup = [
        i.invoice_key
        for i in ctx.items
        if i.invoice_key and i.invoice_key in ctx.existing_invoice_keys
    ]
    if dup:
        return RuleResult(
            "duplicate_invoice",
            "重复发票",
            _FAIL,
            _CRIT,
            "发票已报销过（重复报销被拦截）",
            actual_value=dup[0],
        )
    return RuleResult(
        "duplicate_invoice",
        "重复发票",
        _PASS,
        _INFO,
        "无重复发票",
    )


def check_approval_match(ctx: RuleContext) -> RuleResult:
    """审批单一致性：审批金额不超额度、项目一致、申请人一致。"""
    approvals = ctx.approvals()
    if not approvals:
        return RuleResult(
            "approval_match",
            "审批单一致性",
            _PASS,
            _INFO,
            "无审批单，不适用",
        )
    ap = approvals[0]
    if ap.approval_amount > ctx.reimbursement.total_amount:
        return RuleResult(
            "approval_match",
            "审批单一致性",
            _FAIL,
            _CRIT,
            "审批金额超出报销金额",
            actual_value=str(ap.approval_amount),
            expected_value=str(ctx.reimbursement.total_amount),
        )
    if ap.project_name != ctx.project_name:
        return RuleResult(
            "approval_match",
            "审批单一致性",
            _FAIL,
            _CRIT,
            "审批项目与报销项目不一致",
            actual_value=ap.project_name,
            expected_value=ctx.project_name,
        )
    if ap.applicant_name != ctx.applicant_name:
        return RuleResult(
            "approval_match",
            "审批单一致性",
            _FAIL,
            _CRIT,
            "审批申请人与报销申请人不一致",
            actual_value=ap.applicant_name,
            expected_value=ctx.applicant_name,
        )
    return RuleResult(
        "approval_match",
        "审批单一致性",
        _PASS,
        _INFO,
        "审批单与报销一致",
    )


def check_over_amount(ctx: RuleContext) -> RuleResult:
    """超标：单笔金额超制度标准。"""
    limit = Decimal(_threshold(ctx, "threshold.reimb.over_amount", "5000.00"))
    if ctx.reimbursement.total_amount > limit:
        return RuleResult(
            "over_amount",
            "超标",
            _FAIL,
            _WARN,
            "单笔金额超过制度标准",
            actual_value=str(ctx.reimbursement.total_amount),
            threshold=str(limit),
        )
    return RuleResult(
        "over_amount",
        "超标",
        _PASS,
        _INFO,
        "金额在制度标准内",
        threshold=str(limit),
    )


def check_supplier_registered(ctx: RuleContext) -> RuleResult:
    """供应商在册（V1 默认 disabled，扩展位占位，见 requirements §4.2.4）。"""
    return RuleResult(
        "supplier_registered",
        "供应商在册",
        _PASS,
        _INFO,
        "规则未启用",
    )


# 规则注册表：code → (name, 函数, 是否启用)
REGISTRY: dict[str, dict[str, object]] = {
    "invoice_exists": {"name": "发票存在", "func": check_invoice_exists, "enabled": True},
    "travel_exists": {"name": "行程单存在", "func": check_travel_exists, "enabled": True},
    "approval_exists": {"name": "审批单存在", "func": check_approval_exists, "enabled": True},
    "amount_match": {"name": "金额一致", "func": check_amount_match, "enabled": True},
    "title_match": {"name": "抬头一致", "func": check_title_match, "enabled": True},
    "date_valid": {"name": "日期合理", "func": check_date_valid, "enabled": True},
    "budget_within": {"name": "预算内", "func": check_budget_within, "enabled": True},
    "category_valid": {"name": "科目合法", "func": check_category_valid, "enabled": True},
    "duplicate_invoice": {"name": "重复发票", "func": check_duplicate_invoice, "enabled": True},
    "approval_match": {"name": "审批单一致性", "func": check_approval_match, "enabled": True},
    "over_amount": {"name": "超标", "func": check_over_amount, "enabled": True},
    # V1 disabled 扩展位（不建 supplier 表）
    "supplier_registered": {
        "name": "供应商在册",
        "func": check_supplier_registered,
        "enabled": False,
    },
}


def run_rules(ctx: RuleContext) -> list[RuleResult]:
    """执行所有启用规则，返回结果列表（保持注册顺序）。"""
    results: list[RuleResult] = []
    for spec in REGISTRY.values():
        if spec["enabled"]:
            func = spec["func"]
            results.append(func(ctx))  # type: ignore[operator]
    return results
