"""
Batch counter maintenance.

Two cooperating mechanisms keep Batch.processed / failed / green_count / ... right:

* bump_batch_stats  — O(1) atomic increments run by deliver.py on every job
  completion. Cheap regardless of batch size.
* recompute_batch_stats — the authoritative full recount (indexed COUNTs over the
  batch's jobs + lender_results). O(n) in batch size, so it is NOT run per job:
  the watchdog runs it every 5 minutes for batches with recent activity, and
  deliver.py runs it at the small early checkpoints. It corrects any drift from
  the increments (e.g. a job re-run via /retry-failed, or a task retried after
  the bump committed).

Previously deliver.py ran the full recount on every completion, which is O(n)
per job and O(n^2) per batch — on a 32k batch Postgres CPU climbed steadily and
throughput fell ~25% over the run as the counts grew.
"""

from datetime import datetime, timedelta

from sqlalchemy import select, update, func, distinct
from sqlalchemy.orm import Session

from app.models.tables import Job, LenderResult, Batch


def bump_batch_stats(db: Session, job: Job, results: list) -> None:
    """Atomic +1s for one just-completed job. `results` are its LenderResults."""
    if not job.batch_id:
        return
    tl = job.traffic_light
    n_locs = sum(1 for r in results if getattr(r, "loc_generated", False))
    db.execute(
        update(Batch).where(Batch.id == job.batch_id).values(
            processed             = Batch.processed + 1,
            green_count           = Batch.green_count + (1 if tl == "GREEN" else 0),
            amber_count           = Batch.amber_count + (1 if tl == "AMBER" else 0),
            red_count             = Batch.red_count + (1 if tl == "RED" else 0),
            assessments_generated = Batch.assessments_generated + (1 if job.s3_assessment_key else 0),
            locs_generated        = Batch.locs_generated + n_locs,
        )
    )


def recompute_batch_stats(db: Session, batch_id: int) -> None:
    """Authoritative recount of every counter for one batch (indexed COUNTs)."""
    jc = lambda *conds: (
        select(func.count()).select_from(Job)
        .where(Job.batch_id == batch_id, *conds).scalar_subquery()
    )
    db.execute(
        update(Batch).where(Batch.id == batch_id).values(
            processed             = jc(Job.status == "COMPLETE"),
            failed                = jc(Job.status == "FAILED"),
            green_count           = jc(Job.status == "COMPLETE", Job.traffic_light == "GREEN"),
            amber_count           = jc(Job.status == "COMPLETE", Job.traffic_light == "AMBER"),
            red_count             = jc(Job.status == "COMPLETE", Job.traffic_light == "RED"),
            assessments_generated = jc(Job.s3_assessment_key.isnot(None)),
            locs_generated        = (
                select(func.count()).select_from(LenderResult)
                .join(Job, LenderResult.job_id == Job.id)
                .where(Job.batch_id == batch_id, LenderResult.loc_generated.is_(True))
                .scalar_subquery()
            ),
        )
    )


def active_batch_ids(db: Session, within_minutes: int = 15) -> list[int]:
    """Batches with any job touched recently — the ones whose counters can drift."""
    since = datetime.utcnow() - timedelta(minutes=within_minutes)
    return list(
        db.execute(
            select(distinct(Job.batch_id)).where(
                Job.batch_id.isnot(None),
                func.coalesce(Job.updated_at, Job.created_at) >= since,
            )
        ).scalars()
    )
