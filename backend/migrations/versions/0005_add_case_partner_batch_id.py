"""Add cases.partner_batch_id (Woodville/partner batch grouping)

The PCP dispatch tags batch pushes with a stable partner batch id on the
IRL Case envelope. We store it so the outcome postback can echo it back and
results reconcile/group by the partner's batch.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("partner_batch_id", sa.String(length=100), nullable=True))
    op.create_index("ix_cases_partner_batch_id", "cases", ["partner_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_cases_partner_batch_id", table_name="cases")
    op.drop_column("cases", "partner_batch_id")
