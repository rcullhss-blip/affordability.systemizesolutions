"""Add cases.cfa — the CFA (Conditional Fee Agreement) block captured on the
/irl-case payload, surfaced as the Ryans tracker's CFA columns so the solicitor
imports the CFA in one pass (retires the ack -> CFA-reply email step).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("cfa", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "cfa")
