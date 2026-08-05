"""
Webhook endpoint for direct JSON partner-post ingestion.

Supports:
  POST /api/v1/webhook/bureau
    — Single bureau JSON payload (Equifax or TransUnion)
    — Body: raw JSON object (the partner-post payload)
    — Optional query params: batch_name, matter_ref

  POST /api/v1/webhook/bureau/batch
    — Array of bureau JSON payloads, up to 15,000 per request
    — Body: JSON array of partner-post objects
    — Optional query params: batch_name
    — For large batches the response is immediate; a background worker
      fans out individual jobs so the HTTP request never times out.

Authentication:
  All endpoints require an X-API-Key header matching PROCLAIM_WEBHOOK_API_KEY.
  Leave PROCLAIM_WEBHOOK_API_KEY empty in .env to disable auth (dev/testing only).
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.storage import upload_bytes
from app.core.config import settings
from app.models.tables import Batch, Job, Case
from app.parsers.router import _JSON_PARTNER_POST_PREFIX
from app.parsers.json_normaliser import normalise_json_payload
from app.workers.fetch import fetch_and_process

router = APIRouter()

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

MAX_BATCH_SIZE = 15_000
# Batches larger than this are fanned out by the intake worker instead of inline
INLINE_THRESHOLD = int(os.getenv("WEBHOOK_INLINE_THRESHOLD", "500"))


def _require_api_key(api_key: Optional[str] = Security(_api_key_header)):
    configured = settings.PROCLAIM_WEBHOOK_API_KEY
    if not configured:
        return  # Auth disabled (dev/testing)
    if api_key != configured:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


def _require_irl_key(api_key: Optional[str] = Security(_api_key_header)):
    """Auth for the IRL case endpoint — the PCP platform sends its IRL_API_KEY."""
    configured = settings.IRL_CASE_API_KEY
    if not configured:
        return  # Auth disabled (dev/testing)
    if api_key != configured:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


def _parse_date_opt(value) -> Optional["datetime.date"]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


# All IRL cases are grouped under one batch so existing batch tooling applies.
IRL_CASES_BATCH = "irl-cases"


@router.post("/irl-case", status_code=202)
async def ingest_irl_case(
    request: Request,
    db: Session = Depends(get_db),
    _auth=Depends(_require_irl_key),
):
    """
    Accept one IRL case from the PCP platform (Credit Hub).

    Body: `Systemize IRL Case v1` — { lead_reference, source, triage, client,
    consent, credit_report: { raw, normalised, ... } }.

    Idempotent on `lead_reference`: a retry returns the existing case (never a
    duplicate). The credit report is fed into the standard assessment pipeline
    via a linked Job; the outcome is posted back to the PCP platform by the
    irl_outcome beat task once the Job completes.
    """
    try:
        raw_bytes = await request.body()
        payload = json.loads(raw_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")

    lead_reference = payload.get("lead_reference")
    if not lead_reference:
        raise HTTPException(status_code=422, detail="lead_reference is required")

    # ── Idempotency: never duplicate on retry ────────────────────────────────
    existing = db.query(Case).filter(Case.lead_reference == lead_reference).first()
    if existing:
        return {
            "status": "duplicate",
            "lead_reference": existing.lead_reference,
            "case_id": existing.id,
            "job_id": existing.job_id,
            "case_status": existing.status,
        }

    credit_report = payload.get("credit_report") or {}
    raw_report = credit_report.get("raw") or credit_report.get("normalised")
    if not raw_report:
        raise HTTPException(
            status_code=422,
            detail="credit_report.raw (or .normalised) is required",
        )

    # Preserve the exact inbound report in S3 (audit + reprocessing)
    s3_key = f"raw/irl-case/{uuid.uuid4()}/{lead_reference}.json"
    upload_bytes(settings.S3_BUCKET_RAW, s3_key, json.dumps(raw_report).encode("utf-8"))

    batch = db.query(Batch).filter(Batch.name == IRL_CASES_BATCH).first()
    if not batch:
        batch = Batch(name=IRL_CASES_BATCH, total_reports=0)
        db.add(batch)
        db.flush()
    batch.total_reports = (batch.total_reports or 0) + 1

    job = Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING")
    db.add(job)
    db.flush()

    client = payload.get("client") or {}
    address = client.get("address") or {}
    full_name = " ".join(
        p for p in [client.get("first_name"), client.get("last_name")] if p
    ) or None

    case = Case(
        lead_reference=lead_reference,
        bosh_reference=payload.get("bosh_reference"),
        source=payload.get("source") or "boshhh",
        status="QUEUED",
        triage=payload.get("triage"),
        client_name=full_name,
        client_dob=_parse_date_opt(client.get("date_of_birth")),
        client_postcode=address.get("postcode"),
        job_id=job.id,
        s3_raw_key=s3_key,
    )
    db.add(case)
    db.commit()      # commit before enqueue so the worker can find the job
    db.refresh(case)

    task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "queued",
        "lead_reference": lead_reference,
        "case_id": case.id,
        "job_id": job.id,
    }


@router.post("/bureau")
async def ingest_bureau_post(
    request: Request,
    batch_name: str = Query(default="webhook-batch"),
    matter_ref: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _auth=Depends(_require_api_key),
):
    """Accept a single Equifax or TransUnion JSON partner-post."""
    try:
        raw_bytes = await request.body()
        data = json.loads(raw_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")

    try:
        normalise_json_payload(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Unrecognised bureau format: {e}")

    if matter_ref and not data.get("clientRefId"):
        data["clientRefId"] = matter_ref

    agency = (data.get("agency") or _detect_agency(data)).upper()
    filename = f"bureau_{agency.lower()}_{uuid.uuid4().hex[:8]}.json"
    s3_key = f"raw/{uuid.uuid4()}/{filename}"

    upload_bytes(settings.S3_BUCKET_RAW, s3_key, json.dumps(data).encode("utf-8"))

    batch = db.query(Batch).filter(Batch.name == batch_name).first()
    if not batch:
        batch = Batch(name=batch_name, total_reports=0)
        db.add(batch)
        db.flush()

    batch.total_reports = (batch.total_reports or 0) + 1

    job = Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING")
    db.add(job)
    db.commit()        # commit before enqueue so the worker can find the job
    db.refresh(job)

    task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
    job.celery_task_id = task.id
    db.commit()

    return {
        "job_id":   job.id,
        "batch_id": batch.id,
        "task_id":  task.id,
        "agency":   agency,
        "status":   "queued",
    }


@router.post("/bureau/batch")
async def ingest_bureau_batch(
    request: Request,
    batch_name: str = Query(default="webhook-batch"),
    db: Session = Depends(get_db),
    _auth=Depends(_require_api_key),
):
    """
    Accept an array of bureau JSON payloads in a single request (up to 15,000).

    For batches up to 500 records, jobs are dispatched inline and the response
    includes the final job count. For larger batches the payload is stored in S3
    and a background worker fans out the individual jobs — the response returns
    immediately with status "expanding" so Proclaim is never left waiting.
    """
    try:
        raw_bytes = await request.body()
        payloads = json.loads(raw_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be a valid JSON array")

    if not isinstance(payloads, list):
        if isinstance(payloads, dict):
            payloads = [payloads]
        else:
            raise HTTPException(status_code=400, detail="Expected JSON array or object")

    if len(payloads) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch too large — max {MAX_BATCH_SIZE:,} per request (received {len(payloads):,})"
        )

    if not payloads:
        raise HTTPException(status_code=400, detail="Empty batch")

    total = len(payloads)

    # ── Large batch: store manifest and expand in background ──────────────────
    if total > INLINE_THRESHOLD:
        manifest_key = f"manifests/{uuid.uuid4()}/batch.json"
        upload_bytes(
            settings.S3_BUCKET_RAW,
            manifest_key,
            raw_bytes,
            "application/json",
        )

        batch = Batch(name=batch_name, total_reports=0)  # updated by intake worker
        db.add(batch)
        db.flush()
        batch_id = batch.id
        db.commit()

        from app.workers.intake import expand_proclaim_batch
        expand_proclaim_batch.apply_async(
            args=[batch_id, manifest_key],
            queue="fetch",
        )

        return {
            "batch_id":     batch_id,
            "total":        total,
            "status":       "expanding",
            "message":      f"Batch of {total:,} reports accepted. Jobs are being created in the background.",
        }

    # ── Small batch: validate and dispatch inline ─────────────────────────────
    for i, data in enumerate(payloads):
        if not isinstance(data, dict):
            raise HTTPException(status_code=422, detail=f"Payload #{i} must be a JSON object")
        try:
            normalise_json_payload(data)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Payload #{i} unrecognised bureau format: {e}")

    batch = Batch(name=batch_name, total_reports=total)
    db.add(batch)
    db.flush()

    # Create and COMMIT all job rows before enqueuing any task. A Celery worker
    # picks up a task the instant apply_async runs; if the job row isn't committed
    # yet the worker can't find it and the job is stranded in PENDING. Committing
    # first guarantees every job is visible before its task is dispatched.
    jobs = []
    for data in payloads:
        agency = (data.get("agency") or _detect_agency(data)).upper()
        filename = f"bureau_{agency.lower()}_{uuid.uuid4().hex[:8]}.json"
        s3_key = f"raw/{uuid.uuid4()}/{filename}"

        upload_bytes(settings.S3_BUCKET_RAW, s3_key, json.dumps(data).encode("utf-8"))

        job = Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING")
        db.add(job)
        jobs.append(job)

    db.commit()  # all jobs persisted before any task is enqueued

    for job in jobs:
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
    db.commit()

    return {
        "batch_id":     batch.id,
        "jobs_created": len(jobs),
        "status":       "queued",
    }


def _detect_agency(data: dict) -> str:
    report = data.get("report", {})
    if isinstance(report, dict):
        if "FinancialAccountInformation" in report or "PersonalInformation" in report:
            return "TRANSUNION"
        inner = report.get("report", {})
        if isinstance(inner, dict) and "soleSearch" in inner:
            return "EQUIFAX"
    return "UNKNOWN"
