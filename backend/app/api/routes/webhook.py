"""
Webhook endpoint for direct JSON partner-post ingestion.

Supports:
  POST /api/v1/webhook/bureau
    — Single bureau JSON payload (Equifax or TransUnion)
    — Body: raw JSON object (the partner-post payload)
    — Optional query params: batch_name, matter_ref

  POST /api/v1/webhook/bureau/batch
    — Array of bureau JSON payloads
    — Body: JSON array of partner-post objects
    — Optional query params: batch_name

This lets data partners POST credit reports directly without needing
to wrap them as file uploads.
"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.storage import upload_bytes
from app.core.config import settings
from app.models.tables import Batch, Job
from app.parsers.router import _JSON_PARTNER_POST_PREFIX
from app.parsers.json_normaliser import normalise_json_payload
from app.workers.fetch import fetch_and_process

router = APIRouter()


@router.post("/bureau")
async def ingest_bureau_post(
    request: Request,
    batch_name: str = Query(default="webhook-batch"),
    matter_ref: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Accept a single Equifax or TransUnion JSON partner-post.
    Validates the format, stores the payload, queues a processing job.
    """
    try:
        raw_bytes = await request.body()
        data = json.loads(raw_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")

    # Validate it's a recognised bureau format
    try:
        normalise_json_payload(data)  # dry-run validation only
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Unrecognised bureau format: {e}")

    # Inject matter_ref if supplied via query param
    if matter_ref and not data.get("clientRefId"):
        data["clientRefId"] = matter_ref

    agency = (data.get("agency") or _detect_agency(data)).upper()
    filename = f"bureau_{agency.lower()}_{uuid.uuid4().hex[:8]}.json"
    s3_key   = f"raw/{uuid.uuid4()}/{filename}"

    upload_bytes(settings.S3_BUCKET_RAW, s3_key, json.dumps(data).encode("utf-8"))

    batch = db.query(Batch).filter(Batch.name == batch_name).first()
    if not batch:
        batch = Batch(name=batch_name, total_reports=0)
        db.add(batch)
        db.flush()

    batch.total_reports = (batch.total_reports or 0) + 1

    job = Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING")
    db.add(job)
    db.flush()

    task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
    job.celery_task_id = task.id
    db.commit()

    return {
        "job_id":    job.id,
        "batch_id":  batch.id,
        "task_id":   task.id,
        "agency":    agency,
        "status":    "queued",
    }


@router.post("/bureau/batch")
async def ingest_bureau_batch(
    request: Request,
    batch_name: str = Query(default="webhook-batch"),
    db: Session = Depends(get_db),
):
    """
    Accept an array of bureau JSON payloads in a single request.
    Each element can be Equifax or TransUnion — they are processed independently.
    """
    try:
        raw_bytes = await request.body()
        payloads = json.loads(raw_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be a valid JSON array")

    if not isinstance(payloads, list):
        # Allow single object — wrap it
        if isinstance(payloads, dict):
            payloads = [payloads]
        else:
            raise HTTPException(status_code=400, detail="Expected JSON array or object")

    if len(payloads) > 10_000:
        raise HTTPException(status_code=400, detail="Batch too large — max 10,000 per request")

    # Validate all payloads first
    for i, data in enumerate(payloads):
        try:
            normalise_json_payload(data)
        except ValueError as e:
            raise HTTPException(
                status_code=422,
                detail=f"Payload #{i} unrecognised bureau format: {e}"
            )

    batch = Batch(name=batch_name, total_reports=len(payloads))
    db.add(batch)
    db.flush()

    job_ids = []
    for data in payloads:
        agency   = (data.get("agency") or _detect_agency(data)).upper()
        filename = f"bureau_{agency.lower()}_{uuid.uuid4().hex[:8]}.json"
        s3_key   = f"raw/{uuid.uuid4()}/{filename}"

        upload_bytes(settings.S3_BUCKET_RAW, s3_key, json.dumps(data).encode("utf-8"))

        job = Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING")
        db.add(job)
        db.flush()

        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
        job_ids.append(job.id)

    db.commit()

    return {
        "batch_id":     batch.id,
        "jobs_created": len(job_ids),
        "status":       "queued",
    }


def _detect_agency(data: dict) -> str:
    """Detect Equifax vs TransUnion from payload structure."""
    report = data.get("report", {})
    if isinstance(report, dict):
        if "FinancialAccountInformation" in report or "PersonalInformation" in report:
            return "TRANSUNION"
        inner = report.get("report", {})
        if isinstance(inner, dict) and "soleSearch" in inner:
            return "EQUIFAX"
    return "UNKNOWN"
