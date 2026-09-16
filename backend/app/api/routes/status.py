"""
Ops status — aggregate health counters for an external monitor.

Deliberately separate from /analytics and /cases: it is guarded by its own
MONITOR_API_KEY and returns COUNTS AND TIMESTAMPS ONLY, never client data, so
the key can live in a monitoring job without exposing credit reports. If no
MONITOR_API_KEY is configured the route is closed to everyone.

The health itself is computed in app.core.health, shared with the Slack alert
task, so the endpoint and the alerts can never disagree.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.health import compute_health

router = APIRouter()

_key_header = APIKeyHeader(name="X-Monitor-Key", auto_error=False)


def _require_monitor_key(api_key: Optional[str] = Security(_key_header)) -> None:
    if not settings.MONITOR_API_KEY or api_key != settings.MONITOR_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid monitor key")


@router.get("", dependencies=[Depends(_require_monitor_key)])
def ops_status(db: Session = Depends(get_db)):
    return compute_health(db)
