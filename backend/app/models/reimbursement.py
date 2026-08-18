"""报销域模型（3.3.1 私有）。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ReimbursementStatus, TaskStatus
from app.models.mixins import PrimaryKeyMixin, TimestampMixin, utcnow


class Reimbursement(Base, PrimaryKeyMixin, TimestampMixin):
    """报销单主表（状态机：draft → pending → approved/returned/manual_review）。"""

    __tablename__ = "reimbursement"

    no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    applicant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=False, index=True
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_department.id"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("project.id"), nullable=True, index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ReimbursementStatus.DRAFT.value, nullable=False, index=True
    )
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    return_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[ReimbursementItem]] = relationship(
        back_populates="reimbursement", cascade="all, delete-orphan"
    )


class ReimbursementItem(Base, PrimaryKeyMixin):
    """报销明细。"""

    __tablename__ = "reimbursement_item"

    reimbursement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reimbursement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cost_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cost_category.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    invoice_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )  # 普通索引，非 UNIQUE（冻结口径）
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    reimbursement: Mapped[Reimbursement] = relationship(back_populates="items")


class ReimbursementAttachment(Base, PrimaryKeyMixin):
    """报销单附件关联。"""

    __tablename__ = "reimbursement_attachment"

    reimbursement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reimbursement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attachment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attachment.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class DocParseResult(Base, PrimaryKeyMixin, TimestampMixin):
    """附件 OCR/LLM 解析结果快照（JSON + 置信度）。"""

    __tablename__ = "doc_parse_result"

    attachment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attachment.id"), nullable=False, index=True
    )
    reimbursement_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("reimbursement.id"), nullable=True, index=True
    )
    doc_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    parsed_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)


class AuditTask(Base, PrimaryKeyMixin, TimestampMixin):
    """审核任务状态（异步轮询）。"""

    __tablename__ = "audit_task"

    reimbursement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reimbursement.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=TaskStatus.QUEUED.value, nullable=False, index=True
    )
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)


class AuditConclusion(Base, PrimaryKeyMixin, TimestampMixin):
    """审核结论（结论、推荐科目、校验明细、风险项、报告）。"""

    __tablename__ = "audit_conclusion"

    reimbursement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reimbursement.id"), nullable=False, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("audit_task.id"), nullable=True
    )
    result: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # approved/returned/manual_review
    recommended_category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cost_category.id"), nullable=True
    )
    check_items: Mapped[Any] = mapped_column(JSON, nullable=True)
    risk_items: Mapped[Any] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
