import logging
import random
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job, LenderResult, Batch
from app.analysis.checkpoint_audit import (
    audit_report, is_checkpoint, needs_spot_check, format_checkpoint,
)
from sqlalchemy import select, update, func
from datetime import datetime

log = logging.getLogger("checkpoint")

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
        # Self-clean: the parsed report (jsonb) is intermediate data only needed
        # up to document generation. Docs are now in S3, so drop it to keep the
        # jobs table from growing unbounded. Re-runs can re-fetch from s3_raw_key.
        job.normalised_data = None

        # Randomly flag for spot check (on top of any audit-driven flag above)
        if not job.spot_check_required and random.random() < SPOT_CHECK_RATE:
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

            # ── Checkpoint summary at 3 / 8 / 15 / 25 / 50 processed reports ────
            # A cumulative health snapshot of the batch so a person can eyeball the
            # pool during the live ramp. Defensive: never fails the delivery task.
            try:
                batch = db.get(Batch, bid)
                processed = batch.processed if batch else 0
                if is_checkpoint(processed):
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
