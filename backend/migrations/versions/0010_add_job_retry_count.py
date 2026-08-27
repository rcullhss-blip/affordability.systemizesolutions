"""Add jobs.retry_count — how many times the watchdog has auto-retried a
transient failure, so it retries once and then leaves the job FAILED for a human.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "jobs",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("jobs", "retry_count")
