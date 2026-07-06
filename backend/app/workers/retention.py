"""
Retention purge — keeps Postgres bounded by deleting fully-aged batch data.
Runs daily via Celery Beat. Batches older than RETENTION_DAYS (and all their
jobs / lender_results / orphaned clients+accounts) are removed. Generated
documents live in S3 and are NOT touched by this.
"""
import logging
from datetime import datetime, timezone, timedelta
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Batch, Job, LenderResult, Account, Client
from sqlalchemy import select, delete, func

log = logging.getLogger(__name__)

RETENTION_DAYS = 30


@celery_app.task(name="app.workers.retention.purge_old_batches")
def purge_old_batches():
    db = SessionLocal()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).replace(tzinfo=None)
        old_batches = select(Batch.id).where(Batch.created_at < cutoff)

        n_old = db.scalar(select(func.count()).select_from(Batch).where(Batch.created_at < cutoff))
        if not n_old:
            return

        old_jobs = select(Job.id).where(Job.batch_id.in_(old_batches))

        # Clients referenced ONLY by old-batch jobs become orphans (per-report
        # clients normally map 1:1 to a job; this guards against shared clients).
        keep_clients = select(Job.client_id).where(
            Job.client_id.isnot(None), Job.batch_id.notin_(old_batches)
        )
        orphan_ids = db.execute(
            select(Job.client_id).where(
                Job.client_id.isnot(None),
                Job.batch_id.in_(old_batches),
                Job.client_id.notin_(keep_clients),
            ).distinct()
        ).scalars().all()

        # FK-safe delete order: lender_results -> jobs -> accounts -> clients -> batches
        db.execute(delete(LenderResult).where(LenderResult.job_id.in_(old_jobs)))
        db.execute(delete(Job).where(Job.batch_id.in_(old_batches)))
        if orphan_ids:
            db.execute(delete(Account).where(Account.client_id.in_(orphan_ids)))
            db.execute(delete(Client).where(Client.id.in_(orphan_ids)))
        db.execute(delete(Batch).where(Batch.created_at < cutoff))

        db.commit()
        log.warning("Retention: purged %d batch(es) older than %d days (%d orphan clients)",
                    n_old, RETENTION_DAYS, len(orphan_ids))
    except Exception:
        log.exception("Retention purge error")
        db.rollback()
    finally:
        db.close()
