"""ORM 公共列 mixin。"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """返回当前 UTC 时间（带时区）。"""
    return datetime.now(UTC)


class PrimaryKeyMixin:
    """int64 自增主键（docs/api.md §0.3）。

    MySQL 渲染为 BIGINT；SQLite 渲染为 INTEGER（SQLite 仅对精确 INTEGER 类型
    做 rowid 别名并自增，故需 with_variant 切换，否则 NOT NULL 不自增）。
    """

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )


class TimestampMixin:
    """创建/更新时间戳，统一 UTC。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
