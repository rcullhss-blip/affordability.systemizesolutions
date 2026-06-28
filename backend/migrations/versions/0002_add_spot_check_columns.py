"""Add spot_check columns to jobs

The Job model gained spot_check_required / spot_check_reviewed but no migration
was ever created, so a database built purely from migrations (e.g. a fresh
deploy) was missing them and inserts into jobs failed with UndefinedColumn.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent guards so this also applies cleanly to databases where the
    # columns were already added out-of-band (e.g. the existing V1 production DB).
    op.execute(
        'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS spot_check_required '
        'BOOLEAN NOT NULL DEFAULT false'
    )
    op.execute(
        'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS spot_check_reviewed '
        'BOOLEAN NOT NULL DEFAULT false'
    )


def downgrade() -> None:
    op.drop_column("jobs", "spot_check_reviewed")
    op.drop_column("jobs", "spot_check_required")
