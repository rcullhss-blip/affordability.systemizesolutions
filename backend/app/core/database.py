from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

import os
_is_worker = os.environ.get("CELERY_WORKER") == "1"

# Some managed Postgres providers (e.g. Render) hand out a `postgres://` URL,
# which SQLAlchemy 2.x no longer recognises — normalise to `postgresql://`.
_db_url = settings.DATABASE_URL
if _db_url.startswith("postgres://"):
    _db_url = "postgresql://" + _db_url[len("postgres://"):]

engine = create_engine(
    _db_url,
    pool_pre_ping=True,
    pool_size=3 if _is_worker else 10,
    max_overflow=5 if _is_worker else 20,
    # Workers run 25 gevent greenlets over 8 connections; under a burst (all
    # instances booting into a full queue) a greenlet can wait >30s for a
    # connection. Waiting is fine — failing the job with "QueuePool limit
    # reached" is not (3 jobs failed that way at the 6-instance scale-up).
    pool_timeout=120 if _is_worker else 30,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
