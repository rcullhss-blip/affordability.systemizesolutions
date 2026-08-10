"""Reconcile schema drift: jobs.spot_check_* + job_feedback

These existed on the long-lived Railway DB (added ad-hoc over time) but were
never captured in a migration, so a fresh DB built purely from 0001..0005 was
missing them — every query that loads a Job 500'd. Additive only.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("spot_check_required", sa.Boolean(),
                                    nullable=False, server_default=sa.text("false")))
    op.add_column("jobs", sa.Column("spot_check_reviewed", sa.Boolean(),
                                    nullable=False, server_default=sa.text("false")))
    op.create_table(
        "job_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True, index=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_table("job_feedback")
    op.drop_column("jobs", "spot_check_reviewed")
    op.drop_column("jobs", "spot_check_required")
