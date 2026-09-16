"""
Platform health — one source of truth for "is anything wrong right now".

Used by the /api/v1/status endpoint (external monitor) and by the Slack alert
task (app.workers.alerting), so the dashboard, the endpoint and the alerts can
never disagree about what counts as a problem.

Counts and timestamps only: no client data ever leaves through this.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.tables import Batch, Case, Job

# An outcome still undelivered this long after its job completed means the
# postback sweep is stuck (it normally clears within a minute or two).
OUTCOME_STALL_MINUTES = 20
# A job not reaching COMPLETE/FAILED in this long is not simply queued behind a
# big batch: the watchdog re-queues genuinely stuck jobs every 5 minutes.
JOB_STALL_MINUTES = 45

_TERMINAL = ("COMPLETE", "FAILED")


def compute_health(db: Session) -> dict:
    now = datetime.utcnow()

    jobs_in_flight = db.execute(
        select(func.count(Job.id)).where(Job.status.notin_(_TERMINAL))
    ).scalar() or 0
    jobs_failed = db.execute(
        select(func.count(Job.id)).where(Job.status == "FAILED")
    ).scalar() or 0
    jobs_stalled = db.execute(
        select(func.count(Job.id)).where(
            Job.status.notin_(_TERMINAL),
            Job.updated_at < now - timedelta(minutes=JOB_STALL_MINUTES),
        )
    ).scalar() or 0

    undelivered = (
        db.query(Case, Job)
        .join(Job, Case.job_id == Job.id)
        .filter(Case.outcome_sent.is_(False), Job.status == "COMPLETE")
    )
    outcomes_pending = undelivered.count()
    oldest_pending = (
        undelivered.with_entities(func.min(Job.completed_at)).scalar()
        if outcomes_pending else None
    )
    outcomes_stalled = bool(
        oldest_pending and oldest_pending < now - timedelta(minutes=OUTCOME_STALL_MINUTES)
    )
    # Parked = gave up after MAX_ATTEMPTS and will not retry without a re-arm.
    # outcome_sent is checked too: the 15 Sep overlap race left delivered cases
    # holding a stale OUTCOME_FAILED status, and those are not a problem.
    outcomes_parked = db.execute(
        select(func.count(Case.id)).where(
            Case.status == "OUTCOME_FAILED", Case.outcome_sent.is_(False)
        )
    ).scalar() or 0

    last_case_at = db.execute(select(func.max(Case.created_at))).scalar()
    last_outcome_at = db.execute(select(func.max(Case.outcome_sent_at))).scalar()
    batches_active = db.execute(
        select(func.count(Batch.id)).where(
            Batch.created_at > now - timedelta(days=1),
            Batch.processed < Batch.total_reports,
        )
    ).scalar() or 0

    problems = []
    if jobs_failed:
        problems.append(f"{jobs_failed} assessment job(s) FAILED")
    if jobs_stalled:
        problems.append(f"{jobs_stalled} job(s) stuck >{JOB_STALL_MINUTES}m in the pipeline")
    if outcomes_stalled:
        mins = int((now - oldest_pending).total_seconds() // 60)
        problems.append(f"{outcomes_pending} outcome(s) undelivered, oldest {mins}m old")
    if outcomes_parked:
        problems.append(f"{outcomes_parked} outcome(s) parked after max retries")

    iso = lambda t: t.isoformat() + "Z" if t else None
    return {
        "checked_at": iso(now),
        "healthy": not problems,
        "problems": problems,
        "jobs": {"in_flight": jobs_in_flight, "failed": jobs_failed, "stalled": jobs_stalled},
        "outcomes": {
            "pending": outcomes_pending,
            "stalled": outcomes_stalled,
            "parked": outcomes_parked,
            "last_sent_at": iso(last_outcome_at),
        },
        "intake": {
            "last_case_at": iso(last_case_at),
            "batches_in_progress_24h": batches_active,
        },
    }
