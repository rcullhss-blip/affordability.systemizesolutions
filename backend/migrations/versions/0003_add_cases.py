"""Add cases table (IRL case intake from the PCP platform)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_reference", sa.String(length=100), nullable=False),
        sa.Column("bosh_reference", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="boshhh"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="QUEUED"),
        sa.Column("triage", sa.JSON(), nullable=True),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("client_dob", sa.Date(), nullable=True),
        sa.Column("client_postcode", sa.String(length=20), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("s3_raw_key", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("traffic_light", sa.String(length=10), nullable=True),
        sa.Column("claim_value", sa.Float(), nullable=True),
        sa.Column("outcome_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("outcome_sent_at", sa.DateTime(), nullable=True),
        sa.Column("outcome_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    # Unique => idempotency on lead_reference (retries never duplicate)
    op.create_index("ix_cases_lead_reference", "cases", ["lead_reference"], unique=True)
    op.create_index("ix_cases_status", "cases", ["status"])
    op.create_index("ix_cases_job_id", "cases", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_cases_job_id", table_name="cases")
    op.drop_index("ix_cases_status", table_name="cases")
    op.drop_index("ix_cases_lead_reference", table_name="cases")
    op.drop_table("cases")
