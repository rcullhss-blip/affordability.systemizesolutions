#!/bin/sh
# Railway API service start script
# Runs DB migrations then starts the API server
PYTHONPATH=. alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2
