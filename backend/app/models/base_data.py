"""共享基础层模型：主数据、财务数据、平台数据。

JSON 列使用 `Any`（SQLAlchemy JSON 类型边界，dev-standards 允许的例外）。
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


class SysParam(Base, PrimaryKeyMixin, TimestampMixin):
    """系统参数（阈值/权重/调度节奏，运行时调整带审计）。"""

    __tablename__ = "sys_param"

    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), default="str", nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CostCategory(Base, PrimaryKeyMixin, TimestampMixin):
    """费用科目（共享层单一来源）。"""

    __tablename__ = "cost_category"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cost_category.id"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    invoice_type_map: Mapped[Any] = mapped_column(JSON, nullable=True)
    keyword_map: Mapped[Any] = mapped_column(JSON, nullable=True)


class OrgDepartment(Base, PrimaryKeyMixin, TimestampMixin):
    """部门主数据。"""

    __tablename__ = "org_department"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    manager: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Project(Base, PrimaryKeyMixin, TimestampMixin):
    """项目主数据。"""

    __tablename__ = "project"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_department.id"), nullable=False, index=True
    )
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Budget(Base, PrimaryKeyMixin, TimestampMixin):
    """预算（部门×项目×科目×期间四维度唯一）。"""

    __tablename__ = "budget"

    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_department.id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project.id"), nullable=False, index=True
    )
    cost_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cost_category.id"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    allocation_curve: Mapped[Any] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "project_id",
            "cost_category_id",
            "period",
            name="uq_budget_dim_period",
        ),
    )


class BudgetAdjustment(Base, PrimaryKeyMixin):
    """预算调整记录（留痕）。"""

    __tablename__ = "budget_adjustment"

    budget_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("budget.id", ondelete="CASCADE"), nullable=False, index=True
    )
    before_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    after_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    allocation_curve: Mapped[Any] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    adjusted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ExpenseLedger(Base, PrimaryKeyMixin, TimestampMixin):
    """支出台账（实际支出单一权威来源，报销通过时写入 / 可导入）。"""

    __tablename__ = "expense_ledger"

    source: Mapped[str] = mapped_column(String(16), nullable=False)  # reimb / import
    cost_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cost_category.id"), nullable=False, index=True
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_department.id"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("project.id"), nullable=True, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ref_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class Customer(Base, PrimaryKeyMixin, TimestampMixin):
    """客户主数据。"""

    __tablename__ = "customer"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rating: Mapped[str | None] = mapped_column(String(8), nullable=True)
    credit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class Contract(Base, PrimaryKeyMixin, TimestampMixin):
    """合同台账。"""

    __tablename__ = "contract"

    contract_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment_term: Mapped[int] = mapped_column(Integer, default=30, nullable=False)  # 账期（天）
    status: Mapped[str] = mapped_column(String(16), default="executing", nullable=False)


class AuditLog(Base, PrimaryKeyMixin):
    """审计日志（登录、参数/阈值变更、报销关键操作）。"""

    __tablename__ = "audit_log"

    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before: Mapped[Any] = mapped_column(JSON, nullable=True)
    after: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class FileStore(Base, PrimaryKeyMixin, TimestampMixin):
    """文件物理存储记录。"""

    __tablename__ = "file_store"

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class Attachment(Base, PrimaryKeyMixin, TimestampMixin):
    """通用附件元数据（报销/导入通用）。"""

    __tablename__ = "attachment"

    file_store_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_store.id"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False)  # invoice/travel/approval
    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
