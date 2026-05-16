from celery import shared_task
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job, LenderResult
from app.models.enums import JobStatus, DeliveryStatus
from datetime import datetime


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def deliver_outputs(self, job_id: int):
    """
    Delivery stubs — routes to the correct delivery method based on job config.
    Currently marks as PENDING delivery; active integrations are additive.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return

        # Mark all lender results as pending delivery
        results = db.query(LenderResult).filter(LenderResult.job_id == job.id).all()
        for result in results:
            result.delivery_status = "PENDING"

        job.status = "COMPLETE"
        job.completed_at = datetime.utcnow()
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
