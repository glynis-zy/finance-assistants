"""budget year rework

Revision ID: 0002_budget_year_rework
Revises: 0001_initial
Create Date: 2026-08-18

Stage 3 预算口径修正（条件化迁移，旧库执行结构转换、新库幂等跳过）：
- budget.period(YYYY-MM) → budget.budget_year(YYYY)，唯一约束同步
- budget_deviation：dimension_type/dimension_id/dimension_name → 三业务维度
  department_id/project_id/cost_category_id + trigger_reason + 唯一约束
- stat_signal：dimension_type/dimension_id → 三业务维度 + consecutive_periods
- budget_snapshot：+ status / error
- alert：+ unique_key（幂等键）

注：0001 以 `create_all(Model 元数据)` 建表，全新库已按修正后 Model 建表，
因此本迁移对"列已存在/不存在"做条件判断，保证两种基线都可升级。
SQLite 用 batch_alter_table 重建表；MySQL 走标准 ALTER。
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_budget_year_rework"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def _has_constraint(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    for uc in insp.get_unique_constraints(table):
        if uc["name"] == name:
            return True
    return False


def upgrade() -> None:
    # budget: period → budget_year（仅旧结构）
    budget_cols = _columns("budget")
    if "period" in budget_cols:
        with op.batch_alter_table("budget") as batch:
            batch.alter_column("period", new_column_name="budget_year", type_=sa.String(4))
    if not _has_constraint("budget", "uq_budget_dim_year"):
        with op.batch_alter_table("budget") as batch:
            if _has_constraint("budget", "uq_budget_dim_period"):
                batch.drop_constraint("uq_budget_dim_period", type_="unique")
            batch.create_unique_constraint(
                "uq_budget_dim_year",
                ["department_id", "project_id", "cost_category_id", "budget_year"],
            )

    # budget_deviation: 三维度 + trigger_reason + 唯一约束（仅旧结构）
    bd_cols = _columns("budget_deviation")
    if "dimension_type" in bd_cols:
        with op.batch_alter_table("budget_deviation") as batch:
            batch.drop_index("ix_budget_deviation_dimension_type")
            batch.drop_index("ix_budget_deviation_dimension_id")
            batch.drop_column("dimension_type")
            batch.drop_column("dimension_id")
            batch.drop_column("dimension_name")
            batch.add_column(sa.Column("department_id", sa.BigInteger(), nullable=True))
            batch.add_column(sa.Column("project_id", sa.BigInteger(), nullable=True))
            batch.add_column(sa.Column("cost_category_id", sa.BigInteger(), nullable=True))
            batch.add_column(sa.Column("trigger_reason", sa.String(64), nullable=True))
            batch.create_unique_constraint(
                "uq_bd_dim_period",
                ["department_id", "project_id", "cost_category_id", "period"],
            )
    elif not _has_constraint("budget_deviation", "uq_bd_dim_period"):
        with op.batch_alter_table("budget_deviation") as batch:
            batch.create_unique_constraint(
                "uq_bd_dim_period",
                ["department_id", "project_id", "cost_category_id", "period"],
            )

    # stat_signal: 三维度 + consecutive_periods（仅旧结构）
    ss_cols = _columns("stat_signal")
    if "dimension_id" in ss_cols:
        with op.batch_alter_table("stat_signal") as batch:
            batch.drop_index("ix_stat_signal_dimension_id")
            batch.drop_column("dimension_type")
            batch.drop_column("dimension_id")
            batch.add_column(sa.Column("department_id", sa.BigInteger(), nullable=True))
            batch.add_column(sa.Column("project_id", sa.BigInteger(), nullable=True))
            batch.add_column(sa.Column("cost_category_id", sa.BigInteger(), nullable=True))
            batch.add_column(
                sa.Column("consecutive_periods", sa.Integer(), nullable=False, server_default="0")
            )

    # budget_snapshot: status / error（新库已有则跳过）
    snap_cols = _columns("budget_snapshot")
    with op.batch_alter_table("budget_snapshot") as batch:
        if "status" not in snap_cols:
            batch.add_column(
                sa.Column("status", sa.String(16), nullable=False, server_default="done")
            )
        if "error" not in snap_cols:
            batch.add_column(sa.Column("error", sa.String(512), nullable=True))

    # alert: unique_key（新库已有则跳过）
    alert_cols = _columns("alert")
    if "unique_key" not in alert_cols:
        with op.batch_alter_table("alert") as batch:
            batch.add_column(sa.Column("unique_key", sa.String(128), nullable=True))
            batch.create_unique_constraint("uq_alert_unique_key", ["unique_key"])


def downgrade() -> None:
    alert_cols = _columns("alert")
    if "unique_key" in alert_cols:
        with op.batch_alter_table("alert") as batch:
            batch.drop_constraint("uq_alert_unique_key", type_="unique")
            batch.drop_column("unique_key")

    snap_cols = _columns("budget_snapshot")
    with op.batch_alter_table("budget_snapshot") as batch:
        if "error" in snap_cols:
            batch.drop_column("error")
        if "status" in snap_cols:
            batch.drop_column("status")

    ss_cols = _columns("stat_signal")
    if "dimension_id" not in ss_cols and "department_id" in ss_cols:
        with op.batch_alter_table("stat_signal") as batch:
            batch.drop_column("consecutive_periods")
            batch.drop_column("cost_category_id")
            batch.drop_column("project_id")
            batch.drop_column("department_id")
            batch.add_column(sa.Column("dimension_id", sa.BigInteger(), nullable=True))
            batch.add_column(sa.Column("dimension_type", sa.String(16), nullable=True))

    bd_cols = _columns("budget_deviation")
    if "dimension_type" not in bd_cols and "department_id" in bd_cols:
        with op.batch_alter_table("budget_deviation") as batch:
            batch.drop_constraint("uq_bd_dim_period", type_="unique")
            batch.drop_column("trigger_reason")
            batch.drop_column("cost_category_id")
            batch.drop_column("project_id")
            batch.drop_column("department_id")
            batch.add_column(sa.Column("dimension_name", sa.String(64), nullable=True))
            batch.add_column(sa.Column("dimension_id", sa.BigInteger(), nullable=True))
            batch.add_column(sa.Column("dimension_type", sa.String(16), nullable=True))

    budget_cols = _columns("budget")
    if "period" not in budget_cols and "budget_year" in budget_cols:
        with op.batch_alter_table("budget") as batch:
            batch.drop_constraint("uq_budget_dim_year", type_="unique")
        with op.batch_alter_table("budget") as batch:
            batch.alter_column("budget_year", new_column_name="period", type_=sa.String(7))
