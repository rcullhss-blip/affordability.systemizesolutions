#!/bin/sh
# Railway API service start script
# Runs DB migrations then starts the API server.
# Fail-fast: if the migration fails, crash the deploy instead of silently
# serving a broken schema (which previously caused 500s on a missing table).
set -e
PYTHONPATH=. alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2
