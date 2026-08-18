"""应收风险评分引擎（3.3.3）：确定性规则加权评分，不调用 LLM。

因子（requirements §4.4.2，Stage 4 口径冻结）：
- aging：单笔按逾期天数分档（0/1-30/31-90/91-180/>180 → 0/30/50/70/90），
  多笔未结按未结余额加权平均
- term：clamp((term_cap_days - payment_term_days) / term_cap_days × 100, 0, 100)，多笔按余额加权
- payment：overdue_rate(历史逾期结清/历史结清×100)×0.5 + delay(min(平均正向延迟/cap,1)×100)×0.5；
  无历史结清 → 0
- collection：无催收 0；最近催收后有回款 0；其后无回款且仍有未结 100
总分 = aging×0.4 + term×0.2 + payment×0.3 + collection×0.1（ROUND_HALF_UP 取整）
客户无未结应收 → total=0 / low。
预计回款 = 最早到期未结应收的到期日 + 历史平均正向回款延迟（无历史付款为 0）；
expected_overdue_days = max(0, expected_payment_date - due_date)。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.domain.scoring_engine.types import (
    DEFAULT_THRESHOLDS,
    CollectionInput,
    FactorScore,
    PaymentInput,
    ReceivableInput,
    ScoreResult,
)

# 账龄分档：逾期天数 → 档分
_AGING_BANDS: list[tuple[float, float]] = [
    (0.0, 0.0),
    (30.0, 30.0),
    (90.0, 50.0),
    (180.0, 70.0),
    (float("inf"), 90.0),
]


def aging_band_score(overdue_days: int) -> float:
    """单笔账龄档分：未逾期 0；1-30 天 30；31-90 天 50；91-180 天 70；>180 天 90。"""
    for cap, score in _AGING_BANDS:
        if overdue_days <= cap:
            return score
    return 90.0


def term_score_for(payment_term_days: int, term_cap_days: float) -> float:
    """账期因子分：clamp((cap - term) / cap × 100, 0, 100)。"""
    if payment_term_days <= 0:
        return 100.0
    return max(0.0, min(100.0, (term_cap_days - payment_term_days) / term_cap_days * 100.0))


def risk_level_for(total_score: int, high_score: float) -> str:
    """风险档位：low <40；medium 40~69；high >=70（high_score 可配）。"""
    if total_score >= high_score:
        return "high"
    if total_score >= 40:
        return "medium"
    return "low"


def _outstanding(receivables: list[ReceivableInput]) -> list[ReceivableInput]:
    """未结应收（未结余额 > 0）。"""
    return [r for r in receivables if r.amount - r.paid_amount > 0]


def _weighted_average(values: list[tuple[float, float]]) -> float:
    """按余额权重求平均（values = [(value, balance)]）；总余额为 0 返回 0。"""
    total_balance = sum(b for _, b in values)
    if total_balance <= 0:
        return 0.0
    return sum(v * b for v, b in values) / total_balance


def _settled_stats(
    receivables: list[ReceivableInput], payments: list[PaymentInput]
) -> tuple[int, int, float]:
    """历史结清统计：(结清笔数, 逾期结清笔数, 平均正向延迟天数)。

    结清日 = 该笔应收所有回款中 received_at 最大者（日期）。
    正向延迟 = max(0, 结清日 - due_date)。
    """
    by_rec: dict[int, list[PaymentInput]] = {}
    for p in payments:
        by_rec.setdefault(p.receivable_id, []).append(p)

    settled_count = 0
    overdue_count = 0
    delays: list[float] = []
    for r in receivables:
        if r.amount - r.paid_amount > 0:
            continue  # 未结清不计入历史
        ps = by_rec.get(r.receivable_id, [])
        if not ps:
            continue
        settled_count += 1
        last = max(p.received_at for p in ps)
        delay = max(0.0, (last.date() - r.due_date).days)
        delays.append(float(delay))
        if delay > 0:
            overdue_count += 1
    avg_delay = sum(delays) / len(delays) if delays else 0.0
    return settled_count, overdue_count, avg_delay


def _latest_collection(collections: list[CollectionInput]) -> date | None:
    if not collections:
        return None
    return max(c.occurred_at for c in collections).date()


def compute(
    customer_id: int,
    score_date: date,
    receivables: list[ReceivableInput],
    payments: list[PaymentInput],
    collections: list[CollectionInput],
    thresholds: dict[str, float] | None = None,
) -> ScoreResult:
    """计算客户风险分（纯确定性；同一数据+同一参数 → 同一结果）。"""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    cap_days = th["threshold.ar.term_cap_days"]
    delay_cap = th["threshold.ar.history_delay_cap_days"]
    w_aging = th["threshold.ar.w_aging"]
    w_term = th["threshold.ar.w_term"]
    w_payment = th["threshold.ar.w_payment"]
    w_collection = th["threshold.ar.w_collection"]
    high_score = th["threshold.ar.high_score"]

    outstanding = _outstanding(receivables)
    overdue_amount = sum(
        (r.amount - r.paid_amount) for r in outstanding if (score_date - r.due_date).days > 0
    )

    # aging / term：未结余额加权
    if outstanding:
        aging_values = [
            (aging_band_score(max(0, (score_date - r.due_date).days)), r.amount - r.paid_amount)
            for r in outstanding
        ]
        term_values = [
            (term_score_for(r.payment_term_days, cap_days), r.amount - r.paid_amount)
            for r in outstanding
        ]
        aging_raw = _weighted_average(aging_values)
        term_raw = _weighted_average(term_values)
    else:
        aging_raw = 0.0
        term_raw = 0.0

    # payment：历史结清统计
    settled_count, overdue_count, avg_delay = _settled_stats(receivables, payments)
    if settled_count > 0:
        overdue_rate_score = overdue_count / settled_count * 100.0
        delay_score = min(avg_delay / delay_cap, 1.0) * 100.0 if delay_cap > 0 else 0.0
        payment_raw = overdue_rate_score * 0.5 + delay_score * 0.5
    else:
        overdue_rate_score = 0.0
        delay_score = 0.0
        payment_raw = 0.0  # 无历史结清数据 → 0

    # collection：最近催收之后是否有回款
    latest_coll = _latest_collection(collections)
    if latest_coll is None:
        collection_raw = 0.0
    else:
        paid_after = any(p.received_at.date() > latest_coll for p in payments)
        if paid_after:
            collection_raw = 0.0
        elif outstanding:
            collection_raw = 100.0
        else:
            collection_raw = 0.0

    if outstanding:
        total = Decimal(
            aging_raw * w_aging
            + term_raw * w_term
            + payment_raw * w_payment
            + collection_raw * w_collection
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total_score = int(total)
        risk_level = risk_level_for(total_score, high_score)

        # 预计回款：最早到期的未结应收 + 历史平均正向延迟
        earliest = min(outstanding, key=lambda r: r.due_date)
        avg_delay_days = int(round(avg_delay))
        expected_payment_date = earliest.due_date + timedelta(days=avg_delay_days)
        expected_overdue_days = max(0, (expected_payment_date - earliest.due_date).days)
    else:
        total_score = 0
        risk_level = "low"
        expected_payment_date = None
        expected_overdue_days = None

    factors = {
        "aging": FactorScore(
            raw_score=round(aging_raw, 2),
            weight=w_aging,
            weighted_score=round(aging_raw * w_aging, 2),
            detail={
                "outstanding_count": len(outstanding),
                "band_scores": [
                    {
                        "receivable_id": r.receivable_id,
                        "overdue_days": max(0, (score_date - r.due_date).days),
                        "band_score": aging_band_score(max(0, (score_date - r.due_date).days)),
                        "outstanding_balance": r.amount - r.paid_amount,
                    }
                    for r in outstanding
                ],
            },
        ),
        "term": FactorScore(
            raw_score=round(term_raw, 2),
            weight=w_term,
            weighted_score=round(term_raw * w_term, 2),
            detail={"term_cap_days": cap_days},
        ),
        "payment": FactorScore(
            raw_score=round(payment_raw, 2),
            weight=w_payment,
            weighted_score=round(payment_raw * w_payment, 2),
            detail={
                "settled_count": settled_count,
                "overdue_settled_count": overdue_count,
                "overdue_rate_score": round(overdue_rate_score, 2),
                "avg_positive_delay_days": round(avg_delay, 2),
                "delay_score": round(delay_score, 2),
            },
        ),
        "collection": FactorScore(
            raw_score=round(collection_raw, 2),
            weight=w_collection,
            weighted_score=round(collection_raw * w_collection, 2),
            detail={"latest_collection_date": latest_coll.isoformat() if latest_coll else None},
        ),
    }
    return ScoreResult(
        customer_id=customer_id,
        score_date=score_date,
        factors=factors,
        total_score=total_score,
        risk_level=risk_level,
        expected_payment_date=expected_payment_date,
        expected_overdue_days=expected_overdue_days,
        overdue_amount=round(overdue_amount, 2),
    )
