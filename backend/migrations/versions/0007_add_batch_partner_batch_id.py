"""Add batches.partner_batch_id — group a tagged bulk run (e.g. Woodville) into
one Batch so it runs as a single batch, not scattered individual cases.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("batches", sa.Column("partner_batch_id", sa.String(length=100), nullable=True))
    op.create_index("ix_batches_partner_batch_id", "batches", ["partner_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_batches_partner_batch_id", table_name="batches")
    op.drop_column("batches", "partner_batch_id")
