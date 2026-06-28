#!/bin/sh
# Entrypoint for Railway, role-selected by SERVICE_ROLE:
#   worker            -> Celery worker only (used when shared S3 storage is set up)
#   api               -> API only
#   (unset / sandbox) -> API + worker in ONE container.
#
# The sandbox default co-locates the worker with the API so they share the same
# local disk. Without S3 configured, raw uploads are written to local storage by
# the API; a separate worker container would have its own empty disk and fail to
# read them. Co-locating avoids that. For production, configure S3 and split the
# services by setting SERVICE_ROLE=api and SERVICE_ROLE=worker.
if [ "$SERVICE_ROLE" = "worker" ]; then
  exec ./start_worker.sh
elif [ "$SERVICE_ROLE" = "api" ]; then
  exec ./start_api.sh
else
  PYTHONPATH=. alembic upgrade head
  PYTHONPATH=. celery -A app.core.celery_app worker \
    --loglevel=info --pool=gevent --concurrency=50 \
    -Q fetch,extract,parse,analyse,document,deliver &
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2
fi
