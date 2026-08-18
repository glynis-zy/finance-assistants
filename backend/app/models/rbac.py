"""RBAC 模型：用户、角色、权限及其关联表。

表名沿用 requirements.md §6 冻结清单（单数）。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PrimaryKeyMixin, TimestampMixin


class SysUser(Base, PrimaryKeyMixin, TimestampMixin):
    """系统用户。"""

    __tablename__ = "sys_user"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list[SysRole]] = relationship(
        secondary="user_role", back_populates="users", lazy="selectin"
    )


class SysRole(Base, PrimaryKeyMixin, TimestampMixin):
    """角色。"""

    __tablename__ = "sys_role"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    users: Mapped[list[SysUser]] = relationship(secondary="user_role", back_populates="roles")
    permissions: Mapped[list[SysPermission]] = relationship(
        secondary="role_permission", back_populates="roles", lazy="selectin"
    )


class SysPermission(Base, PrimaryKeyMixin, TimestampMixin):
    """权限码（domain:action）。"""

    __tablename__ = "sys_permission"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    roles: Mapped[list[SysRole]] = relationship(
        secondary="role_permission", back_populates="permissions"
    )


class UserRole(Base):
    """用户-角色关联（联合主键）。"""

    __tablename__ = "user_role"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_role.id", ondelete="CASCADE"), primary_key=True
    )


class RolePermission(Base):
    """角色-权限关联（联合主键）。"""

    __tablename__ = "role_permission"

    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_permission.id", ondelete="CASCADE"), primary_key=True
    )
