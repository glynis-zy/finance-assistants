"""规则引擎类型定义。

规则引擎是确定性纯逻辑（docs/DESIGN.md §1.1）：输入从外部注入，同一输入产出同一结论。
每条规则输出可解释结果（code / actual / expected / threshold / status / risk_level / message）。
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.models.base_data import CostCategory
from app.models.reimbursement import Reimbursement, ReimbursementItem


class RuleStatus(StrEnum):
    """规则判定状态。"""

    PASSED = "passed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass
class RuleResult:
    """单条规则判定结果（可解释、可审计）。"""

    code: str
    name: str
    status: str
    risk_level: str
    message: str
    actual_value: Any = None
    expected_value: Any = None
    threshold: Any = None

    def to_dict(self) -> dict[str, Any]:
        """转为 JSON 可序列化结构（check_items 元素）。"""
        return {
            "rule": self.code,
            "name": self.name,
            "status": self.status,
            "risk_level": self.risk_level,
            "actual_value": self.actual_value,
            "expected_value": self.expected_value,
            "threshold": self.threshold,
            "message": self.message,
        }


@dataclass
class ParsedDocument:
    """单个附件的解析结果（解析层与规则层之间的桥梁）。"""

    category: str  # invoice / travel / approval
    confidence: float
    low_confidence: bool
    data: BaseModel | None  # Pydantic 校验后的结构化数据；低置信度/失败为 None
    error: str | None = None


@dataclass
class BudgetCheck:
    """单个科目维度的预算检查数据（audit_service 预聚合注入）。"""

    cost_category_id: int
    budget_amount: Decimal
    ledger_amount: Decimal
    item_amount: Decimal


@dataclass
class RuleContext:
    """规则引擎输入上下文。"""

    reimbursement: Reimbursement
    items: list[ReimbursementItem]
    parsed_docs: list[ParsedDocument]
    categories: list[CostCategory]
    budget_checks: list[BudgetCheck] = field(default_factory=lambda: [])
    company_name: str = ""
    thresholds: dict[str, str] = field(default_factory=lambda: {})
    existing_invoice_keys: set[str] = field(default_factory=lambda: set())
    project_name: str = ""
    applicant_name: str = ""
    recommended_category: CostCategory | None = None

    def invoices(self) -> list[Any]:
        """解析成功的发票数据。"""
        return [d.data for d in self.parsed_docs if d.category == "invoice" and d.data is not None]

    def travels(self) -> list[Any]:
        return [d.data for d in self.parsed_docs if d.category == "travel" and d.data is not None]

    def approvals(self) -> list[Any]:
        return [d.data for d in self.parsed_docs if d.category == "approval" and d.data is not None]

    def has_category_attachment(self, category: str) -> bool:
        """是否存在指定分类的附件。"""
        return any(d.category == category for d in self.parsed_docs)

    def has_low_confidence(self, category: str) -> bool:
        """指定分类是否存在低置信度（无法可靠提取）的附件。"""
        return any(d.category == category and d.low_confidence for d in self.parsed_docs)
