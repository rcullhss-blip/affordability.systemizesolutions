PYTHON = backend/.venv/bin/python
PIP    = backend/.venv/bin/pip
CELERY = backend/.venv/bin/celery
UVICORN = backend/.venv/bin/uvicorn
ALEMBIC = backend/.venv/bin/alembic

.PHONY: setup db-start db-stop migrate backend worker frontend dev

## First-time setup
setup:
	@echo "==> Installing Python dependencies..."
	cd backend && /usr/local/opt/python@3.12/bin/python3.12 -m venv .venv
	cd backend && .venv/bin/pip install --quiet --upgrade pip
	cd backend && .venv/bin/pip install --quiet -r requirements.txt
	@echo "==> Installing Node dependencies..."
	cd frontend && npm install --silent
	@echo "==> Starting services..."
	brew services start postgresql@16 || true
	brew services start redis || true
	@sleep 2
	@echo "==> Creating database..."
	-/usr/local/opt/postgresql@16/bin/psql -U $(shell whoami) postgres -c "CREATE USER systemize WITH PASSWORD 'systemize_dev';" 2>/dev/null || true
	-/usr/local/opt/postgresql@16/bin/psql -U $(shell whoami) postgres -c "CREATE DATABASE systemize OWNER systemize;" 2>/dev/null || true
	-/usr/local/opt/postgresql@16/bin/psql -U $(shell whoami) postgres -c "GRANT ALL PRIVILEGES ON DATABASE systemize TO systemize;" 2>/dev/null || true
	@echo "==> Running migrations..."
	cd backend && PYTHONPATH=. $(ALEMBIC) upgrade head
	@echo ""
	@echo "✓ Setup complete. Run: make dev"

## Start services
db-start:
	brew services start postgresql@16
	brew services start redis

## Stop services
db-stop:
	brew services stop postgresql@16
	brew services stop redis

## Run migrations
migrate:
	cd backend && PYTHONPATH=. $(ALEMBIC) upgrade head

## Start API server
backend:
	cd backend && PYTHONPATH=. $(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

## Start Celery worker (all queues for dev)
worker:
	cd backend && PYTHONPATH=. $(CELERY) -A app.core.celery_app worker \
		--loglevel=info \
		--concurrency=4 \
		--queues=fetch,extract,parse,analyse,document,deliver

## Start Next.js frontend
frontend:
	cd frontend && npm run dev

## Run everything (requires 3 terminals, or use: make dev)
dev:
	@echo "Starting Systemize in development mode..."
	@echo ""
	@echo "Run these in 3 separate terminals:"
	@echo "  Terminal 1: make backend"
	@echo "  Terminal 2: make worker"
	@echo "  Terminal 3: make frontend"
	@echo ""
	@echo "Then open: http://localhost:3000"
	@echo "API docs:  http://localhost:8000/docs"

## Check everything is running
status:
	@echo "=== Services ==="
	@brew services list | grep -E "postgresql|redis"
	@echo ""
	@echo "=== API ==="
	@curl -s http://localhost:8000/health 2>/dev/null && echo "" || echo "API not running"
	@echo ""
	@echo "=== Frontend ==="
	@curl -s http://localhost:3000 > /dev/null 2>&1 && echo "Frontend: running" || echo "Frontend: not running"
