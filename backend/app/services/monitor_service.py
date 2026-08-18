"""预算监控服务（3.3.2）：DB 装配 → deviation_engine → 幂等持久化。

幂等策略：
- budget_deviation：同维度同期已存在 → 更新（不新增），记录数不因重跑增长
- stat_signal：同核算期先删旧再全量重建（同期的信号状态重算一致）
- alert：unique_key（budget:{period}:{dept}:{proj}:{cat}）已存在 → 跳过
- budget_snapshot：同 period 更新（status 迁移 running → done/failed）
"""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.deviation_engine import compute
from app.domain.deviation_engine.engine import DEFAULT_THRESHOLDS
from app.domain.deviation_engine.types import (
    BudgetInput,
    LedgerRow,
    MonitorResult,
)
from app.models.alert import Alert
from app.models.base_data import Budget, ExpenseLedger, OrgDepartment, SysParam
from app.models.budget_domain import BudgetDeviation, BudgetSnapshot, StatSignal


def _load_thresholds(db: Session) -> dict[str, float]:
    """从 sys_param 读 threshold.budget.* 阈值（缺失/非法用默认值）。"""
    out: dict[str, float] = dict(DEFAULT_THRESHOLDS)
    rows = db.scalars(select(SysParam).where(SysParam.key.like("threshold.budget.%"))).all()
    for p in rows:
        try:
            out[p.key] = float(p.value)
        except ValueError:
            continue
    return out


def _prev_period(period: str) -> str:
    """上一个月核算期（2026-01 → 2025-12）。"""
    year, month = int(period[:4]), int(period[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _load_prev_signals(db: Session, period: str) -> dict[tuple[int, int, int], dict[str, int]]:
    """上期统计信号连续期数（升级判定输入）。"""
    prev = _prev_period(period)
    out: dict[tuple[int, int, int], dict[str, int]] = {}
    rows = db.scalars(select(StatSignal).where(StatSignal.period == prev)).all()
    for s in rows:
        out.setdefault((s.department_id, s.project_id, s.cost_category_id), {})[s.signal_type] = (
            s.consecutive_periods
        )
    return out


def _persist(db: Session, period: str, result: MonitorResult) -> dict[str, object]:
    """写入偏差/信号/快照/预警（幂等），返回统计摘要。"""
    # stat_signal：同期全量重建
    db.execute(delete(StatSignal).where(StatSignal.period == period))
    for sig in result.signals:
        db.add(
            StatSignal(
                signal_type=sig.signal_type,
                department_id=sig.department_id,
                project_id=sig.project_id,
                cost_category_id=sig.cost_category_id,
                period=period,
                value=sig.value,
                triggered=sig.triggered,
                consecutive_periods=sig.consecutive_periods,
            )
        )

    deviation_count = 0
    alert_created = 0
    for dev in result.deviations:
        existing = db.scalar(
            select(BudgetDeviation).where(
                BudgetDeviation.department_id == dev.department_id,
                BudgetDeviation.project_id == dev.project_id,
                BudgetDeviation.cost_category_id == dev.cost_category_id,
                BudgetDeviation.period == period,
            )
        )
        if existing is None:
            existing = BudgetDeviation(
                department_id=dev.department_id,
                project_id=dev.project_id,
                cost_category_id=dev.cost_category_id,
                period=period,
            )
            db.add(existing)
        existing.budget_amount = dev.budget_amount
        existing.actual_amount = dev.actual_amount
        existing.deviation_amount = dev.deviation_amount
        existing.deviation_ratio = dev.deviation_ratio
        existing.level = dev.level
        existing.owner = dev.owner
        existing.trigger_reason = dev.trigger_reason
        deviation_count += 1

        # high 且超支方向 → 预警（unique_key 幂等）
        if dev.level == "high" and dev.deviation_amount > 0:
            unique_key = (
                f"budget:{period}:{dev.department_id}:{dev.project_id}:{dev.cost_category_id}"
            )
            exists = db.scalar(select(Alert.id).where(Alert.unique_key == unique_key))
            if exists is None:
                db.add(
                    Alert(
                        alert_type="budget",
                        level="critical",
                        unique_key=unique_key,
                        summary=(
                            f"预算高偏差 {period} "
                            f"部门{dev.department_id}/项目{dev.project_id}/科目{dev.cost_category_id}"
                        ),
                        detail={
                            "period": period,
                            "department_id": dev.department_id,
                            "project_id": dev.project_id,
                            "cost_category_id": dev.cost_category_id,
                            "budget_amount": str(dev.budget_amount),
                            "actual_amount": str(dev.actual_amount),
                            "deviation_amount": str(dev.deviation_amount),
                            "deviation_ratio": str(dev.deviation_ratio),
                            "level": dev.level,
                            "trigger_reason": dev.trigger_reason,
                        },
                    )
                )
                alert_created += 1

    # snapshot：同 period 更新
    snapshot = db.scalar(select(BudgetSnapshot).where(BudgetSnapshot.period == period))
    if snapshot is None:
        snapshot = BudgetSnapshot(period=period, deviation_count=deviation_count)
        db.add(snapshot)
    snapshot.status = "done"
    snapshot.error = None
    snapshot.deviation_count = deviation_count
    snapshot.snapshot_json = {
        "period": period,
        "budgets_checked": result.budgets_checked,
        "deviation_count": deviation_count,
        "signal_count": len(result.signals),
        "alert_created": alert_created,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    db.commit()
    return {
        "period": period,
        "budgets_checked": result.budgets_checked,
        "deviations": deviation_count,
        "signals": len(result.signals),
        "alerts_created": alert_created,
    }


def run_monitor(db: Session, period: str | None = None) -> dict[str, object]:
    """执行一次预算监控（预算+台账 → 引擎 → 偏差/信号/快照/预警）。"""
    period = period or datetime.now(UTC).strftime("%Y-%m")
    year = period[:4]
    thresholds = _load_thresholds(db)

    dept_map = {d.id: d for d in db.scalars(select(OrgDepartment)).all()}
    budgets: list[BudgetInput] = []
    for b in db.scalars(select(Budget).where(Budget.budget_year == year)).all():
        dept = dept_map.get(b.department_id)
        budgets.append(
            BudgetInput(
                department_id=b.department_id,
                project_id=b.project_id,
                cost_category_id=b.cost_category_id,
                budget_year=b.budget_year,
                amount=b.amount,
                allocation_curve=b.allocation_curve,
                owner=dept.manager if dept else None,
            )
        )

    rows = db.scalars(select(ExpenseLedger)).all()
    ledger: list[LedgerRow] = []
    for e in rows:
        if e.project_id is None:
            continue  # 无项目支出不参与预算监控维度
        ledger.append(
            LedgerRow(
                period=e.period,
                department_id=e.department_id,
                project_id=e.project_id,
                cost_category_id=e.cost_category_id,
                amount=e.amount,
            )
        )

    prev_signals = _load_prev_signals(db, period)
    result = compute(period, budgets, ledger, thresholds, prev_signals)
    return _persist(db, period, result)


def latest_status(db: Session) -> dict[str, object] | None:
    """最近一次监控快照（GET /api/monitor/status 数据源）。"""
    snapshot = db.scalar(select(BudgetSnapshot).order_by(BudgetSnapshot.period.desc()).limit(1))
    if snapshot is None:
        return None
    return {
        "last_run_at": snapshot.created_at,
        "status": snapshot.status,
        "snapshot": {
            "id": snapshot.id,
            "period": snapshot.period,
            "deviation_count": snapshot.deviation_count,
        },
    }
