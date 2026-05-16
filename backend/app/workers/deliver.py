import random
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job, LenderResult
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

    except Exception as exc:
        job = db.get(Job, job_id)
        if job:
            job.status = "FAILED"
            job.error_message = f"Delivery failed: {exc}"
            db.commit()
        raise self.retry(exc=exc)
    finally:
        db.close()
