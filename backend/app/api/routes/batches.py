import csv
import io
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import settings
from app.core.s3 import generate_presigned_url
from app.core.lender_blocklist import is_blocked
from app.models.tables import Batch, Job, Client, LenderResult
from app.models.enums import JobStatus

_FALLBACK_BASE = "http://localhost:8000"

_TITLES = {"MR", "MRS", "MS", "MISS", "DR", "PROF", "SIR", "REV", "MASTER"}
_UK_POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)

_TL_LABELS = {
    "GREEN": "Strong",
    "AMBER": "Borderline",
    "RED":   "Weak",
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


def _file_url(bucket: str, key: str | None, base_url: str = _FALLBACK_BASE) -> str:
    if not key:
        return ""
    if settings.use_local_storage:
        return f"{base_url}/api/v1/files/{bucket}/{key}"
    try:
        return generate_presigned_url(bucket, key, expires_in=604800)  # 7 days (AWS max)
    except Exception:
        return ""


@router.get("/{batch_id}/export/tracker")
def export_tracker_csv(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Proclaim-ready tracker CSV — one row per LOC. Streamed, and pulls only the
    fields it needs (not the full report JSON) so it scales to large batches."""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    nd = Job.normalised_data  # extract client sub-fields server-side, no blob load
    job_rows = db.execute(
        select(
            Job.id, Job.created_at, Job.s3_raw_key, Job.s3_assessment_key,
            Client.name, Client.dob, Client.address,
            nd["client"]["email"].astext, nd["client"]["phone"].astext,
            nd["client"]["name"].astext, nd["client"]["dob"].astext, nd["client"]["address"].astext,
        )
        .outerjoin(Client, Client.id == Job.client_id)
        .where(Job.batch_id == batch_id, Job.status == "COMPLETE")
        .order_by(Job.created_at.asc())
    ).all()

    # Lender results grouped by job (single query, no per-job round-trips)
    lrs: dict[int, list] = {}
    for jid, lender, tl, loc_gen, loc_key in db.execute(
        select(LenderResult.job_id, LenderResult.lender_name, LenderResult.traffic_light,
               LenderResult.loc_generated, LenderResult.s3_loc_key)
        .join(Job, Job.id == LenderResult.job_id)
        .where(Job.batch_id == batch_id, Job.status == "COMPLETE")
    ).all():
        lrs.setdefault(jid, []).append((lender, tl, loc_gen, loc_key))

    base_url = str(request.base_url).rstrip("/")
    RAW, OUTB = settings.S3_BUCKET_RAW, settings.S3_BUCKET_OUTPUTS

    def _line(vals):
        buf = io.StringIO()
        csv.writer(buf).writerow(vals)
        return buf.getvalue()

    def stream():
        yield _line([
            "Timestamp", "Title", "First Name", "Surname", "Date of Birth", "Email", "Phone",
            "Residence 1", "Residence 2", "Residence 3", "Postal Code",
            "Defendant", "Analysis Status", "Case Status",
            "Credit Report", "Assessment PDF", "Letter of Claim",
        ])
        for (jid, created, raw_key, assess_key, c_name, c_dob, c_addr,
             email, phone, nd_name, nd_dob, nd_addr) in job_rows:
            ts = created.strftime("%d/%m/%Y %H:%M") if created else ""
            title, first_name, surname = _split_name((c_name or "") or (nd_name or ""))
            dob = (str(c_dob) if c_dob else "") or (nd_dob or "")
            res1, res2, res3, postcode = _split_address((c_addr or "") or (nd_addr or ""))
            report_url     = _file_url(RAW, raw_key, base_url)
            assessment_url = _file_url(OUTB, assess_key, base_url)
            these = lrs.get(jid, [])
            locs = [(l, tl, k) for (l, tl, g, k) in these if g and k]
            if locs:
                for lender, tl, k in locs:
                    yield _line([
                        ts, title, first_name, surname, dob, email or "", phone or "",
                        res1, res2, res3, postcode,
                        lender, _TL_LABELS.get((tl or "").upper(), ""), "LOC Generated",
                        report_url, assessment_url, _file_url(OUTB, k, base_url),
                    ])
            else:
                all_blocked = bool(these) and all(is_blocked(l) for (l, _, _, _) in these)
                case_status = "No Viable Defendant" if all_blocked else "No Viable Claim"
                yield _line([
                    ts, title, first_name, surname, dob, email or "", phone or "",
                    res1, res2, res3, postcode, "", "", case_status,
                    report_url, assessment_url, "",
                ])

    firm_slug = (batch.firm or "first_legal")
    batch_slug = re.sub(r'[^a-z0-9]+', '_', (batch.name or str(batch_id)).lower()).strip('_')
    filename = f"{batch_slug}_{firm_slug}_affordability_tracker.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
