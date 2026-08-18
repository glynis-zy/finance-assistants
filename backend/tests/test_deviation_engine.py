# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""偏差引擎与统计信号测试（requirements §7.2 验收项）。"""

from decimal import Decimal

import pytest
from app.domain.deviation_engine import compute
from app.domain.deviation_engine.engine import level_for_ratio
from app.domain.deviation_engine.signals import cusum_signal, ewma_signal, mad_z_signal
from app.domain.deviation_engine.types import (
    BudgetInput,
    LedgerRow,
)

UNIFORM = [1 / 12.0] * 12  # 前 6 月累计 0.5


def _budget(
    dept: int,
    proj: int,
    cat: int,
    amount: str,
    curve: list[float] | None = UNIFORM,
    year: str = "2026",
) -> BudgetInput:
    return BudgetInput(dept, proj, cat, year, Decimal(amount), curve)


def _ledger(period: str, dept: int, proj: int, cat: int, amount: str) -> LedgerRow:
    return LedgerRow(period, dept, proj, cat, Decimal(amount))


def _monthly(
    dept: int, proj: int, cat: int, amounts: list[str], year: str = "2026"
) -> list[LedgerRow]:
    return [_ledger(f"{year}-{i + 1:02d}", dept, proj, cat, a) for i, a in enumerate(amounts)]


def test_ledger_aggregation() -> None:
    """6. expense_ledger 聚合正确（月度分组合计）。"""
    rows = _monthly(1, 1, 1, ["10000.00", "20000.00", "30000.00"])
    r = compute("2026-03", [_budget(1, 1, 1, "1200000.00")], rows)
    dev = r.deviations[0]  # 累计 6 万 vs 计划 30 万 → 落后触发
    assert dev.actual_amount == Decimal("60000.00")
    assert dev.budget_amount == Decimal("300000.00")
    assert dev.deviation_amount == Decimal("-240000.00")


def test_over_budget_triggers() -> None:
    """7. 超预算正确触发（累计实际 > 累计预算）。"""
    rows = _monthly(1, 1, 1, ["133333.33"] * 6)  # 累计 80 万 > 计划 60 万
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00")], rows)
    assert len(r.deviations) == 1
    dev = r.deviations[0]
    assert "over_budget" in dev.trigger_reason
    assert dev.deviation_amount > 0
    assert dev.level == "medium"  # ratio ≈ 0.167 → medium


def test_normal_budget_no_deviation() -> None:
    """8. 正常预算不触发（累计贴近计划）。"""
    rows = _monthly(1, 1, 1, ["80000.00"] * 6)  # 累计 48 万，计划 60 万，落后 0.10
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00")], rows)
    assert r.deviations == []


def test_plan_met_no_false_progress() -> None:
    """9. 实际累计 = 计划累计（120 万 / 6 月 60 万）不误报进度异常。"""
    rows = _monthly(1, 1, 1, ["100000.00"] * 6)  # 累计 60 万 = 计划 60 万
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00")], rows)
    assert r.deviations == []


def test_progress_ahead_triggers() -> None:
    """10. 进度领先 >15% 触发（6 月实际 90 万 vs 计划 60 万）。"""
    rows = _monthly(1, 1, 1, ["150000.00"] * 6)
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00")], rows)
    assert len(r.deviations) == 1
    assert "progress" in r.deviations[0].trigger_reason


def test_progress_behind_triggers() -> None:
    """11. 进度落后 >15% 触发（6 月实际 20 万 vs 计划 60 万）。"""
    rows = _monthly(1, 1, 1, ["0.00", "0.00", "0.00", "0.00", "0.00", "200000.00"])
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00")], rows)
    assert len(r.deviations) == 1
    assert "progress" in r.deviations[0].trigger_reason


def test_growth_mom_triggers() -> None:
    """12. 环比增幅 >30% 触发（5 月 10 万 → 6 月 20 万）。"""
    rows = _monthly(1, 1, 1, ["80000.00"] * 4 + ["100000.00", "200000.00"])
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00")], rows)
    assert len(r.deviations) == 1
    assert "growth" in r.deviations[0].trigger_reason


def test_growth_yoy_triggers() -> None:
    """13. 同比增幅 >50% 触发（去年 6 月 10 万 → 今年 6 月 20 万）。"""
    rows = _monthly(1, 1, 1, ["80000.00"] * 4 + ["0.00", "200000.00"])
    rows.append(_ledger("2025-06", 1, 1, 1, "100000.00"))
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00")], rows)
    assert len(r.deviations) == 1
    assert "growth" in r.deviations[0].trigger_reason


def test_growth_zero_denominator_safe() -> None:
    """14. 环比/同比分母为 0 显式跳过（不除零、不伪异常）。"""
    rows = _monthly(1, 1, 1, ["125000.00"] * 4 + ["0.00", "150000.00"])
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00")], rows)
    # 环比 prev=0、同比无数据 → 不触发 growth（over_budget 触发不影响该断言）
    dev = r.deviations[0]
    assert "growth" not in dev.trigger_reason
    assert "over_budget" in dev.trigger_reason  # 累计 65 万 > 计划 60 万


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        ("0.049", "low"),
        ("0.05", "medium"),
        ("0.20", "medium"),
        ("0.2001", "high"),
        ("-0.25", "high"),
        ("0.0", "low"),
    ],
)
def test_level_boundaries(ratio: str, expected: str) -> None:
    """15. low/medium/high 边界值。"""
    assert level_for_ratio(Decimal(ratio), 0.05, 0.20) == expected


def test_ewma_signal() -> None:
    """16. EWMA 信号（支出骤降为 0 触发漂移）。"""
    series = [Decimal("0.1")] * 4 + [Decimal("0")]
    value, triggered = ewma_signal(series, lamb=0.3, delta=0.3)
    assert value == Decimal("0")
    assert triggered is True


def test_cusum_signal() -> None:
    """17. CUSUM 信号（持续超支累积）。"""
    actual = [
        Decimal("0.1"),
        Decimal("0.2"),
        Decimal("0.3"),
        Decimal("0.4"),
        Decimal("0.5"),
        Decimal("0.6"),
    ]
    planned = [Decimal("0.08")] * 6
    value, triggered = cusum_signal(actual, planned, h=0.1)
    assert value is not None and value > Decimal("0.1")
    assert triggered is True


def test_mad_z_signal() -> None:
    """18. MAD 修正 Z-score 离群检测。"""
    values = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.33")]
    z, triggered = mad_z_signal(values, Decimal("-0.33"), z_threshold=3.0)
    assert z is not None and abs(z) > 3
    assert triggered is True


def test_single_signal_no_upgrade() -> None:
    """19. 单期单统计信号仅提示（不升级 → 无正式偏差）。"""
    # 仅 EWMA 触发：1-4 月 12 万，5 月 0，6 月 12 万；预算 120 万、计划 6 月 72 万
    curve = [0.1] * 9 + [0.05, 0.05, 0.0]  # 前 6 月累计 0.6，合计 1.0
    rows = _monthly(1, 1, 1, ["120000.00"] * 4 + ["0.00", "120000.00"])
    r = compute("2026-06", [_budget(1, 1, 1, "1200000.00", curve)], rows)
    assert r.deviations == []  # 累计 60 万 = 计划 72 万前不触发；确定性规则均不触发
    ewma = [s for s in r.signals if s.signal_type == "ewma"]
    assert ewma and ewma[0].triggered is True
    assert ewma[0].consecutive_periods == 1
    assert ewma[0].upgraded is False


def test_consecutive_signal_upgrade() -> None:
    """20. 同一信号连续 2 期触发 → 升级为正式偏差。"""
    budget = _budget(1, 1, 1, "2000000.00")  # 计划 6 月 100 万
    rows5 = _monthly(1, 1, 1, ["150000.00"] * 4 + ["0.00"])  # 5 月累计 60 万 < 计划 83 万
    r5 = compute("2026-05", [budget], rows5)
    assert r5.deviations == []
    ewma5 = [s for s in r5.signals if s.signal_type == "ewma" and s.triggered]
    assert len(ewma5) == 1 and ewma5[0].consecutive_periods == 1

    rows6 = _monthly(1, 1, 1, ["150000.00"] * 4 + ["0.00", "150000.00"])
    prev = {(1, 1, 1): {"ewma": ewma5[0].consecutive_periods}}
    r6 = compute("2026-06", [budget], rows6, prev_signal_consecutive=prev)
    assert len(r6.deviations) == 1
    assert r6.deviations[0].trigger_reason == "stat_signal"
    assert all(s.upgraded is True for s in r6.signals if s.triggered)


def test_two_signals_same_period_upgrade() -> None:
    """21. 同期 >=2 个独立信号触发 → 升级。"""
    budgets = [
        _budget(1, 1, 1, "1200000.00"),  # A：每月 10.05 万 → ratio 0.0025
        _budget(1, 2, 1, "1200000.00"),  # B：每月 9.95 万 → ratio -0.0025
        _budget(1, 3, 1, "1200000.00"),  # C：5 月 0 支出 → ratio -0.0833（EWMA + MAD）
    ]
    rows = (
        _monthly(1, 1, 1, ["100500.00"] * 6)
        + _monthly(1, 2, 1, ["99500.00"] * 6)
        + _monthly(1, 3, 1, ["100000.00"] * 5 + ["0.00"])
    )
    r = compute("2026-06", budgets, rows)
    # C 维度（proj=3）确定性不触发，靠双信号升级
    dev_c = [d for d in r.deviations if d.project_id == 3]
    assert len(dev_c) == 1
    assert dev_c[0].trigger_reason == "stat_signal"
    sig_c = [s for s in r.signals if s.project_id == 3 and s.triggered]
    assert {s.signal_type for s in sig_c} == {"ewma", "mad"}
    assert all(s.upgraded for s in sig_c)
