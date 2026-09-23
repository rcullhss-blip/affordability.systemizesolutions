"""
Backfill the slim credit data (see app.analysis.brain_snapshot) onto completed
jobs delivered before deliver.py started keeping it, so the brain feed has
accounts / at-lending snapshots for past cases too.

Runs from Celery Beat in small batches: each tick re-reads up to BATCH raw
reports from S3, re-parses them exactly as production does (route_to_parser ->
normalise_to_schema), re-attaches the at-lending snapshot for the lenders that
were scored, and stores the slim copy. It never touches lender results, scores,
documents or outcome delivery. Once every eligible job is filled it is a no-op.
A job that cannot be re-parsed gets a marker so it is not retried every tick.
"""
import logging

from sqlalchemy import Text, cast, or_, select

from app.analysis.brain_snapshot import attach_at_lending, slim_schema
from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.storage import download_bytes
from app.models.tables import Job, LenderResult
from app.parsers.normaliser import normalise_to_schema
from app.parsers.router import route_to_parser
from app.workers.analyse import FINANCIAL_TYPES

log = logging.getLogger(__name__)

BATCH = 50


@celery_app.task(name="app.workers.brain_backfill.backfill_slim_data")
def backfill_slim_data():
    db = SessionLocal()
    try:
        # Purged jobs hold SQL NULL or a JSON 'null' depending on how they were written.
        jobs = db.execute(
            select(Job).where(
                Job.status == "COMPLETE",
                Job.s3_raw_key.isnot(None),
                or_(Job.normalised_data.is_(None), cast(Job.normalised_data, Text) == "null"),
            ).order_by(Job.id.desc()).limit(BATCH)
        ).scalars().all()
        if not jobs:
            return 0

        filled = failed = 0
        for job in jobs:
            try:
                raw = download_bytes(settings.S3_BUCKET_RAW, job.s3_raw_key)
                schema = normalise_to_schema(route_to_parser(job.s3_raw_key.split("/")[-1], raw))
                names = db.execute(
                    select(LenderResult.lender_name).where(LenderResult.job_id == job.id)
                ).scalars().all()
                attach_at_lending(schema, list(names), FINANCIAL_TYPES)
                slim = slim_schema(schema) or {"_retained": "slim-v1"}
                slim["_backfilled"] = True
                job.normalised_data = slim
                filled += 1
            except Exception as exc:
                job.normalised_data = {"_retained": "slim-v1", "_backfill_error": str(exc)[:200]}
                failed += 1
            db.commit()

        log.warning("Brain backfill: filled %d, failed %d (batch of %d)", filled, failed, len(jobs))
        return filled
    except Exception:
        log.exception("Brain backfill error")
        db.rollback()
    finally:
        db.close()
