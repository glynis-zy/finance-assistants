"""预算执行偏差引擎（3.3.2）：确定性规则 + 统计信号升级。

确定性规则（requirements §4.3.2）：
- 超预算：截止当前累计实际 > 累计预算（台账为唯一权威）
- 进度异常：|实际进度 − 计划进度| > 阈值（默认 15%），分母均为年度预算总额
- 异常增长：环比 > 30% 或 同比 > 50%（分母为 0 显式跳过）

统计信号（提示级）：EWMA / CUSUM / MAD，升级规则——同一信号连续 N 期（默认 2）
或同期 ≥ 2 个独立信号 → 升级为正式偏差；否则仅提示。

所有阈值从 sys_param 读取（monitor_service 装配后传入），本层保持确定性纯计算。
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.domain.deviation_engine.signals import cusum_signal, ewma_signal, mad_z_signal
from app.domain.deviation_engine.types import (
    TRIGGER_GROWTH,
    TRIGGER_OVER_BUDGET,
    TRIGGER_PROGRESS,
    TRIGGER_STAT_SIGNAL,
    BudgetInput,
    DeviationResult,
    LedgerRow,
    MonitorResult,
    SignalResult,
)

SignalKey = tuple[int, int, int]

# 阈值键默认值（与 seed 的 sys_param 键一致）
DEFAULT_THRESHOLDS: dict[str, float] = {
    "threshold.budget.progress_gap": 0.15,
    "threshold.budget.level_low": 0.05,
    "threshold.budget.level_high": 0.20,
    "threshold.budget.growth_mom": 0.30,
    "threshold.budget.growth_yoy": 0.50,
    "threshold.budget.signal_consecutive": 2.0,
    "threshold.budget.ewma_lambda": 0.30,
    "threshold.budget.ewma_delta": 0.30,
    "threshold.budget.cusum_h": 0.10,
    "threshold.budget.mad_z": 3.0,
}


def cumulative_ratio(curve: list[float] | None, month: int) -> Decimal:
    """截止 month 的累计分摊比例：有曲线按前 month 项之和，无曲线按均匀分摊。"""
    if curve:
        return sum((Decimal(str(x)) for x in curve[:month]), Decimal(0))
    return Decimal(month) / Decimal(12)


def level_for_ratio(ratio: Decimal, low: float, high: float) -> str:
    """偏差等级：low <5%；5% ≤ medium ≤ 20%；>20% high（按绝对值，阈值可配）。"""
    a = abs(ratio)
    if a < Decimal(str(low)):
        return "low"
    if a <= Decimal(str(high)):
        return "medium"
    return "high"


def _monthly_by_key(ledger: list[LedgerRow], year: str) -> dict[SignalKey, dict[int, Decimal]]:
    """按维度聚合年内各月台账金额（period 仅本年度）。"""
    out: dict[SignalKey, dict[int, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in ledger:
        if not row.period.startswith(f"{year}-"):
            continue
        try:
            m = int(row.period[5:7])
        except ValueError:
            continue
        key = (row.department_id, row.project_id, row.cost_category_id)
        out[key][m] += row.amount
    return {k: dict(v) for k, v in out.items()}


def _last_year_same_month(ledger: list[LedgerRow], period: str) -> dict[SignalKey, Decimal]:
    """去年同月台账金额（同比用；无数据为 0 → 同比不触发）。"""
    year = int(period[:4]) - 1
    prefix = f"{year}-{period[5:7]}"
    out: dict[SignalKey, Decimal] = defaultdict(Decimal)
    for row in ledger:
        if row.period == prefix:
            key = (row.department_id, row.project_id, row.cost_category_id)
            out[key] += row.amount
    return dict(out)


def compute(
    period: str,
    budgets: list[BudgetInput],
    ledger: list[LedgerRow],
    thresholds: dict[str, float] | None = None,
    prev_signal_consecutive: dict[SignalKey, dict[str, int]] | None = None,
) -> MonitorResult:
    """执行一次监控计算（纯函数）。"""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    year = period[:4]
    try:
        month = int(period[5:7])
    except ValueError:
        raise ValueError(f"无效核算期: {period}") from None
    if not 1 <= month <= 12:
        raise ValueError(f"无效核算期: {period}")

    monthly = _monthly_by_key(ledger, year)
    prev_year = _last_year_same_month(ledger, period)
    prev_sigs = prev_signal_consecutive or {}

    result = MonitorResult(period=period)
    # 按维度（去重：同维度同年度唯一预算）
    dim_budgets: dict[SignalKey, BudgetInput] = {}
    for b in budgets:
        key = (b.department_id, b.project_id, b.cost_category_id)
        dim_budgets[key] = b
    result.budgets_checked = len(dim_budgets)

    # 第一遍：计算各维度累计偏差与累计值（MAD 截面需要全维度 ratio）
    ratios: dict[SignalKey, Decimal | None] = {}
    cum_actual_by_key: dict[SignalKey, Decimal] = {}
    cum_budget_by_key: dict[SignalKey, Decimal] = {}
    for key, budget in dim_budgets.items():
        if budget.amount <= 0:
            ratios[key] = None
            continue
        cum_actual = sum((v for m, v in monthly.get(key, {}).items() if m <= month), Decimal(0))
        cum_budget = (budget.amount * cumulative_ratio(budget.allocation_curve, month)).quantize(
            Decimal("0.01")
        )
        cum_actual_by_key[key] = cum_actual
        cum_budget_by_key[key] = cum_budget
        ratios[key] = ((cum_actual - cum_budget) / budget.amount).quantize(Decimal("0.0001"))

    # MAD 截面组：同科目
    mad_groups: dict[int, list[Decimal]] = defaultdict(list)
    for key, r in ratios.items():
        if r is not None:
            mad_groups[key[2]].append(r)

    for key, budget in dim_budgets.items():
        dept, proj, cat = key
        if budget.amount <= 0:
            continue  # 年度预算为 0/负 → 无法可靠计算，显式跳过（不产生除零/伪异常）
        m_series = [monthly.get(key, {}).get(t, Decimal(0)) for t in range(1, month + 1)]
        cur = m_series[-1] if m_series else Decimal(0)
        cum_actual = cum_actual_by_key[key]
        cum_budget = cum_budget_by_key[key]
        deviation_amount = cum_actual - cum_budget
        ratio = ratios[key]
        assert ratio is not None

        reasons: list[str] = []
        # 1. 超预算：累计实际 > 累计预算
        if deviation_amount > 0:
            reasons.append(TRIGGER_OVER_BUDGET)
        # 2. 进度异常：|实际进度 - 计划进度| > gap
        actual_progress = cum_actual / budget.amount
        planned_progress = cumulative_ratio(budget.allocation_curve, month)
        progress_gap = Decimal(str(th["threshold.budget.progress_gap"]))
        if abs(actual_progress - planned_progress) > progress_gap:
            reasons.append(TRIGGER_PROGRESS)
        # 3. 异常增长：环比 / 同比（分母为 0 显式跳过，不产生伪异常）
        prev_month = monthly.get(key, {}).get(month - 1, Decimal(0))
        if month > 1 and prev_month > 0 and cur > prev_month:
            mom = (cur - prev_month) / prev_month
            if mom > Decimal(str(th["threshold.budget.growth_mom"])):
                reasons.append(TRIGGER_GROWTH)
        prev_year_amt = prev_year.get(key, Decimal(0))
        if prev_year_amt > 0 and cur > prev_year_amt:
            yoy = (cur - prev_year_amt) / prev_year_amt
            if yoy > Decimal(str(th["threshold.budget.growth_yoy"])):
                reasons.append(TRIGGER_GROWTH)

        # 统计信号（提示级）
        signals: list[tuple[str, Decimal | None, bool]] = []
        # EWMA（月支出率序列）
        rate_series = [x / budget.amount for x in m_series]
        ewma_value, ewma_triggered = ewma_signal(
            rate_series,
            lamb=th["threshold.budget.ewma_lambda"],
            delta=th["threshold.budget.ewma_delta"],
        )
        signals.append(("ewma", ewma_value, ewma_triggered))
        # CUSUM（逐月累计进度）
        actual_series: list[Decimal] = []
        planned_series: list[Decimal] = []
        acc = Decimal(0)
        for t in range(1, month + 1):
            acc += monthly.get(key, {}).get(t, Decimal(0))
            actual_series.append(acc / budget.amount)
            planned_series.append(cumulative_ratio(budget.allocation_curve, t))
        cusum_value, cusum_triggered = cusum_signal(
            actual_series, planned_series, h=th["threshold.budget.cusum_h"]
        )
        signals.append(("cusum", cusum_value, cusum_triggered))
        # MAD（同科目截面）
        mad_value, mad_triggered = mad_z_signal(
            mad_groups.get(cat, []),
            ratio,
            z_threshold=th["threshold.budget.mad_z"],
        )
        signals.append(("mad", mad_value, mad_triggered))

        # 连续期数与升级（同一信号连续 N 期，或同期 >=2 个独立信号）
        prev_consec = prev_sigs.get(key, {})
        consecutive: dict[str, int] = {}
        for stype, _, trig in signals:
            if trig:
                prev_c = prev_consec.get(stype, 0)
                consecutive[stype] = prev_c + 1 if prev_c > 0 else 1
            else:
                consecutive[stype] = 0
        n_need = int(th["threshold.budget.signal_consecutive"])
        triggered_count = sum(1 for _, _, trig in signals if trig)
        upgraded = triggered_count >= 2 or any(
            consecutive[stype] >= n_need for stype, _, trig in signals if trig
        )

        for stype, value, trig in signals:
            result.signals.append(
                SignalResult(
                    signal_type=stype,
                    department_id=dept,
                    project_id=proj,
                    cost_category_id=cat,
                    period=period,
                    value=value,
                    triggered=trig,
                    consecutive_periods=consecutive[stype],
                    upgraded=upgraded,
                )
            )

        level = level_for_ratio(
            ratio, th["threshold.budget.level_low"], th["threshold.budget.level_high"]
        )
        if reasons:
            result.deviations.append(
                DeviationResult(
                    department_id=dept,
                    project_id=proj,
                    cost_category_id=cat,
                    period=period,
                    budget_amount=cum_budget,
                    actual_amount=cum_actual,
                    deviation_amount=deviation_amount,
                    deviation_ratio=ratio,
                    level=level,
                    owner=budget.owner,
                    trigger_reason=",".join(reasons),
                )
            )
        elif upgraded:
            result.deviations.append(
                DeviationResult(
                    department_id=dept,
                    project_id=proj,
                    cost_category_id=cat,
                    period=period,
                    budget_amount=cum_budget,
                    actual_amount=cum_actual,
                    deviation_amount=deviation_amount,
                    deviation_ratio=ratio,
                    level=level,
                    owner=budget.owner,
                    trigger_reason=TRIGGER_STAT_SIGNAL,
                )
            )
    return result
