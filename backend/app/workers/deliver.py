import random
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job, LenderResult, Batch
from sqlalchemy import select, update, func
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

        # Recompute batch stats cheaply on the DB side (indexed COUNTs) instead of
        # locking the batch row and loading every job + lender_result into memory.
        # The old approach was O(n^2) and froze the gevent worker on large batches.
        if job.batch_id:
            bid = job.batch_id
            jc = lambda *conds: (
                select(func.count()).select_from(Job)
                .where(Job.batch_id == bid, *conds).scalar_subquery()
            )
            db.execute(
                update(Batch).where(Batch.id == bid).values(
                    processed             = jc(Job.status == "COMPLETE"),
                    failed                = jc(Job.status == "FAILED"),
                    green_count           = jc(Job.status == "COMPLETE", Job.traffic_light == "GREEN"),
                    amber_count           = jc(Job.status == "COMPLETE", Job.traffic_light == "AMBER"),
                    red_count             = jc(Job.status == "COMPLETE", Job.traffic_light == "RED"),
                    assessments_generated = jc(Job.s3_assessment_key.isnot(None)),
                    locs_generated        = (
                        select(func.count()).select_from(LenderResult)
                        .join(Job, LenderResult.job_id == Job.id)
                        .where(Job.batch_id == bid, LenderResult.loc_generated.is_(True))
                        .scalar_subquery()
                    ),
                )
            )
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
