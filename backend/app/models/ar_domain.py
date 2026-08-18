"""应收预警域模型（3.3.3 私有）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ReceivableStatus
from app.models.mixins import PrimaryKeyMixin, TimestampMixin, utcnow


class ArReceivable(Base, PrimaryKeyMixin, TimestampMixin):
    """应收账款（status 由服务端按累计到账维护）。"""

    __tablename__ = "ar_receivable"

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=False, index=True
    )
    contract_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contract.id"), nullable=True, index=True
    )
    invoice_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ReceivableStatus.OPEN.value, nullable=False, index=True
    )


class ArPayment(Base, PrimaryKeyMixin):
    """回款记录。"""

    __tablename__ = "ar_payment"

    receivable_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ar_receivable.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CollectionRecord(Base, PrimaryKeyMixin):
    """催收记录。"""

    __tablename__ = "collection_record"

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=False, index=True
    )
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str | None] = mapped_column(String(256), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(256), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ArRiskScore(Base, PrimaryKeyMixin):
    """应收风险评分结果（每客户每评分日一条，同日 upsert 幂等）。"""

    __tablename__ = "ar_risk_score"

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=False, index=True
    )
    score_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    factors: Mapped[Any] = mapped_column(JSON, nullable=True)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_overdue_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overdue_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("customer_id", "score_date", name="uq_ar_risk_customer_date"),
    )


class ArRiskRun(Base, PrimaryKeyMixin):
    """应收全量评分任务运行状态（周期任务结果落 DB，可查最近一次运行）。"""

    __tablename__ = "ar_risk_run"

    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    # queued/running/done/failed
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    high_risk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
