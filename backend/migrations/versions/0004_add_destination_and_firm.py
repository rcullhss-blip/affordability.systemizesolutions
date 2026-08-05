"""Add cases.destination_brand_id and jobs.firm (destination branding)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("destination_brand_id", sa.String(length=100), nullable=True))
    op.add_column("jobs", sa.Column("firm", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "firm")
    op.drop_column("cases", "destination_brand_id")
