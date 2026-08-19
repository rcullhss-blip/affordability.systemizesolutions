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
import logging
from datetime import datetime

import httpx
from sqlalchemy.orm import selectinload

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.config import settings
from app.core.storage import get_download_url, upload_bytes
from app.core.lender_blocklist import is_blocked
from app.documents.tracker_csv import (
    build_case_tracker_rows, rows_to_csv_bytes, prepend_case_key, tracker_header_for,
    format_dob,
)
from app.models.tables import Case, Job, LenderResult

log = logging.getLogger("irl_outcome")

MAX_ATTEMPTS = 8      # after this a case is parked as OUTCOME_FAILED (requeue by resetting attempts)
# Cases per tick. Raised for bulk partner runs (e.g. Woodville 100k) so per-client
# postbacks keep pace with the throttled runner's completion rate.
BATCH_LIMIT = 500

# Internal traffic light -> the partner tracker's Analysis Status label.
_ANALYSIS_STATUS = {"GREEN": "Strong", "AMBER": "Mid", "RED": "Weak"}


def _signed(bucket: str, key: str | None) -> str:
    """A download URL valid long enough for the partner to fetch + store it.
    7-day presigned in prod (AWS SigV4 max); a local proxy path in dev."""
    if not key:
        return ""
    if settings.use_local_storage:
        return get_download_url(bucket, key)
    from app.core.s3 import generate_presigned_url
    try:
        return generate_presigned_url(bucket, key, expires_in=604800)  # 7 days
    except Exception:
        return ""


def _client_fields(case: Case, job: Job) -> dict:
    """Client identity for the tracker. `job.normalised_data` is cleared at
    completion, so the durable sources are the Client row (full name/dob/address)
    with the denormalised Case fields as a fallback."""
    client = getattr(job, "client", None)
    name = (getattr(client, "name", None) or case.client_name or "")
    dob = getattr(client, "dob", None) or case.client_dob
    address = getattr(client, "address", None) or case.client_postcode or ""
    return {
        "name": name,
        "dob": str(dob) if dob else "",
        "address": address,
        "email": "",   # not retained past completion (parity with batch tracker)
        "phone": "",
    }


def _build_documents(case: Case, job: Job, lenders: list) -> list:
    """Signed download URLs for the case documents the partner stores on receipt:
    the credit report, the assessment, the branded LOCs (one per lender), and a
    per-case tracker CSV in the Proclaim batch-tracker format. URLs are 7-day
    signed. Best-effort per artefact — never let one missing file break delivery."""
    docs = []

    # Credit report as a rendered PDF (outputs bucket). Fall back to the raw
    # report JSON only for older cases generated before PDF rendering existed.
    if job.s3_credit_report_key:
        report_url = _signed(settings.S3_BUCKET_OUTPUTS, job.s3_credit_report_key)
    else:
        report_url = _signed(settings.S3_BUCKET_RAW, job.s3_raw_key)
    if report_url:
        docs.append({"type": "credit_report", "url": report_url})

    assessment_url = _signed(settings.S3_BUCKET_OUTPUTS, job.s3_assessment_key)
    if assessment_url:
        docs.append({"type": "affordability_assessment", "url": assessment_url})

    loc_urls = {}  # s3_loc_key -> signed url (reused by the tracker CSV)
    for lr in lenders:
        if lr.loc_generated and lr.s3_loc_key:
            url = _signed(settings.S3_BUCKET_OUTPUTS, lr.s3_loc_key)
            loc_urls[lr.s3_loc_key] = url
            docs.append({"type": "irl_loc", "lender": lr.lender_name, "url": url})

    # ── Per-case tracker CSV (same columns Ryan's Proclaim reads for batches) ──
    # One row per LOC/defendant. Best-effort: a tracker failure must not stop the
    # assessment/LOCs/credit report from being delivered.
    try:
        ts = (job.completed_at or job.created_at)
        ts = ts.strftime("%d/%m/%Y %H:%M") if ts else ""
        # Ryans' middleware reads a leading "Case Key" column ("IL") as the case
        # type and expects UK DD/MM/YYYY dates; our lead reference stays in Client
        # Reference so Ryans can echo it back on the case-creation email. Other
        # firms keep the original layout and date format.
        firm = job.firm or case.destination_brand_id
        client_fields = _client_fields(case, job)
        client_fields["dob"] = format_dob(client_fields.get("dob"), firm)
        rows = build_case_tracker_rows(
            client_reference=case.lead_reference,
            timestamp=ts,
            **client_fields,
            lenders=[(lr.lender_name, lr.traffic_light, lr.loc_generated, lr.s3_loc_key)
                     for lr in lenders],
            is_blocked=is_blocked,
            credit_report_url=report_url,
            assessment_url=assessment_url,
            loc_url_for=lambda k: loc_urls.get(k, ""),
        )
        rows = prepend_case_key(rows, firm)
        csv_bytes = rows_to_csv_bytes(rows, tracker_header_for(firm))
        # Deterministic key so retries overwrite rather than pile up.
        if job.s3_assessment_key:
            tracker_key = job.s3_assessment_key.rsplit(
                "_affordability_assessment.pdf", 1)[0] + "_affordability_tracker.csv"
        else:
            tracker_key = f"outputs/irl-case/{case.lead_reference}/affordability_tracker.csv"
        upload_bytes(settings.S3_BUCKET_OUTPUTS, tracker_key, csv_bytes, "text/csv")
        tracker_url = _signed(settings.S3_BUCKET_OUTPUTS, tracker_key)
        if tracker_url:
            docs.append({"type": "tracker_csv", "url": tracker_url})
    except Exception:
        log.exception("Tracker CSV build failed for case %s (delivery continues)",
                      case.lead_reference)

    return docs


def _build_outcome(case: Case, job: Job, lenders: list) -> dict:
    tl = job.traffic_light
    eligible = tl in ("GREEN", "AMBER")
    return {
        "lead_reference": case.lead_reference,
        "batch_id": case.partner_batch_id,   # echoed so the partner groups a batch
        "source": case.source,
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
                "analysis_status": _ANALYSIS_STATUS.get(lr.traffic_light, lr.traffic_light),
                "case_status": "LOC Generated" if lr.loc_generated else "No LOC",
                "claim_score": lr.claim_score,
                "loc_generated": lr.loc_generated,
            }
            for lr in lenders
        ],
        "documents": _build_documents(case, job, lenders),
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
            .options(selectinload(Job.client))   # tracker needs client name/address; avoid an N+1
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
