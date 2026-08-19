import csv
import io
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.config import settings
from app.core.s3 import generate_presigned_url
from app.core.lender_blocklist import is_blocked
from pydantic import BaseModel
from app.models.tables import Batch, Job, Client, LenderResult, Case
from app.models.enums import JobStatus
from app.api.routes.webhook import _require_irl_key
from app.workers.fetch import fetch_and_process
from app.documents.tracker_csv import (
    TL_LABELS, split_name, split_address, case_key_for, tracker_header_for, format_dob,
)

# Job statuses that mean the job will not change again. A batch is "ready" to
# export once none of its jobs are in a non-terminal (still-processing) state.
_TERMINAL_JOB_STATUSES = (JobStatus.COMPLETE.value, JobStatus.FAILED.value)


def _batch_is_ready(db: Session, batch: Batch) -> bool:
    """True once the whole partner batch has finished processing — i.e. at least
    one job exists and no job is still in a non-terminal (in-flight) state.

    Note: `total_reports` is a running count that increments as each case is
    ingested, so this gate only means "everything ingested so far has finished".
    Partners must therefore poll only AFTER they have finished dispatching the
    whole batch — a pull mid-dispatch could momentarily look ready."""
    total_created = db.execute(
        select(func.count(Job.id)).where(Job.batch_id == batch.id)
    ).scalar_one()
    if total_created == 0 or total_created < (batch.total_reports or 0):
        return False
    in_flight = db.execute(
        select(func.count(Job.id)).where(
            Job.batch_id == batch.id,
            Job.status.notin_(_TERMINAL_JOB_STATUSES),
        )
    ).scalar_one()
    return in_flight == 0

_FALLBACK_BASE = "http://localhost:8000"

# Tracker column layout + name/address/traffic-light helpers now live in
# app.documents.tracker_csv (shared with the per-case outcome postback) so both
# tracker producers emit an identical Proclaim-ready format.


def _case_status(loc_generated: bool, traffic_light: str | None) -> str:
    if loc_generated:
        return "LOC Generated"
    tl = (traffic_light or "").upper()
    if tl in ("GREEN", "AMBER"):
        return "Referred for Legal Review"
    if tl == "RED":
        return "No Viable Claim"
    return "Pending"

router = APIRouter()


def _serialise_job(job):
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "status": job.status,
        "traffic_light": job.traffic_light,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "s3_assessment_key": job.s3_assessment_key,
        "client": {
            "id": job.client.id,
            "name": job.client.name,
            "matter_ref": job.client.matter_ref,
            "dob": str(job.client.dob) if job.client.dob else None,
        } if job.client else None,
        "lender_results": [
            {
                "id": r.id,
                "lender_name": r.lender_name,
                "traffic_light": r.traffic_light,
                "claim_score": r.claim_score,
                "loc_generated": r.loc_generated,
                "s3_loc_key": r.s3_loc_key,
                "no_longer_trading": is_blocked(r.lender_name),
            }
            for r in job.lender_results
        ],
    }


@router.get("/")
def list_batches(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    batches = db.execute(select(Batch).order_by(Batch.created_at.desc()).offset(skip).limit(limit)).scalars().all()
    return batches


@router.get("/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.get("/{batch_id}/jobs")
def get_batch_jobs(batch_id: int, db: Session = Depends(get_db)):
    jobs = db.execute(
        select(Job)
        .where(Job.batch_id == batch_id)
        .options(selectinload(Job.client), selectinload(Job.lender_results))
        .order_by(Job.created_at.asc())
    ).scalars().all()
    return [_serialise_job(j) for j in jobs]


@router.get("/{batch_id}/progress")
def batch_progress(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    jobs = db.execute(select(Job).where(Job.batch_id == batch_id)).scalars().all()
    status_counts = {}
    for job in jobs:
        status_counts[job.status] = status_counts.get(job.status, 0) + 1

    complete = status_counts.get("COMPLETE", 0)
    failed = status_counts.get("FAILED", 0)
    pct = round((complete + failed) / max(batch.total_reports, 1) * 100, 1)

    return {
        "batch_id": batch_id,
        "total": batch.total_reports,
        "complete": complete,
        "failed": failed,
        "in_progress": len(jobs) - complete - failed,
        "percent_done": pct,
        "green": batch.green_count,
        "amber": batch.amber_count,
        "red": batch.red_count,
        "assessments": batch.assessments_generated,
        "locs": batch.locs_generated,
    }


def _file_url(bucket: str, key: str | None, base_url: str = _FALLBACK_BASE) -> str:
    if not key:
        return ""
    if settings.use_local_storage:
        return f"{base_url}/api/v1/files/{bucket}/{key}"
    try:
        return generate_presigned_url(bucket, key, expires_in=604800)  # 7 days (AWS SigV4 max)
    except Exception:
        return ""


@router.get("/{batch_id}/export/tracker")
def export_tracker_csv(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Proclaim-ready tracker CSV — one row per LOC. Streamed, and pulls only the
    fields it needs (not the full report JSON) so it scales to large batches."""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Extract only the client sub-fields we need, server-side — never load the
    # full normalised_data blob into memory (that was the slowness).
    def ndp(*keys):
        return func.jsonb_extract_path_text(Job.normalised_data, *keys)
    job_rows = db.execute(
        select(
            Job.id, Job.created_at, Job.s3_raw_key, Job.s3_assessment_key,
            Job.s3_credit_report_key,
            Client.name, Client.dob, Client.address,
            ndp("client", "email"), ndp("client", "phone"),
            ndp("client", "name"), ndp("client", "dob"), ndp("client", "address"),
            Case.lead_reference,
        )
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(Case, Case.job_id == Job.id)
        .where(Job.batch_id == batch_id, Job.status == "COMPLETE")
        .order_by(Job.created_at.asc())
    ).all()

    # Lender results grouped by job (single query, no per-job round-trips)
    lrs: dict[int, list] = {}
    for jid, lender, tl, loc_gen, loc_key in db.execute(
        select(LenderResult.job_id, LenderResult.lender_name, LenderResult.traffic_light,
               LenderResult.loc_generated, LenderResult.s3_loc_key)
        .join(Job, Job.id == LenderResult.job_id)
        .where(Job.batch_id == batch_id, Job.status == "COMPLETE")
    ).all():
        lrs.setdefault(jid, []).append((lender, tl, loc_gen, loc_key))

    base_url = str(request.base_url).rstrip("/")
    RAW, OUTB = settings.S3_BUCKET_RAW, settings.S3_BUCKET_OUTPUTS

    def _line(vals):
        buf = io.StringIO()
        csv.writer(buf).writerow(vals)
        return buf.getvalue()

    # Ryans' middleware reads a leading "Case Key" column as the case-type code
    # ("IL"); other firms get no Case Key column and the original layout. The
    # Client Reference column carries our lead reference for every firm.
    case_key = case_key_for(batch.firm)

    def _row(cells):
        return _line([case_key, *cells] if case_key else cells)

    def stream():
        yield _line(tracker_header_for(batch.firm))
        for (jid, created, raw_key, assess_key, credit_key, c_name, c_dob, c_addr,
             email, phone, nd_name, nd_dob, nd_addr, lead_ref) in job_rows:
            ts = created.strftime("%d/%m/%Y %H:%M") if created else ""
            title, first_name, surname = split_name((c_name or "") or (nd_name or ""))
            dob = (str(c_dob) if c_dob else "") or (nd_dob or "")
            dob = format_dob(dob, batch.firm)  # DD/MM/YYYY for firms that need it (Ryans)
            res1, res2, res3, postcode = split_address((c_addr or "") or (nd_addr or ""))
            # Prefer the generated credit-report PDF (outputs bucket); fall back to
            # the raw report JSON for older jobs that predate PDF generation.
            report_url     = (_file_url(OUTB, credit_key, base_url) if credit_key
                              else _file_url(RAW, raw_key, base_url))
            assessment_url = _file_url(OUTB, assess_key, base_url)
            ref = lead_ref or ""
            these = lrs.get(jid, [])
            locs = [(l, tl, k) for (l, tl, g, k) in these if g and k]
            if locs:
                for lender, tl, k in locs:
                    yield _row([
                        ref,
                        ts, title, first_name, surname, dob, email or "", phone or "",
                        res1, res2, res3, postcode,
                        lender, TL_LABELS.get((tl or "").upper(), ""), "LOC Generated",
                        report_url, assessment_url, _file_url(OUTB, k, base_url),
                    ])
            else:
                all_blocked = bool(these) and all(is_blocked(l) for (l, _, _, _) in these)
                case_status = "No Viable Defendant" if all_blocked else "No Viable Claim"
                yield _row([
                    ref,
                    ts, title, first_name, surname, dob, email or "", phone or "",
                    res1, res2, res3, postcode, "", "", case_status,
                    report_url, assessment_url, "",
                ])

    firm_slug = (batch.firm or "first_legal")
    batch_slug = re.sub(r'[^a-z0-9]+', '_', (batch.name or str(batch_id)).lower()).strip('_')
    filename = f"{batch_slug}_{firm_slug}_affordability_tracker.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/by-partner/{partner_batch_id}/export/tracker")
def export_tracker_by_partner(
    partner_batch_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _auth=Depends(_require_irl_key),
):
    """Tracker CSV for a partner bulk run (e.g. Woodville), looked up by the
    partner's OWN batch_id — so they can pull our tracker without knowing our
    internal batch id.

    Auth: same `X-API-Key` (IRL_CASE_API_KEY / sk_irlcase_*) used on /irl-case.

    Readiness contract:
      * unknown partner batch id        -> 404
      * batch found but still processing -> 200 with an EMPTY body (poll again)
      * batch finished                   -> 200 text/csv tracker
    Partners treat an empty 200 body as "still processing, retry later"."""
    batch = db.query(Batch).filter(Batch.partner_batch_id == partner_batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="No batch found for that partner batch id")
    if not _batch_is_ready(db, batch):
        # Still processing — empty body signals "not ready, retry later".
        return Response(status_code=200, media_type="text/csv", content=b"")
    return export_tracker_csv(batch.id, request, db)


class ReprocessAsFirm(BaseModel):
    # Identify the source batch by our internal id OR the partner's batch id.
    source_batch_id: int | None = None
    source_partner_batch_id: str | None = None
    firm: str = "first_legal"                 # target letterhead, e.g. "ryans"
    new_batch_name: str | None = None
    new_partner_batch_id: str | None = None   # so the result is pullable via by-partner tracker


@router.post("/reprocess-as-firm", dependencies=[Depends(_require_irl_key)])
def reprocess_as_firm(body: ReprocessAsFirm, db: Session = Depends(get_db)):
    """Re-run an existing batch's reports under a DIFFERENT solicitor firm, as a
    fresh batch. Clones each source job's `s3_raw_key` (the retained raw report)
    into new PENDING jobs tagged with the target firm and re-enqueues the full
    pipeline — so LOCs regenerate with the new letterhead. The source batch is
    left untouched. `normalised_data` having been purged post-delivery is fine:
    fetch_and_process re-fetches from the raw S3 object."""
    if body.source_batch_id:
        src = db.get(Batch, body.source_batch_id)
    elif body.source_partner_batch_id:
        src = db.query(Batch).filter(Batch.partner_batch_id == body.source_partner_batch_id).first()
    else:
        raise HTTPException(status_code=400, detail="source_batch_id or source_partner_batch_id required")
    if not src:
        raise HTTPException(status_code=404, detail="source batch not found")

    raw_keys = db.execute(
        select(Job.s3_raw_key)
        .where(Job.batch_id == src.id, Job.s3_raw_key.isnot(None))
        .order_by(Job.created_at.asc())
    ).scalars().all()
    if not raw_keys:
        raise HTTPException(status_code=404, detail="source batch has no retained raw reports to reprocess")

    new_batch = Batch(
        name=body.new_batch_name or f"{src.name} — {body.firm} rerun",
        firm=body.firm,
        partner_batch_id=body.new_partner_batch_id,
        total_reports=len(raw_keys),
    )
    db.add(new_batch)
    db.commit()
    db.refresh(new_batch)

    job_ids: list[int] = []
    for raw_key in raw_keys:
        j = Job(batch_id=new_batch.id, s3_raw_key=raw_key, status="PENDING", firm=body.firm)
        db.add(j)
        db.flush()
        job_ids.append(j.id)
    db.commit()

    for jid in job_ids:
        fetch_and_process.apply_async(args=[jid], queue="fetch")

    return {
        "new_batch_id": new_batch.id,
        "new_partner_batch_id": new_batch.partner_batch_id,
        "firm": body.firm,
        "reports": len(job_ids),
        "status": "processing",
    }
