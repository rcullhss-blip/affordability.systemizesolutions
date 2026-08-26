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
from app.core.config import settings
from app.models.tables import Job
from sqlalchemy import select, func

log = logging.getLogger(__name__)

# How long a job can sit in a processing state before we consider it stuck
STUCK_THRESHOLD_MINUTES = 10

# Broker queues that carry pipeline work. While any of these has a backlog,
# "old" mid-pipeline jobs are simply waiting their turn, not stranded.
PIPELINE_QUEUES = ("fetch", "extract", "parse", "analyse", "document", "deliver")


def _queue_backlog() -> dict:
    """Length of each pipeline queue on the Redis broker (Celery stores a queue as
    a list named after it). Raises if the broker is unreachable."""
    import redis
    r = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=5)
    return {q: int(r.llen(q)) for q in PIPELINE_QUEUES}


@celery_app.task(name="app.workers.watchdog.rescue_stuck_jobs")
def rescue_stuck_jobs():
    # A job is only "stranded" if nothing in the broker will ever pick it up.
    # On a large batch (e.g. 32k rows created in one upload) most jobs legitimately
    # sit PENDING/FETCHING/... for hours while the queues drain; re-queuing them
    # would enqueue duplicates every 5 minutes and multiply the work. So: if any
    # pipeline queue still has a backlog, do nothing this tick.
    try:
        backlog = _queue_backlog()
    except Exception:
        log.exception("Watchdog: cannot read broker queue lengths — skipping this tick")
        return
    queued = sum(backlog.values())
    if queued:
        log.info("Watchdog: %d task(s) queued (%s) — nothing stranded, skipping", queued, backlog)
        return

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)

        # Include PENDING: a job whose fetch task was lost (e.g. broker/DB outage)
        # sits in PENDING forever otherwise — this was the gap that stranded 1,002
        # jobs in the 2026-07-06 outage. Re-queuing is safe: analyse clears prior
        # LenderResults before insert, so no duplicates.
        # Age is measured from the last status change (updated_at), not creation:
        # a job that moved stage 2 minutes ago is in flight, however old the row is.
        last_touch = func.coalesce(Job.updated_at, Job.created_at)
        stuck = db.execute(
            select(Job).where(
                Job.status.in_(["PENDING", "FETCHING", "EXTRACTING", "PARSING", "ANALYSING", "GENERATING"]),
                last_touch < cutoff.replace(tzinfo=None),
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

    elif status in ("EXTRACTING", "PARSING", "PENDING") and job.s3_raw_key:
        # Raw file on S3, re-extract (PENDING-with-raw-key = fetched but never extracted)
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
