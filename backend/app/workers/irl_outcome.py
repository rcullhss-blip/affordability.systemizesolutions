"""
Outcome postback: report completed IRL case assessments back to the PCP platform.

Runs on a beat schedule. For every case whose linked Job has COMPLETED and whose
outcome has not yet been delivered, POST the result to the PCP platform's
/irl-outcome webhook. Reliable + at scale:
  - decoupled from assessment (a sweep, so a restart never loses an outcome),
  - idempotent on our side (a case is only marked sent on a 2xx),
  - retried on the next tick for transient failures,
  - capped so a permanently-failing case surfaces as OUTCOME_FAILED instead of
    hammering the endpoint forever.
"""
from datetime import datetime

import httpx

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.config import settings
from app.core.storage import get_download_url
from app.models.tables import Case, Job, LenderResult

MAX_ATTEMPTS = 8      # after this a case is parked as OUTCOME_FAILED (requeue by resetting attempts)
BATCH_LIMIT = 100     # cases per tick — bounds each run so it scales predictably


def _build_documents(job: Job, lenders: list) -> list:
    """Signed download URLs for the branded LOCs (one per lender) + the assessment.
    The PCP platform fetches + stores these on receipt (URLs are short-lived)."""
    docs = []
    try:
        if job.s3_assessment_key:
            docs.append({
                "type": "affordability_assessment",
                "url": get_download_url(settings.S3_BUCKET_OUTPUTS, job.s3_assessment_key),
            })
        for lr in lenders:
            if lr.loc_generated and lr.s3_loc_key:
                docs.append({
                    "type": "irl_loc",
                    "lender": lr.lender_name,
                    "url": get_download_url(settings.S3_BUCKET_OUTPUTS, lr.s3_loc_key),
                })
    except Exception:
        # Never let URL signing break the postback — retried next tick.
        raise
    return docs


def _build_outcome(case: Case, job: Job, lenders: list) -> dict:
    tl = job.traffic_light
    eligible = tl in ("GREEN", "AMBER")
    return {
        "lead_reference": case.lead_reference,
        "event": "accepted" if eligible else "rejected",
        "outcome": "eligible" if eligible else "ineligible",
        "traffic_light": tl,
        "claim_value": None,  # V1 engine produces no monetary claim value
        "destination_brand_id": case.destination_brand_id,  # echo back what the hub sent
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lenders": [
            {
                "lender": lr.lender_name,
                "traffic_light": lr.traffic_light,
                "claim_score": lr.claim_score,
                "loc_generated": lr.loc_generated,
            }
            for lr in lenders
        ],
        "documents": _build_documents(job, lenders),
    }


@celery_app.task(name="app.workers.irl_outcome.post_case_outcomes")
def post_case_outcomes():
    if not settings.PCP_OUTCOME_URL:
        return {"skipped": "PCP_OUTCOME_URL not configured"}

    db = SessionLocal()
    sent = failed = 0
    try:
        rows = (
            db.query(Case, Job)
            .join(Job, Case.job_id == Job.id)
            .filter(
                Case.outcome_sent.is_(False),
                Case.status != "OUTCOME_FAILED",
                Job.status == "COMPLETE",
            )
            .limit(BATCH_LIMIT)
            .all()
        )

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": settings.PCP_OUTCOME_API_KEY,
        }

        for case, job in rows:
            lenders = db.query(LenderResult).filter(LenderResult.job_id == job.id).all()
            body = _build_outcome(case, job, lenders)

            # Snapshot the result on the case regardless of delivery success
            case.traffic_light = job.traffic_light
            case.outcome = body["outcome"]
            case.outcome_attempts = (case.outcome_attempts or 0) + 1

            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.post(settings.PCP_OUTCOME_URL, json=body, headers=headers)
                resp.raise_for_status()
                case.outcome_sent = True
                case.outcome_sent_at = datetime.utcnow()
                case.status = "OUTCOME_SENT"
                case.last_error = None
                sent += 1
            except Exception as exc:
                case.last_error = str(exc)[:500]
                if case.outcome_attempts >= MAX_ATTEMPTS:
                    case.status = "OUTCOME_FAILED"
                failed += 1

            db.commit()

        return {"sent": sent, "failed": failed, "considered": len(rows)}
    finally:
        db.close()
