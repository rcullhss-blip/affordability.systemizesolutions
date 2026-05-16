from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from app.core.database import get_db
from app.models.tables import Client, Job

router = APIRouter()


@router.get("/")
def list_clients(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    clients = db.execute(select(Client).order_by(Client.name).offset(skip).limit(limit)).scalars().all()
    return clients


@router.get("/{matter_ref}")
def get_client_by_matter_ref(matter_ref: str, db: Session = Depends(get_db)):
    client = db.execute(select(Client).where(Client.matter_ref == matter_ref)).scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/{matter_ref}/jobs")
def get_client_jobs(matter_ref: str, db: Session = Depends(get_db)):
    client = db.execute(select(Client).where(Client.matter_ref == matter_ref)).scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    jobs = db.execute(
        select(Job)
        .where(Job.client_id == client.id)
        .options(selectinload(Job.lender_results))
        .order_by(Job.created_at.desc())
    ).scalars().all()
    return {
        "client": {
            "id": client.id,
            "name": client.name,
            "matter_ref": client.matter_ref,
            "dob": str(client.dob) if client.dob else None,
            "address": client.address,
            "created_at": client.created_at.isoformat() if client.created_at else None,
        },
        "jobs": [
            {
                "id": j.id,
                "batch_id": j.batch_id,
                "status": j.status,
                "traffic_light": j.traffic_light,
                "error_message": j.error_message,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "s3_assessment_key": j.s3_assessment_key,
                "lender_results": [
                    {
                        "id": r.id,
                        "lender_name": r.lender_name,
                        "traffic_light": r.traffic_light,
                        "claim_score": r.claim_score,
                        "loc_generated": r.loc_generated,
                    }
                    for r in j.lender_results
                ],
            }
            for j in jobs
        ],
    }
