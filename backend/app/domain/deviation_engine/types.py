"""预算偏差引擎（3.3.2）核心类型。

引擎为纯计算：输入预算/台账/阈值，输出偏差与统计信号结果，不接触 DB。
DB 装配与持久化由 services/monitor_service 完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

# 触发原因取值（trigger_reason，可逗号合并）
TRIGGER_OVER_BUDGET = "over_budget"
TRIGGER_PROGRESS = "progress"
TRIGGER_GROWTH = "growth"
TRIGGER_STAT_SIGNAL = "stat_signal"

# 统计信号类型
SIGNAL_EWMA = "ewma"
SIGNAL_CUSUM = "cusum"
SIGNAL_MAD = "mad"


@dataclass(frozen=True)
class BudgetInput:
    """预算数据（部门×项目×科目×年度，含分摊曲线）。"""

    department_id: int
    project_id: int
    cost_category_id: int
    budget_year: str
    amount: Decimal
    allocation_curve: list[float] | None
    owner: str | None = None


@dataclass(frozen=True)
class LedgerRow:
    """台账行（预算监控只读）。"""

    period: str  # YYYY-MM
    department_id: int
    project_id: int
    cost_category_id: int
    amount: Decimal


@dataclass(frozen=True)
class DeviationResult:
    """正式偏差记录（累计口径）。"""

    department_id: int
    project_id: int
    cost_category_id: int
    period: str
    budget_amount: Decimal
    actual_amount: Decimal
    deviation_amount: Decimal
    deviation_ratio: Decimal | None
    level: str
    owner: str | None
    trigger_reason: str


@dataclass(frozen=True)
class SignalResult:
    """统计信号记录（提示级）。"""

    signal_type: str
    department_id: int
    project_id: int
    cost_category_id: int
    period: str
    value: Decimal | None
    triggered: bool
    consecutive_periods: int
    upgraded: bool


@dataclass
class MonitorResult:
    """一次监控运行的完整结果。"""

    period: str
    deviations: list[DeviationResult] = field(default_factory=list[DeviationResult])
    signals: list[SignalResult] = field(default_factory=list[SignalResult])
    budgets_checked: int = 0
