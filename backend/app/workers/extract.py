from celery import shared_task
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.storage import download_bytes
from app.core.config import settings
from app.models.tables import Job
from app.models.enums import JobStatus
from app.parsers.router import route_to_parser
from app.workers.parse import parse_content


@celery_app.task(bind=True, max_retries=2, default_retry_delay=15)
def extract_content(self, job_id: int):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job or not job.s3_raw_key:
            return

        job.status = "EXTRACTING"
        db.commit()

        raw_bytes = download_bytes(settings.S3_BUCKET_RAW, job.s3_raw_key)
        filename = job.s3_raw_key.split("/")[-1]
        raw_text = route_to_parser(filename, raw_bytes)

        job.normalised_data = job.normalised_data or {}
        job.normalised_data["_raw_text"] = raw_text
        db.commit()

        parse_content.apply_async(args=[job_id], queue="parse")

    except Exception as exc:
        from celery.exceptions import Retry
        if not isinstance(exc, Retry):
            job = db.get(Job, job_id)
            if job:
                job.status = "FAILED"
                job.error_message = f"Extraction failed: {exc}"
                db.commit()
        raise self.retry(exc=exc)
    finally:
        db.close()
