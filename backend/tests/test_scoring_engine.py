# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""scoring_engine 纯确定性测试（1-21 项引擎部分）。"""

from datetime import date, datetime

import pytest
from app.domain.scoring_engine import (
    aging_band_score,
    compute,
    risk_level_for,
    term_score_for,
)
from app.domain.scoring_engine.types import (
    CollectionInput,
    PaymentInput,
    ReceivableInput,
)

SCORE_DATE = date(2026, 8, 18)


def _rec(
    rid: int,
    amount: float,
    paid: float = 0.0,
    due: date = date(2026, 8, 18),
    term: int = 30,
) -> ReceivableInput:
    return ReceivableInput(
        receivable_id=rid,
        customer_id=1,
        contract_id=1,
        amount=amount,
        paid_amount=paid,
        due_date=due,
        status="settled" if paid >= amount else "open",
        payment_term_days=term,
    )


def _pay(rid: int, amount: float, at: str) -> PaymentInput:
    return PaymentInput(rid, amount, datetime.fromisoformat(at.replace("Z", "+00:00")))


def _col(at: str) -> CollectionInput:
    return CollectionInput(datetime.fromisoformat(at.replace("Z", "+00:00")))


def test_overdue_days() -> None:
    """6. overdue_days 动态正确（通过 aging 档分间接验证）。"""
    r = _rec(1, 1000.0, due=date(2026, 7, 19))  # 30 天前
    result = compute(1, SCORE_DATE, [r], [], [])
    assert result.factors["aging"].raw_score == 30.0


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (date(2026, 8, 18), 0.0),  # 未逾期
        (date(2026, 7, 19), 30.0),  # 30 天
        (date(2026, 7, 18), 50.0),  # 31 天
        (date(2026, 5, 19), 70.0),  # 91 天
        (date(2026, 5, 18), 70.0),  # 92 天
        (date(2026, 2, 18), 90.0),  # 181 天
        (date(2026, 2, 17), 90.0),  # 182 天
    ],
)
def test_aging_band_boundaries(due: date, expected: float) -> None:
    """7. aging 各档边界（0/1-30/31-90/91-180/>180）。"""
    assert aging_band_score(max(0, (SCORE_DATE - due).days)) == expected


def test_aging_balance_weighted() -> None:
    """8. 多笔未结余额加权 aging。"""
    r1 = _rec(1, 1000.0, due=date(2026, 7, 19))  # 30 分，余额 1000
    r2 = _rec(2, 2000.0, due=date(2026, 2, 17))  # 90 分，余额 2000
    result = compute(1, SCORE_DATE, [r1, r2], [], [])
    assert result.factors["aging"].raw_score == pytest.approx((1000 * 30 + 2000 * 90) / 3000)


@pytest.mark.parametrize(
    ("term", "expected"),
    [(120, 0.0), (90, 25.0), (60, 50.0), (30, 75.0), (0, 100.0), (150, 0.0)],
)
def test_term_score_boundaries(term: int, expected: float) -> None:
    """9. term_score 0/30/60/90/120+ 边界与 clamp。"""
    assert term_score_for(term, 120.0) == pytest.approx(expected)


def test_no_settled_payment_score_zero() -> None:
    """10. 无历史结清数据 payment_score=0。"""
    r = _rec(1, 1000.0, due=date(2026, 1, 1))
    result = compute(1, SCORE_DATE, [r], [], [])
    assert result.factors["payment"].raw_score == 0.0


def test_overdue_rate_score() -> None:
    """11. 历史逾期率计算（2 笔结清 1 笔逾期 → overdue_rate 50）。"""
    # R1 结清（正常，延迟 0：付款日=到期日）；R2 结清（逾期 10 天）
    r1 = _rec(1, 1000.0, paid=1000.0, due=date(2026, 7, 1))
    r2 = _rec(2, 1000.0, paid=1000.0, due=date(2026, 7, 1))
    pays = [
        _pay(1, 1000.0, "2026-07-01T00:00:00Z"),
        _pay(2, 1000.0, "2026-07-11T00:00:00Z"),
    ]
    result = compute(1, SCORE_DATE, [r1, r2], pays, [])
    detail = result.factors["payment"].detail
    assert detail["settled_count"] == 2
    assert detail["overdue_rate_score"] == 50.0
    assert detail["avg_positive_delay_days"] == pytest.approx(5.0)  # (0+10)/2
    assert detail["delay_score"] == pytest.approx(round(5 / 90 * 100, 2))
    assert result.factors["payment"].raw_score == pytest.approx(
        50 * 0.5 + round(5 / 90 * 100, 2) * 0.5
    )


def test_delay_score_normalized() -> None:
    """12. 平均延迟归一：90+ 天 → 100；45 天 → 50。"""
    r = _rec(1, 1000.0, paid=1000.0, due=date(2026, 5, 1))
    pay = _pay(1, 1000.0, "2026-08-01T00:00:00Z")  # 延迟 92 天
    result = compute(1, SCORE_DATE, [r], [pay], [])
    assert result.factors["payment"].detail["delay_score"] == pytest.approx(100.0)

    r2 = _rec(1, 1000.0, paid=1000.0, due=date(2026, 6, 1))
    pay2 = _pay(1, 1000.0, "2026-07-16T00:00:00Z")  # 延迟 45 天
    result2 = compute(1, SCORE_DATE, [r2], [pay2], [])
    assert result2.factors["payment"].detail["delay_score"] == pytest.approx(50.0)


def test_no_collection_score_zero() -> None:
    """13. 无催收记录 collection_score=0。"""
    r = _rec(1, 1000.0, due=date(2026, 1, 1))
    result = compute(1, SCORE_DATE, [r], [], [])
    assert result.factors["collection"].raw_score == 0.0


def test_collection_no_payment_after_score_100() -> None:
    """14. 最近催收之后无回款且仍有未结 → collection=100。"""
    r = _rec(1, 1000.0, due=date(2026, 1, 1))
    result = compute(1, SCORE_DATE, [r], [], [_col("2026-08-01T00:00:00Z")])
    assert result.factors["collection"].raw_score == 100.0


def test_collection_paid_after_score_zero() -> None:
    """15. 最近催收之后存在回款 → collection=0。"""
    r = _rec(1, 1000.0, paid=500.0, due=date(2026, 1, 1))
    pay = _pay(1, 500.0, "2026-08-10T00:00:00Z")  # 催收后回款
    result = compute(1, SCORE_DATE, [r], [pay], [_col("2026-08-01T00:00:00Z")])
    assert result.factors["collection"].raw_score == 0.0


def test_weighted_total() -> None:
    """16. 四因子权重总分（aging90/term75/payment~83/collection100 → 86）。"""
    # 未结逾期 200 天（aging 90）、term 30（75 分）
    r_open = _rec(1, 2000.0, due=date(2026, 1, 31), term=30)
    # 历史结清 1 笔：延迟 60 天 → overdue_rate 100、delay 66.67 → payment 83.33
    r_settled = _rec(2, 1000.0, paid=1000.0, due=date(2025, 12, 1))
    pays = [_pay(2, 1000.0, "2026-01-30T00:00:00Z")]
    cols = [_col("2026-08-01T00:00:00Z")]  # 催收后未回款 → collection 100
    result = compute(1, SCORE_DATE, [r_open, r_settled], pays, cols)
    assert result.factors["aging"].raw_score == 90.0
    assert result.factors["term"].raw_score == pytest.approx(75.0)
    assert result.factors["payment"].raw_score == pytest.approx(83.33, abs=0.01)
    assert result.factors["collection"].raw_score == 100.0
    assert result.total_score == 86
    assert result.risk_level == "high"


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0, "low"), (39, "low"), (40, "medium"), (69, "medium"), (70, "high"), (100, "high")],
)
def test_risk_level_boundaries(score: int, expected: str) -> None:
    """17. score 39/40/69/70 风险档位边界。"""
    assert risk_level_for(score, 70.0) == expected


def test_no_outstanding_low_zero() -> None:
    """18. 无未结应收 → total=0 / low。"""
    r = _rec(1, 1000.0, paid=1000.0, due=date(2026, 1, 1))
    pay = _pay(1, 1000.0, "2026-02-01T00:00:00Z")
    result = compute(1, SCORE_DATE, [r], [pay], [])
    assert result.total_score == 0
    assert result.risk_level == "low"
    assert result.expected_payment_date is None


def test_expected_payment_date() -> None:
    """19. expected_payment_date = 最早到期未结 + 历史平均延迟。"""
    r_open = _rec(1, 2000.0, due=date(2026, 6, 1))
    r_settled = _rec(2, 1000.0, paid=1000.0, due=date(2026, 5, 1))
    pay = _pay(2, 1000.0, "2026-05-11T00:00:00Z")  # 延迟 10 天
    result = compute(1, SCORE_DATE, [r_open, r_settled], [pay], [])
    assert result.expected_payment_date == date(2026, 6, 11)
    assert result.expected_overdue_days == 10


def test_expected_overdue_days_formula() -> None:
    """20. expected_overdue_days = max(0, expected_payment_date - due_date)。"""
    r = _rec(1, 2000.0, due=date(2026, 6, 1))
    r_settled = _rec(2, 1000.0, paid=1000.0, due=date(2026, 5, 1))
    pay = _pay(2, 1000.0, "2026-04-20T00:00:00Z")  # 提前回款 → 正向延迟 0
    result = compute(1, SCORE_DATE, [r, r_settled], [pay], [])
    assert result.expected_overdue_days == 0
    assert result.expected_payment_date == date(2026, 6, 1)


def test_earliest_due_selected() -> None:
    """21. 多笔未结应收选择最早到期项。"""
    r1 = _rec(1, 1000.0, due=date(2026, 9, 1))
    r2 = _rec(2, 2000.0, due=date(2026, 7, 1))  # 最早到期
    result = compute(1, SCORE_DATE, [r1, r2], [], [])
    assert result.expected_payment_date == date(2026, 7, 1)
