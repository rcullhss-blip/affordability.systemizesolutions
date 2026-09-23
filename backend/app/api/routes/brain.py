"""
Read-only assessment feed for the IRL "brain" (outcome-learning) project.

Guarded by its own BRAIN_API_KEY (X-API-Key header) — deliberately NOT a partner
key: partner keys act as admin and can post/reprocess cases and read client
details, whereas this key can only read this one GET route. If BRAIN_API_KEY is
not configured the route is closed to everyone.

Returns what the engine decided and why, per completed case and lender. It never
returns client identity or contact data (name, DOB, address, email, phone),
account numbers, the raw report or document links. Cases are matched on our
case ID / client reference (the tracker's "Client Reference" column).
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.analysis.checkpoint_audit import audit_report
from app.analysis.computed_at_lending import _parse_date, compute_at_lending
from app.analysis.rules_engine import _compute_confidence
from app.core.config import settings
from app.core.database import get_db
from app.core.lender_blocklist import is_blocked
from app.models.tables import Batch, Case, Job, LenderResult

router = APIRouter()

_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_PUBLIC_RECORD_STATUSES = {"CCJ", "INSOLVENCY", "INSOLVENCY_SATISFIED"}


def _require_brain_key(api_key: Optional[str] = Security(_key_header)) -> None:
    if not settings.BRAIN_API_KEY or api_key != settings.BRAIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _iso(v) -> Optional[str]:
    return v.isoformat() if v else None


def _parse_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        ts, jid = cursor.rsplit("|", 1)
        return datetime.fromisoformat(ts), int(jid)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid cursor")


def _data_present(schema: dict) -> dict:
    accounts = schema.get("accounts") or []
    defaults = schema.get("defaults") or []
    return {
        "accounts": len(accounts),
        "accounts_with_credit_limit": sum(1 for a in accounts if (a.get("credit_limit") or 0) > 0),
        "accounts_with_payment_history": sum(1 for a in accounts if a.get("payment_history")),
        "accounts_with_opened_date": sum(1 for a in accounts if a.get("opened_date")),
        "searches": len(schema.get("searches") or []),
        "defaults": sum(1 for d in defaults if d.get("status") not in _PUBLIC_RECORD_STATUSES),
        "public_records": sum(1 for d in defaults if d.get("status") in _PUBLIC_RECORD_STATUSES)
                          + len(schema.get("public_records") or []),
    }


def _lender_accounts(schema: dict, lender_name: str) -> list[dict]:
    return [
        {
            "account_type":    a.get("account_type"),
            "status":          a.get("status"),
            "opened_date":     a.get("opened_date") or None,   # the lending date the rules used
            "closed_date":     a.get("closed_date") or a.get("settled_date") or None,
            "default_date":    a.get("default_date"),
            "balance":         a.get("balance"),
            "credit_limit":    a.get("credit_limit"),
            "utilisation_pct": a.get("utilisation_pct"),
            "monthly_payment": a.get("monthly_payment"),
            "payment_history": a.get("payment_history") or [],
            "payment_codes_raw": a.get("payment_codes_raw"),   # positional, month 0 = last_updated
            "last_updated":    a.get("last_updated"),
        }
        for a in (schema.get("accounts") or [])
        if a.get("lender") == lender_name
    ]


def _searches(schema: dict) -> list[dict]:
    return [
        {"date": s.get("date"), "lender": s.get("lender"), "search_type": s.get("search_type"),
         "search_subtype": s.get("search_subtype"), "application_type": s.get("application_type")}
        for s in (schema.get("searches") or []) if isinstance(s, dict)
    ]


def _defaults(schema: dict) -> list[dict]:
    """Defaults, CCJs and insolvencies exactly as the rules read them (status says which)."""
    return [
        {"lender": d.get("lender"), "status": d.get("status"), "date": d.get("date"),
         "amount": d.get("amount"), "record_type": d.get("record_type") or d.get("type")}
        for d in (schema.get("defaults") or []) if isinstance(d, dict)
    ]


def _data_status(schema: dict) -> str:
    """available: slim credit data present; unavailable: raw report could not be
    re-read; pending_backfill: purged before it was kept, refill still queued."""
    if schema.get("_backfill_error"):
        return "unavailable"
    return "available" if schema.get("accounts") is not None else "pending_backfill"


def _at_lending(schema: dict, lender_name: str) -> Optional[dict]:
    """The at-lending snapshot, recomputed from the stored accounts with the same
    lending-date rule as analyse.py (the lender's first in-scope account), so
    snapshot fixes apply to every case on read rather than only to new runs."""
    from app.workers.analyse import FINANCIAL_TYPES  # heavy worker import, as below

    accounts = schema.get("accounts") or []
    accs = [a for a in accounts if a.get("lender") == lender_name
            and (a.get("account_type") or "OTHER").upper() in FINANCIAL_TYPES]
    if not accs:
        return None
    return compute_at_lending(_parse_date(accs[0].get("opened_date")), accounts,
                              schema.get("searches") or [], schema.get("defaults") or [], lender_name)


@router.get("/lender-results", dependencies=[Depends(_require_brain_key)])
def lender_results(
    updated_since: Optional[datetime] = Query(None, description="ISO timestamp; only cases updated after this"),
    cursor: Optional[str] = Query(None, description="next_cursor from the previous page"),
    limit: int = Query(100, ge=1, le=250),
    db: Session = Depends(get_db),
):
    # Imported here: both modules pull in heavy document/worker dependencies.
    from app.documents.assessment_pdf import _confidence_from_flags
    from app.workers.document import _loc_preflight

    q = (
        select(Job, Case.lead_reference, Batch.partner_batch_id)
        .outerjoin(Case, Case.job_id == Job.id)
        .outerjoin(Batch, Batch.id == Job.batch_id)
        .where(Job.status == "COMPLETE")
    )
    if updated_since:
        q = q.where(Job.updated_at > updated_since)
    if cursor:
        c_ts, c_id = _parse_cursor(cursor)
        q = q.where(or_(Job.updated_at > c_ts, and_(Job.updated_at == c_ts, Job.id > c_id)))
    rows = db.execute(q.order_by(Job.updated_at.asc(), Job.id.asc()).limit(limit)).all()

    job_ids = [job.id for job, _, _ in rows]
    by_job: dict[int, list] = {}
    if job_ids:
        for lr in db.execute(
            select(LenderResult).where(LenderResult.job_id.in_(job_ids)).order_by(LenderResult.id)
        ).scalars():
            by_job.setdefault(lr.job_id, []).append(lr)

    cases = []
    for job, lead_ref, partner_batch_id in rows:
        schema = job.normalised_data or {}
        lrs = by_job.get(job.id, [])
        lenders = []
        for lr in lrs:
            flags = [f for f in (lr.risk_flags or []) if isinstance(f, dict)]
            pdf_grade, pdf_pct = _confidence_from_flags(flags)
            lenders.append({
                "lender_name":        lr.lender_name,            # as printed on the report
                "traffic_light":      lr.traffic_light,
                "score":              lr.claim_score,            # capped at 100
                "score_uncapped":     None,                      # not recorded yet
                "flags":              [{"type": f.get("type"), "severity": f.get("severity"),
                                        "description": f.get("description"),
                                        "points": None}          # per-flag points not recorded yet
                                       for f in flags],
                "confidence_engine":  _compute_confidence(flags),
                "confidence_pdf":     {"score": pdf_pct, "grade": pdf_grade},
                "loc_generated":      lr.loc_generated,
                "blocked_lender":     is_blocked(lr.lender_name),
                "preflight_warnings": _loc_preflight(schema, lr) if lr.loc_generated else [],
                "at_lending":         _at_lending(schema, lr.lender_name),
                "accounts":           _lender_accounts(schema, lr.lender_name),
            })
        data_status = _data_status(schema)
        # Only audit real data — auditing a purged report reports a false PARSE_EMPTY.
        findings = (audit_report(schema, [{"traffic_light": lr.traffic_light,
                                           "lender_name": lr.lender_name} for lr in lrs])
                    if data_status == "available" else None)
        cases.append({
            "case_id":             job.id,
            "client_reference":    lead_ref,                 # tracker "Client Reference" (blank for older batch uploads)
            "firm":                job.firm,
            "batch_id":            job.batch_id,
            "partner_batch_id":    partner_batch_id,
            "engine_version":      None,                     # not recorded yet
            "assessed_at":         _iso(job.completed_at),
            "updated_at":          _iso(job.updated_at),
            "traffic_light":       job.traffic_light,
            "data_status":         data_status,
            "data_source":         schema.get("_source"),
            "data_present":        _data_present(schema),
            "qa": {
                "audit_findings":      findings,
                "spot_check_required": job.spot_check_required,
                "spot_check_reviewed": job.spot_check_reviewed,
            },
            "searches":            _searches(schema),
            "defaults":            _defaults(schema),
            "lenders":             lenders,
        })

    next_cursor = None
    if len(rows) == limit:
        last = rows[-1][0]
        next_cursor = f"{last.updated_at.isoformat()}|{last.id}"
    return {"cases": cases, "count": len(cases), "next_cursor": next_cursor}
