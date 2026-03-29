"""add autoresearch tables

Revision ID: a1b2c3d4e5f6
Revises: 6d734d412218
Create Date: 2026-03-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "6d734d412218"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autoresearch_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("completed_iterations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("best_brier", sa.Float(), nullable=True),
        sa.Column("best_sharpe", sa.Float(), nullable=True),
        sa.Column("best_iteration", sa.Integer(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )

    op.create_table(
        "autoresearch_iterations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("autoresearch_runs.id"), nullable=False),
        sa.Column("iteration_num", sa.Integer(), nullable=False),
        sa.Column("strategy_code", sa.Text(), nullable=False),
        sa.Column("hypothesis", sa.Text(), server_default="", nullable=False),
        sa.Column("train_brier", sa.Float(), nullable=True),
        sa.Column("val_brier", sa.Float(), nullable=True),
        sa.Column("train_sharpe", sa.Float(), nullable=True),
        sa.Column("val_sharpe", sa.Float(), nullable=True),
        sa.Column("num_trades", sa.Integer(), server_default="0", nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("accepted", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("commit_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_autoresearch_iterations_run_id",
        "autoresearch_iterations",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autoresearch_iterations_run_id", table_name="autoresearch_iterations")
    op.drop_table("autoresearch_iterations")
    op.drop_table("autoresearch_runs")
