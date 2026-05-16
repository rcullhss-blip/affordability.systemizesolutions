import io
import re
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from app.core.database import get_db
from app.core.storage import get_download_url, download_bytes
from app.core.config import settings
from app.core.lender_blocklist import is_blocked
from app.models.tables import Job

router = APIRouter()


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
