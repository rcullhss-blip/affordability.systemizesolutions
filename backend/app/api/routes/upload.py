from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid
import zipfile
import io
import re
from app.core.database import get_db
from app.core.config import settings
from app.core.storage import upload_bytes, list_keys
from app.models.tables import Batch, Job
from app.models.enums import JobStatus
from app.workers.fetch import fetch_and_process
from app.api.routes.webhook import _require_api_key
from app.core.auth import Principal, require_auth


def _effective_firm(p: Principal, requested: str) -> str:
    """Firm users always upload under their own firm; admins choose."""
    return p.firm if (not p.is_admin and p.firm) else requested

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".html", ".htm", ".csv", ".xlsx", ".zip", ".docx", ".json"}

# Above this many URLs a CSV upload is expanded in the background (see upload_csv).
CSV_INLINE_THRESHOLD = 500

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
    p: Principal = Depends(require_auth),
):
    firm = _effective_firm(p, firm)
    fmt = _detect_format(file.filename or "")
    if fmt == "unknown":
        raise HTTPException(status_code=400, detail="Unsupported file format")

    # If someone sends a CSV to this endpoint, route it to the URL-list handler
    if fmt == ".csv":
        return await upload_csv(file=file, batch_name=batch_name, firm=firm, db=db, p=p)

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


@router.post("/files")
async def upload_files(
    files: List[UploadFile] = File(...),
    batch_name: str = Form(...),
    firm: str = Form("first_legal"),
    batch_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    p: Principal = Depends(require_auth),
):
    """Accept many report files at once (e.g. a dragged-in folder). Creates ONE
    batch with one job per supported file. Returns the received/created counts so
    the caller can verify nothing was dropped.

    Pass an existing `batch_id` to append these files to that batch — this lets a
    large folder be uploaded in chunks (e.g. 200 at a time) while staying one batch."""
    firm = _effective_firm(p, firm)
    received = len(files)
    supported = [
        f for f in files
        if _detect_format((f.filename or "").split("/")[-1]) not in ("unknown", ".csv", ".zip")
    ]
    if not supported:
        raise HTTPException(
            status_code=400,
            detail="No supported report files found (expected JSON, PDF, HTML, DOCX or XLSX)",
        )

    if batch_id is not None:
        batch = db.get(Batch, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")
        batch.total_reports = (batch.total_reports or 0) + len(supported)
        db.flush()
    else:
        batch = Batch(name=batch_name, total_reports=len(supported), firm=firm)
        db.add(batch)
        db.flush()

    # Commit every job before enqueuing so a worker can't race an uncommitted job
    # into a stranded PENDING state — guarantees each file becomes a tracked job.
    jobs = []
    for f in supported:
        raw = await f.read()
        filename = (f.filename or "report").split("/")[-1]
        s3_key = f"raw/{uuid.uuid4()}/{filename}"
        upload_bytes(settings.S3_BUCKET_RAW, s3_key, raw)
        jobs.append(Job(batch_id=batch.id, s3_raw_key=s3_key, status="PENDING"))
    db.add_all(jobs)
    db.commit()

    for job in jobs:
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
    db.commit()

    return {
        "batch_id": batch.id,
        "received": received,
        "jobs_created": len(jobs),
        "skipped": received - len(supported),
        "status": "queued",
    }


@router.post("/zip")
async def upload_zip(
    file: UploadFile = File(...),
    batch_name: str = Form(...),
    firm: str = Form("first_legal"),
    db: Session = Depends(get_db),
    p: Principal = Depends(require_auth),
):
    """Accept a ZIP of credit report files. Creates one job per supported file inside the ZIP."""
    firm = _effective_firm(p, firm)
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


class S3PrefixIngest(BaseModel):
    batch_name: str
    prefix: str
    firm: str = "first_legal"
    # Guard against accidentally turning an entire 100k staging area into one
    # batch — split large staging areas into wave prefixes instead.
    max_reports: int = 15_000


@router.post("/s3-prefix", dependencies=[Depends(_require_api_key)])
async def ingest_s3_prefix(body: S3PrefixIngest, db: Session = Depends(get_db)):
    """Create a batch from reports ALREADY staged in the raw S3 bucket under a
    prefix (bulk ingest path: CRA pull stages reports → this processes them).
    Job creation + enqueue happens in the intake worker so the response is
    instant regardless of batch size; keys already attached to a job are
    skipped, so re-posting the same prefix is safe."""
    from app.workers.intake import expand_s3_prefix, _is_report_key

    prefix = body.prefix.lstrip("/")
    if not prefix:
        raise HTTPException(status_code=400, detail="prefix is required")

    keys = [k for k in list_keys(settings.S3_BUCKET_RAW, prefix) if _is_report_key(k)]
    if not keys:
        raise HTTPException(status_code=404, detail=f"No report files found under prefix '{prefix}'")
    if len(keys) > body.max_reports:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(keys):,} reports under '{prefix}' exceeds max_reports "
                f"({body.max_reports:,}) — split the staging area into wave prefixes "
                f"or raise max_reports explicitly"
            ),
        )

    batch = Batch(name=body.batch_name, total_reports=len(keys), firm=body.firm)
    db.add(batch)
    db.commit()
    db.refresh(batch)

    expand_s3_prefix.apply_async(args=[batch.id, prefix], queue="fetch")

    return {"batch_id": batch.id, "reports_found": len(keys), "status": "expanding"}


@router.post("/csv")
async def upload_csv(
    file: UploadFile = File(...),
    batch_name: str = Form(...),
    firm: str = Form("first_legal"),
    db: Session = Depends(get_db),
    p: Principal = Depends(require_auth),
):
    """Accept a CSV of report URLs, create one job per row."""
    firm = _effective_firm(p, firm)
    content = await file.read()
    # Strip UTF-8 BOM if present, then pull URLs from anywhere in the file.
    raw = content.lstrip(b"\xef\xbb\xbf")
    urls = extract_urls(raw.decode("utf-8", errors="replace"))

    if not urls:
        raise HTTPException(status_code=400, detail="No URLs found in CSV")

    batch = Batch(name=batch_name, total_reports=len(urls), firm=firm)
    db.add(batch)
    db.flush()

    # ── Large CSV: store the URL list and fan out in the background ──────────
    # Creating 32k+ jobs and enqueuing 32k tasks inside one HTTP request worked
    # for the Barings batch but is the wrong place for it — a 100k CSV shouldn't
    # depend on the request staying open. Same manifest pattern as the webhook.
    if len(urls) > CSV_INLINE_THRESHOLD:
        import json
        manifest_key = f"manifests/{uuid.uuid4()}/urls.json"
        upload_bytes(settings.S3_BUCKET_RAW, manifest_key,
                     json.dumps(urls).encode("utf-8"), "application/json")
        db.commit()
        from app.workers.intake import expand_url_manifest
        expand_url_manifest.apply_async(args=[batch.id, manifest_key], queue="fetch")
        return {"batch_id": batch.id, "jobs_created": len(urls), "status": "expanding",
                "message": f"{len(urls):,} URLs accepted; jobs are being created in the background."}

    # ── Small CSV: create + commit all jobs BEFORE enqueuing, so the worker can't
    # race ahead of an uncommitted job and strand it (same fix as the webhook path).
    jobs = [Job(batch_id=batch.id, source_url=url, status="PENDING") for url in urls]
    db.add_all(jobs)
    db.commit()

    for job in jobs:
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
    db.commit()

    return {"batch_id": batch.id, "jobs_created": len(jobs), "status": "queued"}
