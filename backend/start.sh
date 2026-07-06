#!/bin/sh
# Single Railway entrypoint, role-selected by SERVICE_ROLE so the API and the
# Celery worker can share one railway.toml startCommand:
#   SERVICE_ROLE=worker  -> Celery worker (gevent)
#   SERVICE_ROLE=beat    -> Celery beat scheduler (MUST be a single replica)
#   anything else / unset -> API (default)
if [ "$SERVICE_ROLE" = "worker" ]; then
  exec ./start_worker.sh
elif [ "$SERVICE_ROLE" = "beat" ]; then
  exec ./start_beat.sh
else
  exec ./start_api.sh
fi
