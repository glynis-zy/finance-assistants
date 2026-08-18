"""预算偏差引擎（3.3.2）：确定性规则 + 统计信号，纯计算、可测试。"""

from app.domain.deviation_engine.engine import compute
from app.domain.deviation_engine.types import (
    BudgetInput,
    DeviationResult,
    LedgerRow,
    MonitorResult,
    SignalResult,
)

__all__ = [
    "compute",
    "BudgetInput",
    "DeviationResult",
    "LedgerRow",
    "MonitorResult",
    "SignalResult",
]
