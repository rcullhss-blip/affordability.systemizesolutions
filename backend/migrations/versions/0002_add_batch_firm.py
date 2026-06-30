"""Add firm column to batches (per-firm LOC branding)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-30
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE batches ADD COLUMN IF NOT EXISTS firm "
        "VARCHAR(50) NOT NULL DEFAULT 'first_legal'"
    )


def downgrade() -> None:
    op.drop_column("batches", "firm")
