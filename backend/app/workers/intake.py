"""
Batch expansion worker for large Proclaim/webhook ingestion.

When >500 reports arrive in one request we store a single manifest in S3,
create the Batch record, and dispatch THIS task rather than looping over
thousands of records inside the HTTP handler (which would time out).

This task reads the manifest and fans out one fetch_and_process task per report,
committing in chunks to keep memory and DB lock time bounded.
"""

import json
import uuid

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.storage import upload_bytes, download_bytes
from app.core.config import settings
from app.models.tables import Batch, Job

COMMIT_CHUNK = 500  # Commit to DB and dispatch tasks every N records


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def expand_proclaim_batch(self, batch_id: int, s3_manifest_key: str):
    """
    Read a stored JSON-array manifest and create one Job + one Celery task per entry.
    Runs entirely in the background so the HTTP response is instant.
    """
    from app.workers.fetch import fetch_and_process

    db = SessionLocal()
    try:
        batch = db.get(Batch, batch_id)
        if not batch:
            return

        raw = download_bytes(settings.S3_BUCKET_RAW, s3_manifest_key)
        payloads = json.loads(raw)

        total = 0
        chunk: list[Job] = []

        def _dispatch(jobs: list[Job]):
            """Commit the jobs, THEN enqueue — so the worker can always find them."""
            if not jobs:
                return
            db.commit()  # persist this chunk of jobs before any task is enqueued
            for j in jobs:
                t = fetch_and_process.apply_async(args=[j.id], queue="fetch")
                j.celery_task_id = t.id
            db.commit()

        for data in payloads:
            agency = _detect_agency(data)
            filename = f"bureau_{agency.lower()}_{uuid.uuid4().hex[:8]}.json"
            s3_key = f"raw/{uuid.uuid4()}/{filename}"
            upload_bytes(
                settings.S3_BUCKET_RAW,
                s3_key,
                json.dumps(data).encode("utf-8"),
                "application/json",
            )

            job = Job(batch_id=batch_id, s3_raw_key=s3_key, status="PENDING")
            db.add(job)
            chunk.append(job)
            total += 1

            if len(chunk) >= COMMIT_CHUNK:
                _dispatch(chunk)
                chunk = []

        _dispatch(chunk)  # final partial chunk

        # Write the real total back — batch was created with total_reports=0
        batch = db.get(Batch, batch_id)
        if batch:
            batch.total_reports = total
            db.commit()

    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


def _detect_agency(data: dict) -> str:
    report = data.get("report", {})
    if isinstance(report, dict):
        if "FinancialAccountInformation" in report or "PersonalInformation" in report:
            return "TRANSUNION"
        inner = report.get("report", {})
        if isinstance(inner, dict) and "soleSearch" in inner:
            return "EQUIFAX"
    return "UNKNOWN"
