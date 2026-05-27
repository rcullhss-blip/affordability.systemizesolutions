from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
import uuid
import zipfile
import io
from app.core.database import get_db
from app.core.config import settings
from app.core.storage import upload_bytes
from app.models.tables import Batch, Job
from app.models.enums import JobStatus
from app.workers.fetch import fetch_and_process

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".html", ".htm", ".csv", ".xlsx", ".zip", ".docx", ".json"}


def _detect_format(filename: str) -> str:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix if suffix in ALLOWED_EXTENSIONS else "unknown"


@router.post("/file")
async def upload_file(
    file: UploadFile = File(...),
    batch_name: str = Form(...),
    db: Session = Depends(get_db),
):
    fmt = _detect_format(file.filename or "")
    if fmt == "unknown":
        raise HTTPException(status_code=400, detail="Unsupported file format")

    # If someone sends a CSV to this endpoint, route it to the URL-list handler
    if fmt == ".csv":
        return await upload_csv(file=file, batch_name=batch_name, db=db)

    raw_bytes = await file.read()
    s3_key = f"raw/{uuid.uuid4()}/{file.filename}"
    upload_bytes(settings.S3_BUCKET_RAW, s3_key, raw_bytes)

    batch = Batch(name=batch_name, total_reports=1)
    db.add(batch)
    db.flush()

    job = Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING")
    db.add(job)
    db.commit()
    db.refresh(job)

    task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
    job.celery_task_id = task.id
    db.commit()

    return {"job_id": job.id, "batch_id": batch.id, "task_id": task.id, "status": "queued"}


@router.post("/zip")
async def upload_zip(
    file: UploadFile = File(...),
    batch_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Accept a ZIP of credit report files. Creates one job per supported file inside the ZIP."""
    content = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    supported_names = [
        name for name in zf.namelist()
        if not name.startswith("__MACOSX")
        and not name.endswith("/")
        and _detect_format(name.split("/")[-1]) != "unknown"
    ]

    if not supported_names:
        raise HTTPException(status_code=400, detail="No supported files found in ZIP (expected PDF, HTML, DOCX, XLSX)")

    batch = Batch(name=batch_name, total_reports=len(supported_names))
    db.add(batch)
    db.flush()

    job_ids = []
    for name in supported_names:
        filename = name.split("/")[-1]
        file_bytes = zf.read(name)
        s3_key = f"raw/{uuid.uuid4()}/{filename}"
        upload_bytes(settings.S3_BUCKET_RAW, s3_key, file_bytes)

        job = Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING")
        db.add(job)
        db.flush()
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
        job_ids.append(job.id)

    db.commit()
    return {"batch_id": batch.id, "jobs_created": len(job_ids), "status": "queued"}


@router.post("/csv")
async def upload_csv(
    file: UploadFile = File(...),
    batch_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Accept a CSV of report URLs, create one job per row."""
    content = await file.read()
    # Strip UTF-8 BOM if present
    raw = content.lstrip(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8", errors="replace").splitlines()
    # Only keep lines that look like URLs — skip headers, blank lines, comments
    urls = [line.strip() for line in lines if line.strip().lower().startswith("http")]

    if not urls:
        raise HTTPException(status_code=400, detail="No URLs found in CSV")

    batch = Batch(name=batch_name, total_reports=len(urls))
    db.add(batch)
    db.flush()

    job_ids = []
    for url in urls:
        job = Job(batch_id=batch.id, source_url=url, status="PENDING")
        db.add(job)
        db.flush()
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
        job_ids.append(job.id)

    db.commit()
    return {"batch_id": batch.id, "jobs_created": len(job_ids), "status": "queued"}
