import csv
import io
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import settings
from app.core.s3 import generate_presigned_url
from app.core.lender_blocklist import is_blocked
from app.models.tables import Batch, Job
from app.models.enums import JobStatus

BASE_URL = "http://localhost:8000"

_TITLES = {"MR", "MRS", "MS", "MISS", "DR", "PROF", "SIR", "REV", "MASTER"}
_UK_POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)

_TL_LABELS = {
    "GREEN": "Strong Claim Indicators",
    "AMBER": "Claim Indicators Present",
    "RED":   "Insufficient Evidence",
}


def _split_name(full_name: str):
    """Return (title, first_name, surname) from a full name string."""
    parts = full_name.strip().title().split()
    if not parts:
        return "", "", ""
    if parts[0].upper() in _TITLES:
        return parts[0], (parts[1] if len(parts) > 1 else ""), " ".join(parts[2:])
    return "", parts[0], " ".join(parts[1:])


def _split_address(address: str):
    """Return (res1, res2, res3, postcode) from a comma-joined address string."""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    postcode = ""
    for i in range(len(parts) - 1, -1, -1):
        if _UK_POSTCODE.search(parts[i]):
            postcode = parts.pop(i).strip().upper()
            break
    return (
        parts[0] if len(parts) > 0 else "",
        parts[1] if len(parts) > 1 else "",
        parts[2] if len(parts) > 2 else "",
        postcode,
    )


def _case_status(loc_generated: bool, traffic_light: str | None) -> str:
    if loc_generated:
        return "LOC Generated"
    tl = (traffic_light or "").upper()
    if tl in ("GREEN", "AMBER"):
        return "Referred for Legal Review"
    if tl == "RED":
        return "No Viable Claim"
    return "Pending"

router = APIRouter()


def _serialise_job(job):
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "status": job.status,
        "traffic_light": job.traffic_light,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "s3_assessment_key": job.s3_assessment_key,
        "client": {
            "id": job.client.id,
            "name": job.client.name,
            "matter_ref": job.client.matter_ref,
            "dob": str(job.client.dob) if job.client.dob else None,
        } if job.client else None,
        "lender_results": [
            {
                "id": r.id,
                "lender_name": r.lender_name,
                "traffic_light": r.traffic_light,
                "claim_score": r.claim_score,
                "loc_generated": r.loc_generated,
                "s3_loc_key": r.s3_loc_key,
                "no_longer_trading": is_blocked(r.lender_name),
            }
            for r in job.lender_results
        ],
    }


@router.get("/")
def list_batches(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    batches = db.execute(select(Batch).order_by(Batch.created_at.desc()).offset(skip).limit(limit)).scalars().all()
    return batches


@router.get("/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.get("/{batch_id}/jobs")
def get_batch_jobs(batch_id: int, db: Session = Depends(get_db)):
    jobs = db.execute(
        select(Job)
        .where(Job.batch_id == batch_id)
        .options(selectinload(Job.client), selectinload(Job.lender_results))
        .order_by(Job.created_at.asc())
    ).scalars().all()
    return [_serialise_job(j) for j in jobs]


@router.get("/{batch_id}/progress")
def batch_progress(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    jobs = db.execute(select(Job).where(Job.batch_id == batch_id)).scalars().all()
    status_counts = {}
    for job in jobs:
        status_counts[job.status] = status_counts.get(job.status, 0) + 1

    complete = status_counts.get("COMPLETE", 0)
    failed = status_counts.get("FAILED", 0)
    pct = round((complete + failed) / max(batch.total_reports, 1) * 100, 1)

    return {
        "batch_id": batch_id,
        "total": batch.total_reports,
        "complete": complete,
        "failed": failed,
        "in_progress": len(jobs) - complete - failed,
        "percent_done": pct,
        "green": batch.green_count,
        "amber": batch.amber_count,
        "red": batch.red_count,
        "assessments": batch.assessments_generated,
        "locs": batch.locs_generated,
    }


def _file_url(bucket: str, key: str | None) -> str:
    if not key:
        return ""
    if settings.use_local_storage:
        return f"{BASE_URL}/api/v1/files/{bucket}/{key}"
    try:
        return generate_presigned_url(bucket, key, expires_in=86400)
    except Exception:
        return ""


@router.get("/{batch_id}/export/tracker")
def export_tracker_csv(batch_id: int, db: Session = Depends(get_db)):
    """Proclaim-ready tracker CSV — one row per LOC."""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    jobs = db.execute(
        select(Job)
        .where(Job.batch_id == batch_id)
        .options(selectinload(Job.client), selectinload(Job.lender_results))
        .order_by(Job.created_at.asc())
    ).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Timestamp", "Title", "First Name", "Surname", "Date of Birth",
        "Email", "Phone",
        "Residence 1", "Residence 2", "Residence 3", "Postal Code",
        "Defendant", "Analysis Status", "Case Status",
        "Credit Report", "Assessment PDF", "Letter of Claim",
    ])

    for job in jobs:
        client = job.client
        schema_client = (job.normalised_data or {}).get("client", {})

        # Timestamp
        ts = job.created_at.strftime("%d/%m/%Y %H:%M") if job.created_at else ""

        # Name fields — prefer DB client record, fall back to normalised_data
        raw_name = (client.name if client else "") or schema_client.get("name", "")
        title, first_name, surname = _split_name(raw_name)

        # DOB
        dob = (str(client.dob) if client and client.dob else "") or schema_client.get("dob", "")

        # Contact — only in normalised_data (not stored on Client model)
        email = schema_client.get("email", "")
        phone = schema_client.get("phone", "")

        # Address
        raw_addr = (client.address or "" if client else "") or schema_client.get("address", "")
        res1, res2, res3, postcode = _split_address(raw_addr)

        # Document URLs
        report_url     = _file_url(settings.S3_BUCKET_RAW,     job.s3_raw_key)
        assessment_url = _file_url(settings.S3_BUCKET_OUTPUTS, job.s3_assessment_key)

        locs = [r for r in job.lender_results if r.loc_generated and r.s3_loc_key]
        rows_to_write = locs if locs else [None]

        for r in rows_to_write:
            defendant       = r.lender_name if r else ""
            analysis_status = _TL_LABELS.get((r.traffic_light or "").upper(), "") if r else ""
            case_status     = _case_status(r.loc_generated if r else False, r.traffic_light if r else None)
            loc_url         = _file_url(settings.S3_BUCKET_OUTPUTS, r.s3_loc_key) if r else ""

            writer.writerow([
                ts, title, first_name, surname, dob,
                email, phone,
                res1, res2, res3, postcode,
                defendant, analysis_status, case_status,
                report_url, assessment_url, loc_url,
            ])

    buf.seek(0)
    batch_slug = re.sub(r'[^a-z0-9]+', '_', (batch.name or str(batch_id)).lower()).strip('_')
    filename = f"{batch_slug}_first_legal_affordability_assessment.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
