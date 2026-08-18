"""预算监控域模型（3.3.2 私有）。

Stage 3 口径修正：正式偏差按 部门×项目×科目×期间(YYYY-MM) 存储，
不设 dimension_type/dimension_id 作为事实记录的唯一业务维度；
汇总展示在查询层按维度聚合（docs/requirements.md §6.3）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import PrimaryKeyMixin, TimestampMixin, utcnow


class BudgetDeviation(Base, PrimaryKeyMixin, TimestampMixin):
    """预算偏差事实记录（部门×项目×科目×期间唯一，level 独立枚举 low/medium/high）。"""

    __tablename__ = "budget_deviation"

    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_department.id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project.id"), nullable=False, index=True
    )
    cost_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cost_category.id"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    deviation_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    deviation_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # over_budget/progress/growth/stat_signal（可逗号合并）
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "project_id",
            "cost_category_id",
            "period",
            name="uq_bd_dim_period",
        ),
    )


class BudgetSnapshot(Base, PrimaryKeyMixin):
    """预算监控任务快照（每次任务一行，同核算期可更新，可回溯）。"""

    __tablename__ = "budget_snapshot"

    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="done", nullable=False
    )  # queued/running/done/failed
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    snapshot_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    deviation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class StatSignal(Base, PrimaryKeyMixin):
    """统计信号（EWMA/CUSUM/MAD，提示级；连续期数用于升级判定）。"""

    __tablename__ = "stat_signal"

    signal_type: Mapped[str] = mapped_column(String(16), nullable=False)  # ewma/cusum/mad
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_department.id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project.id"), nullable=False, index=True
    )
    cost_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cost_category.id"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consecutive_periods: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
