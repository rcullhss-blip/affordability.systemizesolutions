from celery import Celery
from celery.schedules import crontab
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
        "app.workers.autoscale",
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
        "app.workers.autoscale.*": {"queue": "watchdog"},
    },
    beat_schedule={
        "autoscale-every-2-minutes": {
            "task": "app.workers.autoscale.autoscale_workers",
            "schedule": 120.0,  # up fast after an upload; down after 5 idle ticks (~10 min)
        },
        "watchdog-every-5-minutes": {
            "task": "app.workers.watchdog.rescue_stuck_jobs",
            "schedule": 300.0,  # every 5 minutes
        },
        "retention-purge-daily": {
            "task": "app.workers.retention.purge_old_batches",
            # Fixed time of day, NOT an 86400s interval: beat's interval timer restarts
            # with the service, and this project deploys more often than daily, so the
            # interval form never elapsed and nothing was ever purged (found 16 Sep 2026,
            # with 10 Aug batches still in the DB).
            "schedule": crontab(hour=3, minute=0),
        },
        "post-case-outcomes-every-minute": {
            "task": "app.workers.irl_outcome.post_case_outcomes",
            "schedule": 60.0,  # sweep completed cases and post outcomes back
        },
    },
)
