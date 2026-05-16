from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Date, Text,
    ForeignKey, JSON, Enum as SAEnum, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
from app.models.enums import TrafficLight, JobStatus, DeliveryStatus, AccountType


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    total_reports: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    green_count: Mapped[int] = mapped_column(Integer, default=0)
    amber_count: Mapped[int] = mapped_column(Integer, default=0)
    red_count: Mapped[int] = mapped_column(Integer, default=0)
    assessments_generated: Mapped[int] = mapped_column(Integer, default=0)
    locs_generated: Mapped[int] = mapped_column(Integer, default=0)

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="batch")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    dob: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matter_ref: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="client")
    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="client")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("batches.id"), nullable=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    traffic_light: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    s3_raw_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    s3_assessment_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalised_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    spot_check_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    spot_check_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    batch: Mapped[Optional["Batch"]] = relationship("Batch", back_populates="jobs")
    client: Mapped[Optional["Client"]] = relationship("Client", back_populates="jobs")
    lender_results: Mapped[list["LenderResult"]] = relationship("LenderResult", back_populates="job")

    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_batch_id", "batch_id"),
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    lender_name: Mapped[str] = mapped_column(String(255), index=True)
    account_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    opened_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    credit_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    utilisation_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    payment_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    client: Mapped["Client"] = relationship("Client", back_populates="accounts")


class LenderResult(Base):
    __tablename__ = "lender_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    lender_name: Mapped[str] = mapped_column(String(255), index=True)
    traffic_light: Mapped[str] = mapped_column(String(10))
    claim_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_flags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    evidence_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    loc_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    s3_loc_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), default="PENDING")

    job: Mapped["Job"] = relationship("Job", back_populates="lender_results")

    __table_args__ = (
        Index("ix_lender_results_lender_name", "lender_name"),
    )
