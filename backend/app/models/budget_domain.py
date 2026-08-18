"""预算监控域模型（3.3.2 私有）。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import PrimaryKeyMixin, TimestampMixin, utcnow


class BudgetDeviation(Base, PrimaryKeyMixin, TimestampMixin):
    """预算偏差明细（level 独立枚举：low/medium/high）。"""

    __tablename__ = "budget_deviation"

    dimension_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    dimension_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    dimension_name: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    deviation_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    deviation_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)


class BudgetSnapshot(Base, PrimaryKeyMixin):
    """预算监控任务快照（全量对比结果，可回溯）。"""

    __tablename__ = "budget_snapshot"

    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    snapshot_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    deviation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class StatSignal(Base, PrimaryKeyMixin):
    """统计信号（EWMA/CUSUM/MAD，提示级）。"""

    __tablename__ = "stat_signal"

    signal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    dimension_type: Mapped[str] = mapped_column(String(16), nullable=False)
    dimension_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
