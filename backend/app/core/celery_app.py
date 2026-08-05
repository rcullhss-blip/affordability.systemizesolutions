from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "systemize",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.fetch",
        "app.workers.intake",
        "app.workers.extract",
        "app.workers.parse",
        "app.workers.analyse",
        "app.workers.document",
        "app.workers.deliver",
        "app.workers.watchdog",
        "app.workers.retention",
        "app.workers.irl_outcome",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/London",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.fetch.*":   {"queue": "fetch"},
        "app.workers.intake.*":  {"queue": "fetch"},
        "app.workers.extract.*": {"queue": "extract"},
        "app.workers.parse.*": {"queue": "parse"},
        "app.workers.analyse.*": {"queue": "analyse"},
        "app.workers.document.*": {"queue": "document"},
        "app.workers.deliver.*": {"queue": "deliver"},
        "app.workers.watchdog.*": {"queue": "watchdog"},
        "app.workers.retention.*": {"queue": "watchdog"},
        "app.workers.irl_outcome.*": {"queue": "deliver"},
    },
    beat_schedule={
        "watchdog-every-5-minutes": {
            "task": "app.workers.watchdog.rescue_stuck_jobs",
            "schedule": 300.0,  # every 5 minutes
        },
        "retention-purge-daily": {
            "task": "app.workers.retention.purge_old_batches",
            "schedule": 86400.0,  # once a day
        },
        "post-case-outcomes-every-minute": {
            "task": "app.workers.irl_outcome.post_case_outcomes",
            "schedule": 60.0,  # sweep completed cases and post outcomes back
        },
    },
)
