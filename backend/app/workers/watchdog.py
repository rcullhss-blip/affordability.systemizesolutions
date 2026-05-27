"""
Watchdog — runs every 5 minutes via Celery Beat.
Finds jobs stranded in a mid-pipeline state (worker was killed) and re-queues
them from the correct stage so no manual intervention is ever needed.
"""
import logging
from datetime import datetime, timezone, timedelta
from celery import shared_task
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job
from sqlalchemy import select

log = logging.getLogger(__name__)

# How long a job can sit in a processing state before we consider it stuck
STUCK_THRESHOLD_MINUTES = 10


@celery_app.task(name="app.workers.watchdog.rescue_stuck_jobs")
def rescue_stuck_jobs():
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)

        stuck = db.execute(
            select(Job).where(
                Job.status.in_(["FETCHING", "EXTRACTING", "PARSING", "ANALYSING", "GENERATING"]),
                Job.created_at < cutoff.replace(tzinfo=None),
            )
        ).scalars().all()

        if not stuck:
            return

        log.warning("Watchdog: %d stuck job(s) found — re-queuing", len(stuck))

        for job in stuck:
            _requeue(job)

        db.commit()
        log.info("Watchdog: rescued %d job(s)", len(stuck))

    except Exception:
        log.exception("Watchdog error")
    finally:
        db.close()


def _requeue(job: Job):
    """Re-queue from the furthest safe checkpoint."""
    from app.workers.fetch import fetch_and_process
    from app.workers.extract import extract_content
    from app.workers.analyse import run_analysis
    from app.workers.document import generate_documents

    status = job.status

    if status in ("FETCHING",) or not job.s3_raw_key:
        # No raw file yet — restart from scratch
        job.status = "PENDING"
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
        log.info("Watchdog: job %d FETCHING → re-queued fetch", job.id)

    elif status in ("EXTRACTING", "PARSING") and job.s3_raw_key:
        # Raw file on S3, re-extract
        job.status = "PENDING"
        task = extract_content.apply_async(args=[job.id], queue="extract")
        job.celery_task_id = task.id
        log.info("Watchdog: job %d %s → re-queued extract", job.id, status)

    elif status == "ANALYSING" and job.normalised_data:
        # Parsed data in DB, skip straight to analysis
        job.status = "PENDING"
        task = run_analysis.apply_async(args=[job.id], queue="analyse")
        job.celery_task_id = task.id
        log.info("Watchdog: job %d ANALYSING → re-queued analyse", job.id)

    elif status == "GENERATING":
        # Analysis done, just regenerate documents
        job.status = "ANALYSING"
        task = generate_documents.apply_async(args=[job.id], queue="document")
        job.celery_task_id = task.id
        log.info("Watchdog: job %d GENERATING → re-queued document", job.id)

    else:
        # Fallback — full restart
        job.status = "PENDING"
        task = fetch_and_process.apply_async(args=[job.id], queue="fetch")
        job.celery_task_id = task.id
        log.info("Watchdog: job %d %s → fallback full restart", job.id, status)
