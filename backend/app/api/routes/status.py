"""
Ops status — aggregate health counters for an external monitor.

Deliberately separate from /analytics and /cases: it is guarded by its own
MONITOR_API_KEY and returns COUNTS AND TIMESTAMPS ONLY, never client data, so
the key can live in a monitoring job without exposing credit reports. If no
MONITOR_API_KEY is configured the route is closed to everyone.

`problems` is the point: an empty list means nothing needs a human.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models.tables import Batch, Case, Job

router = APIRouter()

_key_header = APIKeyHeader(name="X-Monitor-Key", auto_error=False)

# An outcome still undelivered after this long means the postback sweep is stuck
# (it normally clears within a minute or two of a job completing).
OUTCOME_STALL_MINUTES = 20
# A job that has not reached COMPLETE/FAILED in this long is not just queued behind
# a big batch; the watchdog re-queues stuck jobs every 5 minutes.
JOB_STALL_MINUTES = 45


def _require_monitor_key(api_key: Optional[str] = Security(_key_header)) -> None:
    if not settings.MONITOR_API_KEY or api_key != settings.MONITOR_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid monitor key")


@router.get("", dependencies=[Depends(_require_monitor_key)])
def ops_status(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    _terminal = ("COMPLETE", "FAILED")

    jobs_in_flight = db.execute(
        select(func.count(Job.id)).where(Job.status.notin_(_terminal))
    ).scalar() or 0
    jobs_failed = db.execute(
        select(func.count(Job.id)).where(Job.status == "FAILED")
    ).scalar() or 0
    jobs_stalled = db.execute(
        select(func.count(Job.id)).where(
            Job.status.notin_(_terminal),
            Job.updated_at < now - timedelta(minutes=JOB_STALL_MINUTES),
        )
    ).scalar() or 0

    # Cases whose assessment finished but whose outcome has not gone back yet.
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

    return {
        "checked_at": now.isoformat() + "Z",
        "healthy": not problems,
        "problems": problems,
        "jobs": {"in_flight": jobs_in_flight, "failed": jobs_failed, "stalled": jobs_stalled},
        "outcomes": {
            "pending": outcomes_pending,
            "stalled": outcomes_stalled,
            "parked": outcomes_parked,
            "last_sent_at": last_outcome_at.isoformat() + "Z" if last_outcome_at else None,
        },
        "intake": {
            "last_case_at": last_case_at.isoformat() + "Z" if last_case_at else None,
            "batches_in_progress_24h": batches_active,
        },
    }
