import logging
import random
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job, LenderResult, Batch
from app.analysis.checkpoint_audit import (
    audit_report, is_checkpoint, needs_spot_check, format_checkpoint,
)
from app.workers.batch_stats import bump_batch_stats, recompute_batch_stats
from app.analysis.brain_snapshot import slim_schema
from sqlalchemy import select, update, func
from datetime import datetime

log = logging.getLogger("checkpoint")

SPOT_CHECK_RATE = 0.025  # 25 in 1000 completed jobs flagged for review (small batches)
# On large batches a flat 2.5% is unreviewable (32k reports -> ~800 random flags),
# so the random rate is scaled to yield about this many per batch. Audit-driven
# flags (parser gaps, scoring misses) are never capped.
SPOT_CHECK_MAX_RANDOM_PER_BATCH = 100


def _spot_check_rate(job: Job) -> float:
    total = getattr(getattr(job, "batch", None), "total_reports", 0) or 0
    if total <= 0:
        return SPOT_CHECK_RATE
    return min(SPOT_CHECK_RATE, SPOT_CHECK_MAX_RANDOM_PER_BATCH / total)


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

        # ── Per-report audit (runs while normalised_data is still present) ──────
        # Catches parser gaps / scoring misses on the new report format during the
        # live ramp. Any MEDIUM+ finding flags the job for human spot check.
        # Fully defensive: an audit error must never fail delivery.
        try:
            schema = job.normalised_data or {}
            lender_results = [{"traffic_light": r.traffic_light,
                               "lender_name": r.lender_name} for r in results]
            findings = audit_report(schema, lender_results)
            if findings:
                for f in findings:
                    log.warning("AUDIT job=%s [%s] %s: %s",
                                job.id, f["severity"], f["code"], f["detail"])
                if needs_spot_check(findings):
                    job.spot_check_required = True
        except Exception as audit_exc:
            log.warning("AUDIT job=%s failed to run: %s", job_id, audit_exc)

        job.status = "COMPLETE"
        job.completed_at = datetime.utcnow()
        # Self-clean: the raw report text and client identity are only needed up to
        # document generation. Docs are now in S3, so keep just the slim credit data
        # the engine scored on (read by the brain feed); re-runs re-fetch from s3_raw_key.
        job.normalised_data = slim_schema(job.normalised_data)

        # Randomly flag for spot check (on top of any audit-driven flag above)
        if not job.spot_check_required and random.random() < _spot_check_rate(job):
            job.spot_check_required = True

        db.commit()

        # Batch counters: O(1) atomic increments here; the authoritative full
        # recount runs in the watchdog every 5 min (and at the early checkpoints
        # below). Recounting on every completion was O(n) per job — on a 32k batch
        # Postgres CPU climbed and throughput fell ~25% across the run.
        if job.batch_id:
            bid = job.batch_id
            bump_batch_stats(db, job, results)
            db.commit()

            # ── Checkpoint summary at 3 / 8 / 15 / 25 / 50 processed reports ────
            # A cumulative health snapshot of the batch so a person can eyeball the
            # pool during the live ramp. Defensive: never fails the delivery task.
            try:
                batch = db.get(Batch, bid)
                processed = batch.processed if batch else 0
                if is_checkpoint(processed):
                    recompute_batch_stats(db, bid)   # exact figures for the snapshot (n is small here)
                    db.commit()
                    db.refresh(batch)
                    jc = lambda *conds: (
                        select(func.count()).select_from(Job)
                        .where(Job.batch_id == bid, *conds).scalar_subquery()
                    )
                    completed_no_lenders = db.execute(
                        select(func.count()).select_from(Job).where(
                            Job.batch_id == bid, Job.status == "COMPLETE",
                            ~Job.lender_results.any(),
                        )
                    ).scalar() or 0
                    green_without_loc = db.execute(
                        select(func.count()).select_from(LenderResult)
                        .join(Job, LenderResult.job_id == Job.id)
                        .where(Job.batch_id == bid,
                               LenderResult.traffic_light == "GREEN",
                               LenderResult.loc_generated.is_(False))
                    ).scalar() or 0
                    agg = {
                        "total": batch.total_reports, "failed": batch.failed,
                        "green": batch.green_count, "amber": batch.amber_count,
                        "red": batch.red_count,
                        "completed_no_lenders": completed_no_lenders,
                        "missing_assessment": db.execute(
                            select(jc(Job.status == "COMPLETE",
                                      Job.s3_assessment_key.is_(None)))).scalar() or 0,
                        "green_without_loc": green_without_loc,
                        "flagged_for_review": db.execute(
                            select(jc(Job.spot_check_required.is_(True)))).scalar() or 0,
                    }
                    log.warning("\n%s", format_checkpoint(bid, processed, agg))
            except Exception as cp_exc:
                log.warning("CHECKPOINT batch=%s failed to run: %s", bid, cp_exc)

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
