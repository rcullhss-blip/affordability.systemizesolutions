from celery import shared_task
from sqlalchemy.exc import IntegrityError
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.tables import Job, Client, Account
from app.models.enums import JobStatus
from app.parsers.normaliser import normalise_to_schema
from app.workers.analyse import run_analysis
from app.analysis.computed_at_lending import _parse_date


@celery_app.task(bind=True, max_retries=2, default_retry_delay=15)
def parse_content(self, job_id: int):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return

        job.status = "PARSING"
        db.commit()

        raw_text = (job.normalised_data or {}).get("_raw_text", "")
        schema = normalise_to_schema(raw_text)

        client_data = schema.get("client", {})
        matter_ref = client_data.get("matter_ref") or f"AUTO-{job.id}"

        client = db.query(Client).filter(Client.matter_ref == matter_ref).first()
        if not client:
            dob_raw = client_data.get("dob")
            dob_date = _parse_date(dob_raw) if dob_raw else None
            try:
                client = Client(
                    name=client_data.get("name", "Unknown"),
                    dob=dob_date,
                    address=client_data.get("address"),
                    matter_ref=matter_ref,
                )
                db.add(client)
                db.flush()
            except IntegrityError:
                # Another worker created this client concurrently (same matter_ref)
                db.rollback()
                client = db.query(Client).filter(Client.matter_ref == matter_ref).first()

        for acc in schema.get("accounts", []):
            account = Account(
                client_id=client.id,
                lender_name=acc.get("lender", "Unknown"),
                account_type=acc.get("account_type"),
                opened_date=_parse_date(acc.get("opened_date")),
                balance=acc.get("balance"),
                credit_limit=acc.get("credit_limit"),
                utilisation_pct=acc.get("utilisation_pct"),
                status=acc.get("status"),
                payment_history=acc.get("payment_history", []),
            )
            db.add(account)

        job.client_id = client.id
        job.normalised_data = schema
        db.commit()

        run_analysis.apply_async(args=[job_id], queue="analyse")

    except Exception as exc:
        from celery.exceptions import Retry
        if not isinstance(exc, Retry):
            job = db.get(Job, job_id)
            if job:
                job.status = "FAILED"
                job.error_message = f"Parsing failed: {exc}"
                db.commit()
        raise self.retry(exc=exc)
    finally:
        db.close()
