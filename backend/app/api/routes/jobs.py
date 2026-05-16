import io
import re
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, text
from app.core.database import get_db
from app.core.storage import get_download_url, download_bytes
from app.core.config import settings
from app.core.lender_blocklist import is_blocked
from app.models.tables import Job

router = APIRouter()


class FeedbackIn(BaseModel):
    note: str


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.lender_results), selectinload(Job.client))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "status": job.status,
        "traffic_light": job.traffic_light,
        "error_message": job.error_message,
        "source_url": job.source_url,
        "s3_raw_key": job.s3_raw_key,
        "s3_assessment_key": job.s3_assessment_key,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "client": {
            "id": job.client.id,
            "name": job.client.name,
            "matter_ref": job.client.matter_ref,
            "dob": str(job.client.dob) if job.client.dob else None,
            "address": job.client.address,
        } if job.client else None,
        "lender_results": [
            {
                "id": r.id,
                "lender_name": r.lender_name,
                "traffic_light": r.traffic_light,
                "claim_score": r.claim_score,
                "loc_generated": r.loc_generated,
                "s3_loc_key": r.s3_loc_key,
                "evidence_summary": r.evidence_summary,
                "risk_flags": r.risk_flags or [],
                "no_longer_trading": is_blocked(r.lender_name),
            }
            for r in job.lender_results
        ],
    }


@router.get("/{job_id}/download/assessment")
def download_assessment(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or not job.s3_assessment_key:
        raise HTTPException(status_code=404, detail="Assessment not available")
    url = get_download_url(settings.S3_BUCKET_OUTPUTS, job.s3_assessment_key)
    return {"url": url}


@router.get("/{job_id}/download/locs")
def download_locs(job_id: int, db: Session = Depends(get_db)):
    job = db.execute(
        select(Job).where(Job.id == job_id).options(selectinload(Job.lender_results))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    urls = []
    for result in job.lender_results:
        if result.s3_loc_key:
            urls.append({
                "lender": result.lender_name,
                "traffic_light": result.traffic_light,
                "url": get_download_url(settings.S3_BUCKET_OUTPUTS, result.s3_loc_key),
            })
    return {"locs": urls}


@router.get("/{job_id}/download/locs/zip")
def download_locs_zip(job_id: int, db: Session = Depends(get_db)):
    job = db.execute(
        select(Job).where(Job.id == job_id).options(selectinload(Job.lender_results), selectinload(Job.client))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    locs = [r for r in job.lender_results if r.loc_generated and r.s3_loc_key]
    if not locs:
        raise HTTPException(status_code=404, detail="No LOCs available for this job")

    client_name = (job.client.name if job.client else "") or "client"
    client_slug = re.sub(r'[^a-z0-9]+', '_', client_name.lower()).strip('_')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for result in locs:
            lender_slug = re.sub(r'[^a-z0-9]+', '_', result.lender_name.lower()).strip('_')
            filename = f"{client_slug}_loc_{lender_slug}.docx"
            try:
                data = download_bytes(settings.S3_BUCKET_OUTPUTS, result.s3_loc_key)
                zf.writestr(filename, data)
            except Exception:
                pass

    buf.seek(0)
    zip_name = f"{client_slug}_locs.zip"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@router.get("/spot-checks")
def get_spot_checks(db: Session = Depends(get_db)):
    """Return all jobs flagged for spot check that haven't been reviewed yet."""
    jobs = db.execute(
        select(Job)
        .where(Job.spot_check_required == True, Job.spot_check_reviewed == False)
        .options(selectinload(Job.client))
        .order_by(Job.completed_at.desc())
    ).scalars().all()
    return [
        {
            "id": j.id,
            "batch_id": j.batch_id,
            "client_name": j.client.name if j.client else f"Job #{j.id}",
            "matter_ref": j.client.matter_ref if j.client else None,
            "traffic_light": j.traffic_light,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]


@router.post("/{job_id}/spot-check/reviewed")
def mark_spot_check_reviewed(job_id: int, db: Session = Depends(get_db)):
    """Mark a spot-checked job as reviewed by admin."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.spot_check_reviewed = True
    db.commit()
    return {"ok": True}


@router.post("/{job_id}/feedback")
def submit_feedback(job_id: int, body: FeedbackIn, db: Session = Depends(get_db)):
    """Log an issue or correction note against a job."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.execute(
        text("INSERT INTO job_feedback (job_id, note) VALUES (:job_id, :note)"),
        {"job_id": job_id, "note": body.note.strip()},
    )
    db.commit()
    return {"ok": True}


@router.get("/{job_id}/feedback")
def get_feedback(job_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, note, created_at, resolved FROM job_feedback WHERE job_id = :id ORDER BY created_at DESC"),
        {"id": job_id},
    ).fetchall()
    return [{"id": r.id, "note": r.note, "created_at": r.created_at.isoformat(), "resolved": r.resolved} for r in rows]


@router.get("/feedback/open")
def get_open_feedback(db: Session = Depends(get_db)):
    """All unresolved feedback across all jobs — for the admin dashboard queue."""
    rows = db.execute(
        text("""
            SELECT f.id, f.job_id, f.note, f.created_at,
                   c.name AS client_name, c.matter_ref
            FROM job_feedback f
            LEFT JOIN jobs j ON j.id = f.job_id
            LEFT JOIN clients c ON c.id = j.client_id
            WHERE f.resolved = FALSE
            ORDER BY f.created_at DESC
        """)
    ).fetchall()
    return [
        {
            "id": r.id, "job_id": r.job_id, "note": r.note,
            "created_at": r.created_at.isoformat(),
            "client_name": r.client_name or f"Job #{r.job_id}",
            "matter_ref": r.matter_ref,
        }
        for r in rows
    ]


@router.post("/feedback/{feedback_id}/resolved")
def resolve_feedback(feedback_id: int, db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE job_feedback SET resolved = TRUE WHERE id = :id"),
        {"id": feedback_id},
    )
    db.commit()
    return {"ok": True}
