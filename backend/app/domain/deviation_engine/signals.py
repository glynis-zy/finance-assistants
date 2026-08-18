"""统计辅助信号（纯 Python，无重框架）。

- EWMA：平滑"期望支出率"，捕捉缓慢漂移
- CUSUM：对持续小幅偏移敏感的累积检器（高侧）
- MAD 修正 Z-score：同类（同科目）中偏离同侪的离群者

信号只输出提示（triggered），升级判定在 engine 层完成。
分母为 0 / 样本不足等不可靠场景显式跳过，不产生除零或伪信号。
"""

from __future__ import annotations

from decimal import Decimal

EPSILON = Decimal("1e-9")


def median(values: list[Decimal]) -> Decimal | None:
    """中位数（空列表返回 None）。"""
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


def ewma_signal(
    series: list[Decimal],
    *,
    lamb: float = 0.3,
    delta: float = 0.3,
) -> tuple[Decimal | None, bool]:
    """EWMA 信号。

    对月支出率序列递推 e_t = λ·x_t + (1-λ)·e_{t-1}（e_1 = x_1），
    当前月 x_t 相对前值 e_{t-1} 偏差超过 delta 比例 → 触发。
    序列不足 2 期无法比较 → 不触发。
    """
    if len(series) < 2:
        return (series[-1] if series else None), False
    prev = series[0]
    for i in range(1, len(series)):
        x = series[i]
        e = Decimal(str(lamb)) * x + (Decimal(1) - Decimal(str(lamb))) * prev
        if i == len(series) - 1:
            base = max(abs(prev), EPSILON)
            triggered = abs(x - prev) > Decimal(str(delta)) * base
            return x, triggered
        prev = e
    return (series[-1] if series else None), False


def cusum_signal(
    actual_progress: list[Decimal],
    planned_progress: list[Decimal],
    *,
    h: float = 0.1,
) -> tuple[Decimal | None, bool]:
    """CUSUM 信号（高侧）。

    S_t = max(0, S_{t-1} + (实际累计进度_t - 计划累计进度_t))，S_0 = 0。
    S_t > h（占年度预算的比例）→ 触发。序列长度须一致且 >= 1。
    """
    if not actual_progress or len(actual_progress) != len(planned_progress):
        return None, False
    s = Decimal(0)
    threshold = Decimal(str(h))
    for a, p in zip(actual_progress, planned_progress, strict=True):
        s = max(Decimal(0), s + (a - p))
    return s, s > threshold


def mad_z_signal(
    values: list[Decimal],
    target: Decimal,
    *,
    z_threshold: float = 3.0,
) -> tuple[Decimal | None, bool]:
    """MAD 修正 Z-score 离群检测。

    z = (x - median) / (1.4826 × MAD)；|z| > 阈值 → 触发。
    样本 < 3 或 MAD 为 0 且 x == median → 无法可靠判定，不触发。
    """
    if len(values) < 3:
        return None, False
    med = median(values)
    if med is None:
        return None, False
    deviations = [abs(v - med) for v in values]
    mad = median(deviations)
    if mad is None:
        return None, False
    scale = Decimal("1.4826") * mad
    if scale <= EPSILON:
        return None, False
    z = (target - med) / scale
    return z, abs(z) > Decimal(str(z_threshold))
