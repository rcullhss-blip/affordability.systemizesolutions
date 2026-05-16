import httpx
import uuid
from celery import shared_task
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.storage import upload_bytes
from app.core.config import settings
from app.models.tables import Job
from app.models.enums import JobStatus
from app.workers.extract import extract_content


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def fetch_and_process(self, job_id: int):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return

        job.status = "FETCHING"
        db.commit()

        if job.source_url:
            try:
                with httpx.Client(timeout=60, follow_redirects=True) as client:
                    response = client.get(job.source_url)
                    response.raise_for_status()
                raw_bytes = response.content
                filename = job.source_url.split("/")[-1].split("?")[0] or "report"
                s3_key = f"raw/{uuid.uuid4()}/{filename}"
                upload_bytes(settings.S3_BUCKET_RAW, s3_key, raw_bytes)
                job.s3_raw_key = s3_key
                db.commit()
            except Exception as exc:
                raise self.retry(exc=exc)

        extract_content.apply_async(args=[job_id], queue="extract")

    except Exception as exc:
        job = db.get(Job, job_id)
        if job:
            job.status = "FAILED"
            job.error_message = str(exc)
            db.commit()
        raise
    finally:
        db.close()
