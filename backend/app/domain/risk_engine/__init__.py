"""确定性规则引擎（docs/DESIGN.md §1.1）。"""

from app.domain.risk_engine.rules import REGISTRY, run_rules
from app.domain.risk_engine.types import (
    BudgetCheck,
    ParsedDocument,
    RuleContext,
    RuleResult,
    RuleStatus,
)

__all__ = [
    "REGISTRY",
    "run_rules",
    "BudgetCheck",
    "ParsedDocument",
    "RuleContext",
    "RuleResult",
    "RuleStatus",
]
