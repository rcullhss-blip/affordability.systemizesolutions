"""
Cases API — IRL cases received from the PCP platform.

Powers the admin "Cases" tab (mirrors Batches): list, detail, and a summary
count. Case status is the intake/postback state; `job_status` is the live
assessment-pipeline state of the linked Job.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models.tables import Case, Job, LenderResult
from app.api.routes.webhook import _require_irl_key
from app.workers.fetch import fetch_and_process

router = APIRouter()


def _signed(bucket: str, key: str | None) -> str:
    """7-day presigned download URL (local proxy path in dev). Best-effort."""
    if not key:
        return ""
    if settings.use_local_storage:
        from app.core.storage import get_download_url
        return get_download_url(bucket, key)
    from app.core.s3 import generate_presigned_url
    try:
        return generate_presigned_url(bucket, key, expires_in=604800)  # 7 days
    except Exception:
        return ""


def _case_documents(case: Case, job: Job, db: Session) -> dict:
    """Signed URLs for a case's artefacts — credit report, assessment, the
    per-case tracker CSV, and generated LOCs. The tracker key mirrors the one
    written by app.workers.irl_outcome so this points at the same object."""
    OUTB, RAW = settings.S3_BUCKET_OUTPUTS, settings.S3_BUCKET_RAW
    report = (_signed(OUTB, job.s3_credit_report_key) if job.s3_credit_report_key
              else _signed(RAW, job.s3_raw_key))
    if job.s3_assessment_key:
        tracker_key = (job.s3_assessment_key.rsplit("_affordability_assessment.pdf", 1)[0]
                       + "_affordability_tracker.csv")
    else:
        tracker_key = f"outputs/irl-case/{case.lead_reference}/affordability_tracker.csv"
    locs = [
        {"lender": lr.lender_name, "url": _signed(OUTB, lr.s3_loc_key)}
        for lr in db.query(LenderResult)
        .filter(LenderResult.job_id == job.id,
                LenderResult.loc_generated.is_(True),
                LenderResult.s3_loc_key.isnot(None))
        .all()
    ]
    return {
        "credit_report": report,
        "assessment": _signed(OUTB, job.s3_assessment_key),
        "tracker_csv": _signed(OUTB, tracker_key),
        "locs": locs,
    }


def _serialise_case(case: Case, job) -> dict:
    return {
        "id": case.id,
        "lead_reference": case.lead_reference,
        "bosh_reference": case.bosh_reference,
        "source": case.source,
        "destination_brand_id": case.destination_brand_id,
        "status": case.status,                        # QUEUED / OUTCOME_SENT / OUTCOME_FAILED
        "job_status": job.status if job else None,    # PENDING..COMPLETE (live pipeline state)
        "traffic_light": (job.traffic_light if job else None) or case.traffic_light,
        "outcome": case.outcome,
        "outcome_sent": case.outcome_sent,
        "outcome_sent_at": case.outcome_sent_at.isoformat() if case.outcome_sent_at else None,
        "outcome_attempts": case.outcome_attempts,
        "last_error": case.last_error,
        "client_name": case.client_name,
        "client_postcode": case.client_postcode,
        "triage": case.triage,
        "job_id": case.job_id,
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }


@router.get("/")
def list_cases(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(Case, Job)
        .outerjoin(Job, Case.job_id == Job.id)
        # Cases that belong to a tagged bulk run (e.g. Woodville) appear as a single
        # batch on the Batches tab, not scattered here.
        .filter(Case.partner_batch_id.is_(None))
        .order_by(Case.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_serialise_case(c, j) for c, j in rows]


@router.get("/stats/summary")
def cases_summary(db: Session = Depends(get_db)):
    # Single (non-batch) cases only — bulk-run cases are summarised on the Batches tab.
    _single = Case.partner_batch_id.is_(None)
    total = db.query(func.count(Case.id)).filter(_single).scalar() or 0
    sent = db.query(func.count(Case.id)).filter(_single, Case.outcome_sent.is_(True)).scalar() or 0
    failed = db.query(func.count(Case.id)).filter(_single, Case.status == "OUTCOME_FAILED").scalar() or 0
    # LOCs delivered to the PCP system: generated LOCs on cases whose outcome was sent.
    locs_sent = (
        db.query(func.count(LenderResult.id))
        .join(Job, LenderResult.job_id == Job.id)
        .join(Case, Case.job_id == Job.id)
        .filter(LenderResult.loc_generated.is_(True), Case.outcome_sent.is_(True), _single)
        .scalar() or 0
    )
    return {
        "total": total,
        "outcome_sent": sent,
        "locs_sent": locs_sent,
        "failed": failed,
        "in_progress": max(total - sent - failed, 0),
    }


class ReprocessCasesAsFirm(BaseModel):
    lead_references: list[str]
    # Target letterhead, e.g. "ryans". Omit (null) to RE-SCORE IN PLACE — each case
    # keeps its existing firm; use this to re-run cases through updated scoring/parsing
    # without changing branding.
    firm: str | None = None


@router.post("/reprocess-as-firm", dependencies=[Depends(_require_irl_key)])
def reprocess_cases_as_firm(body: ReprocessCasesAsFirm, db: Session = Depends(get_db)):
    """Re-run specific existing IRL cases under a DIFFERENT solicitor firm and
    re-deliver them through the per-case outcome postback.

    For each lead_reference: clone the retained raw report into a new PENDING job
    tagged with the target firm, re-point the Case at it, and re-arm the outcome
    (outcome_sent=False). When the new job completes, the postback re-delivers the
    freshly firm-branded LOCs + PDF credit report + per-case tracker CSV. The
    partner replaces the prior IRL doc set on receipt, so corrected docs supersede
    any earlier ones with no duplicates.

    The raw report is re-fetched from S3 (normalised_data is purged post-delivery),
    so this works long after the original run. Use this to (re)brand a hand-picked
    set of single hub cases — e.g. move 44 cases onto the Ryans letterhead — where
    the batch-level /batches/reprocess-as-firm would sweep in unrelated cases.
    """
    firm = (body.firm or "").strip().lower()   # "" -> re-score in place (keep each case's firm)
    # De-dupe while preserving order; a repeated lead_reference must re-run once.
    refs = list(dict.fromkeys(r for r in (body.lead_references or []) if r))
    if not refs:
        raise HTTPException(status_code=422, detail="lead_references must be a non-empty list")

    queued: list[int] = []
    results = []
    for ref in refs:
        case = db.query(Case).filter(Case.lead_reference == ref).first()
        if not case:
            results.append({"lead_reference": ref, "status": "not_found"})
            continue
        old_job = db.get(Job, case.job_id) if case.job_id else None
        raw_key = (old_job.s3_raw_key if old_job else None) or case.s3_raw_key
        if not raw_key:
            results.append({"lead_reference": ref, "status": "no_raw_report"})
            continue

        # Target firm: the requested one, else keep the case's existing branding
        # (re-score in place) rather than defaulting everything to first_legal.
        target_firm = firm or (case.destination_brand_id
                               or (old_job.firm if old_job else None) or "first_legal")

        # New job under the target firm, in the same batch as before so counts stay
        # coherent; the full pipeline re-runs from the retained raw report.
        new_job = Job(
            batch_id=(old_job.batch_id if old_job else None),
            s3_raw_key=raw_key,
            status="PENDING",
            firm=target_firm,
        )
        db.add(new_job)
        db.flush()

        # Re-point the case at the new job and re-arm the outcome postback.
        case.job_id = new_job.id
        case.destination_brand_id = target_firm
        case.outcome = None
        case.outcome_sent = False
        case.outcome_sent_at = None
        case.outcome_attempts = 0
        case.status = "QUEUED"
        case.last_error = None
        db.flush()

        queued.append(new_job.id)
        results.append({"lead_reference": ref, "status": "reprocessing",
                        "job_id": new_job.id, "firm": target_firm})

    db.commit()

    # Enqueue only after commit so the worker always finds the job.
    for jid in queued:
        fetch_and_process.apply_async(args=[jid], queue="fetch")

    return {
        "firm": firm or "(in place)",
        "requested": len(refs),
        "reprocessing": len(queued),
        "results": results,
    }


@router.get("/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    job = db.get(Job, case.job_id) if case.job_id else None
    data = _serialise_case(case, job)
    if job:
        data["lenders"] = [
            {
                "lender_name": lr.lender_name,
                "traffic_light": lr.traffic_light,
                "claim_score": lr.claim_score,
                "risk_flags": lr.risk_flags,
                "evidence_summary": lr.evidence_summary,
                "loc_generated": lr.loc_generated,
            }
            for lr in db.query(LenderResult).filter(LenderResult.job_id == job.id).all()
        ]
        data["documents"] = _case_documents(case, job, db)
    data["cfa"] = case.cfa
    return data
