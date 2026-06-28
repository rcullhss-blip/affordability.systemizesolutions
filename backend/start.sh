#!/bin/sh
# Single entrypoint for Railway. The same image runs either the API or the
# Celery worker depending on SERVICE_ROLE, so both services share one config
# (railway.toml) and are differentiated only by an env var.
#   SERVICE_ROLE=worker  -> Celery worker (gevent)
#   anything else / unset -> API (default)
if [ "$SERVICE_ROLE" = "worker" ]; then
  exec ./start_worker.sh
else
  exec ./start_api.sh
fi
