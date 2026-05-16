"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2025-05-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("total_reports", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("green_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amber_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("red_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assessments_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locs_generated", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("matter_ref", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_clients_matter_ref", "clients", ["matter_ref"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("batches.id"), nullable=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("traffic_light", sa.String(10), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("s3_raw_key", sa.Text(), nullable=True),
        sa.Column("s3_assessment_key", sa.Text(), nullable=True),
        sa.Column("normalised_data", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_batch_id", "jobs", ["batch_id"])

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("lender_name", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(50), nullable=True),
        sa.Column("opened_date", sa.Date(), nullable=True),
        sa.Column("balance", sa.Float(), nullable=True),
        sa.Column("credit_limit", sa.Float(), nullable=True),
        sa.Column("utilisation_pct", sa.Float(), nullable=True),
        sa.Column("status", sa.String(100), nullable=True),
        sa.Column("payment_history", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_accounts_lender_name", "accounts", ["lender_name"])

    op.create_table(
        "lender_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("lender_name", sa.String(255), nullable=False),
        sa.Column("traffic_light", sa.String(10), nullable=False),
        sa.Column("claim_score", sa.Float(), nullable=True),
        sa.Column("risk_flags", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("loc_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("s3_loc_key", sa.Text(), nullable=True),
        sa.Column("delivery_status", sa.String(20), nullable=False, server_default="PENDING"),
    )
    op.create_index("ix_lender_results_lender_name", "lender_results", ["lender_name"])
    op.create_index("ix_lender_results_job_id", "lender_results", ["job_id"])


def downgrade() -> None:
    op.drop_table("lender_results")
    op.drop_table("accounts")
    op.drop_table("jobs")
    op.drop_table("clients")
    op.drop_table("batches")
