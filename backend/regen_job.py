#!/usr/bin/env python3
"""
Direct regeneration of assessment PDF + LOCs for a given job.
Bypasses Celery — uses current code directly.
Usage: python regen_job.py <job_id>
"""
import sys
import os

# Ensure backend app is importable
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("ENVIRONMENT", "development")

from datetime import datetime
from app.core.database import SessionLocal
from app.core.storage import upload_bytes
from app.core.config import settings
from app.models.tables import Job, LenderResult
from app.documents.assessment_pdf import generate_assessment_pdf
from app.documents.loc_docx import generate_loc_docx

job_id = int(sys.argv[1]) if len(sys.argv) > 1 else 8

db = SessionLocal()
try:
    job = db.get(Job, job_id)
    if not job:
        print(f"Job {job_id} not found")
        sys.exit(1)

    schema       = job.normalised_data or {}
    client       = schema.get("client", {})
    client_name  = (client.get("name") or "Unknown").replace(" ", "_")
    matter_ref   = client.get("matter_ref") or f"AUTO-{job.id}"

    lender_results = db.query(LenderResult).filter(LenderResult.job_id == job.id).all()
    print(f"Job {job_id}  |  {client.get('name')}  |  {len(lender_results)} lender results")

    # ── Assessment PDF ────────────────────────────────────────────────────
    print("Generating assessment PDF…")
    pdf_bytes = generate_assessment_pdf(schema, lender_results)
    assessment_key = f"outputs/{matter_ref}/{matter_ref}__{client_name}__Assessment.pdf"
    upload_bytes(settings.S3_BUCKET_OUTPUTS, assessment_key, pdf_bytes, "application/pdf")
    job.s3_assessment_key = assessment_key
    print(f"  ✓  {assessment_key}  ({len(pdf_bytes):,} bytes)")

    # ── LOCs ──────────────────────────────────────────────────────────────
    for result in lender_results:
        if result.traffic_light in ("GREEN", "AMBER"):
            lender_safe = result.lender_name.replace(" ", "_").replace("/", "-")
            print(f"Generating LOC for {result.lender_name}…")
            loc_bytes = generate_loc_docx(schema, result)
            loc_key = f"outputs/{matter_ref}/{matter_ref}__{client_name}__{lender_safe}__LOC.docx"
            upload_bytes(
                settings.S3_BUCKET_OUTPUTS, loc_key, loc_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            result.s3_loc_key   = loc_key
            result.loc_generated = True
            print(f"  ✓  {loc_key}  ({len(loc_bytes):,} bytes)")

    job.status       = "COMPLETE"
    job.completed_at = datetime.utcnow()
    db.commit()
    print(f"\nDone — job {job_id} marked COMPLETE.")

finally:
    db.close()
