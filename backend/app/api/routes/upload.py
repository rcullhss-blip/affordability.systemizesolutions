from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
import uuid
import zipfile
import io
import re
from app.core.database import get_db
from app.core.config import settings
from app.core.storage import upload_bytes
from app.models.tables import Batch, Job
from app.models.enums import JobStatus
from app.workers.fetch import fetch_and_process

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".html", ".htm", ".csv", ".xlsx", ".zip", ".docx", ".json"}

# Match a URL anywhere in a line — not just at the start — so links sitting in a
# CSV cell alongside other columns (or wrapped in quotes) are still found.
_URL_RE = re.compile(r'https?://[^\s,"\'<>\\]+', re.IGNORECASE)


def gdrive_direct(url: str) -> str:
    """Turn a Google Drive *share* link into a direct-download URL. A share link
    (…/file/d/<id>/view or …/open?id=<id>) returns the Drive HTML viewer, not the
    file, so it must be rewritten to …/uc?export=download&id=<id>."""
    if "drive.google.com" not in url and "docs.google.com" not in url:
        return url
    m = (re.search(r'/file/d/([A-Za-z0-9_-]+)', url)
         or re.search(r'[?&]id=([A-Za-z0-9_-]+)', url))
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def extract_urls(text: str) -> list[str]:
    """Extract every http(s) URL from arbitrary CSV/text, de-duplicated, with
    Google Drive share links normalised to direct downloads."""
    out, seen = [], set()
    for raw in _URL_RE.findall(text):
        u = gdrive_direct(raw.rstrip('",\';)'))
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _detect_format(filename: str) -> str:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix if suffix in ALLOWED_EXTENSIONS else "unknown"


@router.post("/file")
async def upload_file(
    file: UploadFile = File(...),
    batch_name: str = Form(...),
    firm: str = Form("first_legal"),
    db: Session = Depends(get_db),
):
    fmt = _detect_format(file.filename or "")
    if fmt == "unknown":
        raise HTTPException(status_code=400, detail="Unsupported file format")

    # If someone sends a CSV to this endpoint, route it to the URL-list handler
    if fmt == ".csv":
        return await upload_csv(file=file, batch_name=batch_name, firm=firm, db=db)

    raw_bytes = await file.read()
    s3_key = f"raw/{uuid.uuid4()}/{file.filename}"
    upload_bytes(settings.S3_BUCKET_RAW, s3_key, raw_bytes)

    batch = Batch(name=batch_name, total_reports=1, firm=firm)
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
    firm: str = Form("first_legal"),
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
        raise HTTPException(status_code=400, detail="No supported files found in ZIP (expected PDF, HTML, DOCX, XLSX, JSON)")

    batch = Batch(name=batch_name, total_reports=len(supported_names), firm=firm)
    db.add(batch)
    db.flush()

    # Create + commit all jobs before enqueuing (avoid the worker racing an
    # uncommitted job into a stranded PENDING state).
    jobs = []
    for name in supported_names:
        filename = name.split("/")[-1]
        s3_key = f"raw/{uuid.uuid4()}/{filename}"
        upload_bytes(settings.S3_BUCKET_RAW, s3_key, zf.read(name))
        jobs.append(Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING"))
    db.add_all(jobs)
    db.commit()

    for job in jobs:
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
    db.commit()

    return {"batch_id": batch.id, "jobs_created": len(jobs), "status": "queued"}


@router.post("/csv")
async def upload_csv(
    file: UploadFile = File(...),
    batch_name: str = Form(...),
    firm: str = Form("first_legal"),
    db: Session = Depends(get_db),
):
    """Accept a CSV of report URLs, create one job per row."""
    content = await file.read()
    # Strip UTF-8 BOM if present, then pull URLs from anywhere in the file.
    raw = content.lstrip(b"\xef\xbb\xbf")
    urls = extract_urls(raw.decode("utf-8", errors="replace"))

    if not urls:
        raise HTTPException(status_code=400, detail="No URLs found in CSV")

    batch = Batch(name=batch_name, total_reports=len(urls), firm=firm)
    db.add(batch)
    db.flush()

    # Create + commit all jobs BEFORE enqueuing, so the worker can't race ahead
    # of an uncommitted job and strand it (same fix as the webhook path).
    jobs = [Job(batch_id=batch.id, source_url=url, status="PENDING") for url in urls]
    db.add_all(jobs)
    db.commit()

    for job in jobs:
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
    db.commit()

    return {"batch_id": batch.id, "jobs_created": len(jobs), "status": "queued"}
