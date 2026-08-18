"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-18

Stage 1 初始迁移：一次性建全量冻结表（30 张），后续 Stage 用 autogenerate 增量。
"""
import sqlalchemy as sa
from alembic import op

import app.models  # noqa: F401
from app.db.base import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
