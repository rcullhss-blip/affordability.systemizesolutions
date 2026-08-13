"""Add jobs.s3_credit_report_key — store the generated credit-report PDF so the
partner tracker can link a PDF instead of the raw report JSON.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("s3_credit_report_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "s3_credit_report_key")
