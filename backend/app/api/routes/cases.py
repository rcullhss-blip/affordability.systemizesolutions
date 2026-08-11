"""
Cases API — IRL cases received from the PCP platform.

Powers the admin "Cases" tab (mirrors Batches): list, detail, and a summary
count. Case status is the intake/postback state; `job_status` is the live
assessment-pipeline state of the linked Job.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tables import Case, Job, LenderResult

router = APIRouter()


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
    return data
