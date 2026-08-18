"""预警域模型（三助手共用）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import PrimaryKeyMixin, utcnow


class Alert(Base, PrimaryKeyMixin):
    """预警（类型/级别/摘要/详情/产生任务/已读）。"""

    __tablename__ = "alert"

    alert_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # budget / ar
    level: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # info/warning/critical
    summary: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[Any] = mapped_column(JSON, nullable=True)
    source_task_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class Notification(Base, PrimaryKeyMixin):
    """投递记录（通道/状态/重试，幂等）。"""

    __tablename__ = "notification"

    alert_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("alert.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)  # inapp/email/wecom/dingtalk
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
