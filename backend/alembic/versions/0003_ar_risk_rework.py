"""ar risk rework

Revision ID: 0003_ar_risk_rework
Revises: 0002_budget_year_rework
Create Date: 2026-08-18

Stage 4 应收域修正（条件化迁移，新旧库均幂等）：
- ar_risk_score：+ score_date（每客户每评分日一条）、+ overdue_amount；唯一约束 uq_ar_risk_customer_date
- 新增 ar_risk_run 表（周期任务状态，结果落 DB 可查）
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_ar_risk_rework"
down_revision = "0002_budget_year_rework"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def _has_constraint(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(uc["name"] == name for uc in insp.get_unique_constraints(table))


def upgrade() -> None:
    cols = _columns("ar_risk_score")
    with op.batch_alter_table("ar_risk_score") as batch:
        if "score_date" not in cols:
            batch.add_column(sa.Column("score_date", sa.Date(), nullable=True))
        if "overdue_amount" not in cols:
            batch.add_column(sa.Column("overdue_amount", sa.Numeric(18, 2), nullable=True))
    if not _has_constraint("ar_risk_score", "uq_ar_risk_customer_date"):
        with op.batch_alter_table("ar_risk_score") as batch:
            batch.create_unique_constraint(
                "uq_ar_risk_customer_date", ["customer_id", "score_date"]
            )

    if not sa.inspect(op.get_bind()).has_table("ar_risk_run"):
        op.create_table(
            "ar_risk_run",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("customer_count", sa.Integer(), nullable=False),
            sa.Column("high_risk_count", sa.Integer(), nullable=False),
            sa.Column("error", sa.String(512), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("ar_risk_run")
    cols = _columns("ar_risk_score")
    if "score_date" in cols or "overdue_amount" in cols:
        with op.batch_alter_table("ar_risk_score") as batch:
            if _has_constraint("ar_risk_score", "uq_ar_risk_customer_date"):
                batch.drop_constraint("uq_ar_risk_customer_date", type_="unique")
            if "overdue_amount" in cols:
                batch.drop_column("overdue_amount")
            if "score_date" in cols:
                batch.drop_column("score_date")
