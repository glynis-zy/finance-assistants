"""应收风险评分引擎（3.3.3）核心类型。

引擎为纯确定性计算：输入客户应收/付款/催收数据与阈值，输出因子明细与总分。
DB 装配与持久化由 services/ar_service 完成。不调用 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# 阈值键默认值（与 seed 的 sys_param 键一致）
DEFAULT_THRESHOLDS: dict[str, float] = {
    "threshold.ar.term_cap_days": 120.0,
    "threshold.ar.history_delay_cap_days": 90.0,
    "threshold.ar.high_score": 70.0,
    "threshold.ar.w_aging": 0.4,
    "threshold.ar.w_term": 0.2,
    "threshold.ar.w_payment": 0.3,
    "threshold.ar.w_collection": 0.1,
}


@dataclass(frozen=True)
class ReceivableInput:
    """应收单数据（含累计到账，balance = amount - paid）。"""

    receivable_id: int
    customer_id: int
    contract_id: int | None
    amount: float
    paid_amount: float
    due_date: date
    status: str
    payment_term_days: int = 30


@dataclass(frozen=True)
class PaymentInput:
    """回款记录。"""

    receivable_id: int
    amount: float
    received_at: datetime


@dataclass(frozen=True)
class CollectionInput:
    """催收记录。"""

    occurred_at: datetime


@dataclass(frozen=True)
class FactorScore:
    """单因子结果（raw/weight/weighted 三字段契约）。"""

    raw_score: float
    weight: float
    weighted_score: float
    detail: dict[str, object] = field(default_factory=dict[str, object])


@dataclass(frozen=True)
class ScoreResult:
    """客户评分结果（完整因子明细，可解释）。"""

    customer_id: int
    score_date: date
    factors: dict[str, FactorScore]
    total_score: int
    risk_level: str
    expected_payment_date: date | None
    expected_overdue_days: int | None
    overdue_amount: float
