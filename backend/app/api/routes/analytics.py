from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.tables import LenderResult, Job

router = APIRouter()


@router.get("/lenders")
def lender_analytics(limit: int = 20, db: Session = Depends(get_db)):
    """Top lenders by volume, claim rate, and average score."""
    rows = db.execute(
        select(
            LenderResult.lender_name,
            func.count(LenderResult.id).label("total"),
            func.count(LenderResult.id).filter(LenderResult.traffic_light == "GREEN").label("green_count"),
            func.count(LenderResult.id).filter(LenderResult.traffic_light == "AMBER").label("amber_count"),
            func.count(LenderResult.id).filter(LenderResult.traffic_light == "RED").label("red_count"),
            func.avg(LenderResult.claim_score).label("avg_score"),
        )
        .group_by(LenderResult.lender_name)
        .order_by(func.count(LenderResult.id).desc())
        .limit(limit)
    ).all()

    return [
        {
            "lender": r.lender_name,
            "total_accounts": r.total,
            "green": r.green_count or 0,
            "amber": r.amber_count or 0,
            "red": r.red_count or 0,
            "claim_rate_pct": round((r.green_count or 0) / max(r.total, 1) * 100, 1),
            "avg_claim_score": round(r.avg_score or 0, 2),
        }
        for r in rows
    ]


@router.get("/summary")
def platform_summary(db: Session = Depends(get_db)):
    total_jobs = db.execute(select(func.count(Job.id))).scalar()
    green = db.execute(select(func.count(Job.id)).where(Job.traffic_light == "GREEN")).scalar()
    amber = db.execute(select(func.count(Job.id)).where(Job.traffic_light == "AMBER")).scalar()
    red = db.execute(select(func.count(Job.id)).where(Job.traffic_light == "RED")).scalar()
    locs = db.execute(select(func.count(LenderResult.id)).where(LenderResult.loc_generated == True)).scalar()

    return {
        "total_assessments": total_jobs,
        "green": green,
        "amber": amber,
        "red": red,
        "locs_generated": locs,
    }
