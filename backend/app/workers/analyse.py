import copy
import re
from celery import shared_task
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job, LenderResult, Batch
from app.models.enums import JobStatus, TrafficLight
from app.analysis.rules_engine import analyse_lender
from app.analysis.computed_at_lending import compute_at_lending, _parse_date as parse_date
from app.analysis.lender_classifier import classify_lender
from app.workers.document import generate_documents
from sqlalchemy.orm.attributes import flag_modified


# Flags that represent genuine affordability / conduct grounds — not the
# structural debt-stacking / repeat-borrowing that fires on almost every lender.
# Used to gate out-of-scope entities (e.g. insurance premium finance) so they
# only produce a claim when there's a real adverse signal.
_SUBSTANTIVE_FLAGS = {
    "REPEATED_MISSED_PAYMENTS", "MISSED_PAYMENT", "HIGH_UTILISATION",
    "ELEVATED_UTILISATION", "ACTIVE_ADVERSE_AT_LENDING", "PAYDAY_LOAN",
    "ACTIVE_CCJ", "MULTIPLE_CCJS", "PUBLIC_RECORD_INSOLVENCY", "DEFAULT_REGISTERED",
}


def _has_real_grounds(flags) -> bool:
    return any(isinstance(f, dict) and f.get("type") in _SUBSTANTIVE_FLAGS
               for f in (flags or []))


# Mobile networks whose names are too short to match safely by substring (bare
# 'EE' is a substring of 'speedycash'/'freemans', etc.). Matched EXACTLY against
# the cleaned lender name so they're excluded without false-positiving real lenders.
_MOBILE_NETWORKS = {
    "ee", "o2", "three", "3", "orange", "t-mobile", "t mobile", "tmobile",
    "ee mobile", "o2 mobile", "three uk", "h3g", "h3g uk", "hutchison 3g",
}


def _is_mobile_network(name: str) -> bool:
    core = re.sub(r'\b(ltd|limited|plc|uk|group|the)\b', '', (name or "").lower()).strip().strip('.,& ')
    return core in _MOBILE_NETWORKS


@celery_app.task(bind=True, max_retries=2, default_retry_delay=15)
def run_analysis(self, job_id: int):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return

        job.status = "ANALYSING"
        # Clear any stale lender results from a previous (possibly partial) run
        # so re-queued jobs don't accumulate duplicate rows.
        db.query(LenderResult).filter(LenderResult.job_id == job.id).delete()
        db.commit()

        schema = copy.deepcopy(job.normalised_data or {})
        accounts = schema.get("accounts", [])
        searches = schema.get("searches", [])
        defaults = schema.get("defaults", [])

        # Only analyse financial credit accounts — skip telecoms, utilities, bank accounts, mortgages
        FINANCIAL_TYPES = {
            "CREDIT_CARD", "PERSONAL_LOAN", "PAYDAY_LOAN", "HIRE_PURCHASE",
            "OVERDRAFT", "STORE_CARD", "MAIL_ORDER", "HOME_CREDIT", "OTHER",
        }
        # Telecom companies offering phone finance and debt purchasers are not subject
        # to FCA CONC affordability obligations in the same way as consumer credit lenders
        NON_FINANCIAL_PATTERNS = [
            "o2", "vodafone", "virgin media mobile", "hutchison 3g", "hutchison3g",
            "ee limited", "three mobile", "talk talk", "bt group",
            "pra group", "pra capital", "lowell", "cabot financial",
            "intrum", "arrow global", "hoist finance", "moorcroft",
            "link financial", "1st credit", "creditcorp",
            # Charge cards (pay-in-full, no revolving balance) — out of scope
            "american express", "amex",
        ]

        def _is_non_financial(name: str) -> bool:
            n = name.lower()
            # Mobile/telecom providers are out of scope (never a consumer-credit LOC),
            # even when the account slips through typed as OTHER. _is_mobile_network
            # catches bare short names (EE, O2, Three, Orange) that substring matching
            # misses or mis-classifies.
            if _is_mobile_network(name) or classify_lender(name) == "telecom":
                return True
            return any(pat in n for pat in NON_FINANCIAL_PATTERNS)

        lender_groups: dict[str, list] = {}
        for acc in accounts:
            if acc.get("account_type", "OTHER").upper() not in FINANCIAL_TYPES:
                continue
            lender = acc.get("lender", "Unknown")
            if _is_non_financial(lender):
                continue
            lender_groups.setdefault(lender, []).append(acc)

        overall_lights = []
        for lender_name, accs in lender_groups.items():
            # Compute financial snapshot at lending date
            lending_date = parse_date(accs[0].get("opened_date")) if accs else None
            cal = compute_at_lending(lending_date, accounts, searches, defaults, lender_name)

            # Attach snapshot to account data so document generator can access it
            for acc in accs:
                acc["computed_at_lending"] = cal

            result = analyse_lender(lender_name, accs, searches, defaults, schema)

            # Insurance premium finance is out of IRL scope UNLESS there are real
            # affordability grounds — a genuine adverse/conduct signal, not just
            # the structural debt-stacking / repeat-borrowing that fires on every
            # lender. Without real grounds it's forced RED (no LOC).
            if classify_lender(lender_name) == "premium_finance" and not _has_real_grounds(result["flags"]):
                result = {**result, "traffic_light": "RED"}

            lr = LenderResult(
                job_id=job.id,
                lender_name=lender_name,
                traffic_light=result["traffic_light"],
                claim_score=result["score"],
                risk_flags=result["flags"],
                evidence_summary=result["evidence"],
                loc_generated=False,
            )
            db.add(lr)
            overall_lights.append(result["traffic_light"])

        if "GREEN" in overall_lights:
            job.traffic_light = "GREEN"
        elif "AMBER" in overall_lights:
            job.traffic_light = "AMBER"
        else:
            job.traffic_light = "RED"

        # Deep-copied schema with CAL data — flag_modified ensures SQLAlchemy persists it
        job.normalised_data = schema
        flag_modified(job, "normalised_data")

        _update_batch_counts(db, job)
        db.commit()

        generate_documents.apply_async(args=[job_id], queue="document")

    except Exception as exc:
        from celery.exceptions import Retry
        if not isinstance(exc, Retry):
            job = db.get(Job, job_id)
            if job:
                job.status = "FAILED"
                job.error_message = f"Analysis failed: {exc}"
                db.commit()
        raise self.retry(exc=exc)
    finally:
        db.close()


def _update_batch_counts(db, job):
    pass  # Batch stats are recomputed in deliver.py after job.status = "COMPLETE"
