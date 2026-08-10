#!/bin/sh
# Worker service start script (Render/Railway).
# Concurrency is env-tunable (WORKER_CONCURRENCY) so it can be adjusted without a
# code change. Default 25: enough I/O parallelism per instance while keeping the
# Redis/Postgres connection footprint sane when running several worker instances
# (4 instances x 50 exhausted Redis 'max clients'; 4 x 25 is comfortable).
exec celery -A app.core.celery_app worker \
  --loglevel=info \
  --pool=gevent \
  --concurrency="${WORKER_CONCURRENCY:-25}" \
  -Q fetch,extract,parse,analyse,document,deliver,watchdog
