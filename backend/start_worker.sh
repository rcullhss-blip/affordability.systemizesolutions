#!/bin/sh
# Railway worker service start script
exec celery -A app.core.celery_app worker \
  --loglevel=info \
  --pool=gevent \
  --concurrency=50 \
  -Q fetch,extract,parse,analyse,document,deliver
