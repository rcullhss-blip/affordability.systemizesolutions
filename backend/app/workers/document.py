import re
import logging
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.storage import upload_bytes
from app.core.config import settings
from app.core.lender_blocklist import is_blocked
from app.analysis.lender_classifier import is_possible_intermediary
from app.models.tables import Job, LenderResult, Batch
from app.models.enums import JobStatus, TrafficLight
from app.documents.assessment_pdf import generate_assessment_pdf
from app.documents.loc_docx import generate_loc_docx
from app.workers.deliver import deliver_outputs

log = logging.getLogger(__name__)


def _has_flag(result, flag_type: str) -> bool:
    for f in (result.risk_flags or []):
        if isinstance(f, dict) and f.get("type") == flag_type:
            return True
    return False


def _find_agreement_date(schema: dict, lender_name: str) -> str | None:
    """Return the open/agreement date for the lender's account, or None if missing."""
    accounts = schema.get("accounts", [])
    name_lower = lender_name.lower()
    words = [w for w in re.split(r'\W+', name_lower) if len(w) > 3]

    for acc in accounts:
        acc_lender = (acc.get("lender") or "").lower()
        if acc_lender == name_lower:
            return acc.get("opened_date") or acc.get("open_date") or acc.get("agreement_date")
        if name_lower in acc_lender or acc_lender in name_lower:
            return acc.get("opened_date") or acc.get("open_date") or acc.get("agreement_date")

    for acc in accounts:
        acc_lender = (acc.get("lender") or "").lower()
        if words and all(w in acc_lender for w in words):
            return acc.get("opened_date") or acc.get("open_date") or acc.get("agreement_date")

    return None


def _loc_preflight(schema: dict, result) -> list[str]:
    """
    Returns a list of solicitor-review warnings.
    An empty list means no issues. LOC is always generated; warnings appear inside the document.
    """
    warnings = []
    lender = result.lender_name

    if is_possible_intermediary(lender):
        warnings.append(
            f"{lender} may be a credit broker rather than the regulated creditor — "
            f"verify the originating lender before sending this LOC"
        )

    if _has_flag(result, "POSSIBLE_DEBT_PURCHASER"):
        warnings.append(
            f"{lender} may not be the originating lender (account defaulted close to opening date, "
            f"suggesting purchased or reassigned debt) — verify entity before sending"
        )

    if not _find_agreement_date(schema, lender):
        warnings.append(
            f"No exact agreement date found for {lender} in the credit file — "
            f"a general date has been used; confirm the exact date before sending"
        )

    return warnings


@celery_app.task(bind=True, max_retries=2, default_retry_delay=15)
def generate_documents(self, job_id: int):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return

        job.status = "GENERATING"
        db.commit()

        schema = job.normalised_data or {}
        # Merge DB client record into schema so PDF/LOC have the real name, DOB,
        # address and matter_ref — normalised_data.client can be empty for CSV jobs.
        if job.client:
            db_client = job.client
            schema_client = schema.setdefault("client", {})
            if not schema_client.get("name"):
                schema_client["name"] = db_client.name or ""
            if not schema_client.get("dob"):
                schema_client["dob"] = str(db_client.dob) if db_client.dob else ""
            if not schema_client.get("address"):
                schema_client["address"] = db_client.address or ""
            if not schema_client.get("matter_ref"):
                schema_client["matter_ref"] = db_client.matter_ref or ""

        client = schema.get("client", {})
        raw_name = client.get("name") or "Unknown"
        client_slug = re.sub(r'[^a-z0-9]+', '_', raw_name.lower()).strip('_')
        matter_ref = client.get("matter_ref") or f"AUTO-{job.id}"

        lender_results = db.query(LenderResult).filter(LenderResult.job_id == job.id).all()

        # Generate PDF assessment
        pdf_bytes = generate_assessment_pdf(schema, lender_results)
        assessment_key = f"outputs/{matter_ref}/{client_slug}_affordability_assessment.pdf"
        upload_bytes(settings.S3_BUCKET_OUTPUTS, assessment_key, pdf_bytes, "application/pdf")
        job.s3_assessment_key = assessment_key

        loc_count = 0
        viable_results = [r for r in lender_results if r.traffic_light in ("GREEN", "AMBER") and not is_blocked(r.lender_name)]
        for result in viable_results:
            warnings = _loc_preflight(schema, result)
            if warnings:
                log.warning("LOC review warnings for %s: %s", result.lender_name, "; ".join(warnings))
            lender_slug = re.sub(r'[^a-z0-9]+', '_', result.lender_name.lower()).strip('_')
            loc_bytes = generate_loc_docx(schema, result, review_warnings=warnings or None)
            loc_key = f"outputs/{matter_ref}/{client_slug}_loc_{lender_slug}.docx"
            upload_bytes(settings.S3_BUCKET_OUTPUTS, loc_key, loc_bytes,
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            result.s3_loc_key = loc_key
            result.loc_generated = True
            loc_count += 1

        # If no viable defendants (all blocked or all RED), downgrade job to RED
        if loc_count == 0 and job.traffic_light in ("GREEN", "AMBER"):
            job.traffic_light = "RED"

        # Batch counter recompute is done in deliver.py after job.status = "COMPLETE"

        db.commit()

        deliver_outputs.apply_async(args=[job_id], queue="deliver")

    except Exception as exc:
        from celery.exceptions import Retry
        if not isinstance(exc, Retry):
            job = db.get(Job, job_id)
            if job:
                job.status = "FAILED"
                job.error_message = f"Document generation failed: {exc}"
                db.commit()
        raise self.retry(exc=exc)
    finally:
        db.close()
