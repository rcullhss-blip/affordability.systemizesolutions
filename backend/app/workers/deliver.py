import random
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job, LenderResult, Batch
from sqlalchemy import select
from datetime import datetime

SPOT_CHECK_RATE = 0.025  # 25 in 1000 completed jobs flagged for review


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def deliver_outputs(self, job_id: int):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return

        results = db.query(LenderResult).filter(LenderResult.job_id == job.id).all()
        for result in results:
            result.delivery_status = "PENDING"

        job.status = "COMPLETE"
        job.completed_at = datetime.utcnow()

        # Randomly flag for spot check
        if random.random() < SPOT_CHECK_RATE:
            job.spot_check_required = True

        db.commit()

        # Recompute batch stats now that this job is COMPLETE — single source of truth
        if job.batch_id:
            batch = db.execute(
                select(Batch).where(Batch.id == job.batch_id).with_for_update()
            ).scalar_one_or_none()
            if batch:
                complete_jobs = db.execute(select(Job).where(Job.batch_id == batch.id, Job.status == "COMPLETE")).scalars().all()
                failed_jobs   = db.execute(select(Job).where(Job.batch_id == batch.id, Job.status == "FAILED")).scalars().all()
                all_lrs       = db.execute(select(LenderResult).join(Job).where(Job.batch_id == batch.id)).scalars().all()
                batch.green_count          = sum(1 for j in complete_jobs if j.traffic_light == "GREEN")
                batch.amber_count          = sum(1 for j in complete_jobs if j.traffic_light == "AMBER")
                batch.red_count            = sum(1 for j in complete_jobs if j.traffic_light == "RED")
                batch.processed            = len(complete_jobs)
                batch.failed               = len(failed_jobs)
                batch.locs_generated       = sum(1 for r in all_lrs if r.loc_generated)
                batch.assessments_generated= sum(1 for j in complete_jobs if j.s3_assessment_key)
                db.commit()

    except Exception as exc:
        from celery.exceptions import Retry
        if not isinstance(exc, Retry):
            job = db.get(Job, job_id)
            if job:
                job.status = "FAILED"
                job.error_message = f"Delivery failed: {exc}"
                db.commit()
        raise self.retry(exc=exc)
    finally:
        db.close()
