#!/bin/sh
# Railway beat service start script — the single Celery Beat scheduler.
# MUST run as exactly ONE replica: multiple beats = duplicate scheduled tasks.
# It only SCHEDULES (watchdog every 5m, retention daily); the workers (which
# consume the `watchdog` queue) actually execute them.
exec celery -A app.core.celery_app beat --loglevel=info
