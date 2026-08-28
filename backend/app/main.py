from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi import Depends
from app.api.routes import batches, jobs, clients, analytics, upload, files, webhook, cases, auth
from app.core.auth import require_auth, require_admin, seed_admin_from_env
from app.core.config import settings

app = FastAPI(
    title="Systemize API",
    description="Affordability assessment platform API",
    version="1.0.0",
)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth (28 Aug 2026 incident: the dashboard/API were reachable without sign-in) ──
# Every data route requires a signed-in user or a partner API key (see
# app.core.auth). Firm users are further scoped to their own firm inside the
# batches/jobs/upload handlers. Webhooks keep their own per-endpoint API keys.
ANY_USER = [Depends(require_auth)]
ADMIN_ONLY = [Depends(require_admin)]

app.include_router(auth.router,    prefix="/api/v1/auth",    tags=["auth"])
app.include_router(upload.router,  prefix="/api/v1/upload",  tags=["upload"],  dependencies=ANY_USER)
app.include_router(batches.router, prefix="/api/v1/batches", tags=["batches"], dependencies=ANY_USER)
app.include_router(jobs.router,    prefix="/api/v1/jobs",    tags=["jobs"],    dependencies=ANY_USER)
app.include_router(clients.router, prefix="/api/v1/clients", tags=["clients"], dependencies=ADMIN_ONLY)
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"], dependencies=ADMIN_ONLY)
app.include_router(files.router,   prefix="/api/v1/files",   tags=["files"],   dependencies=ADMIN_ONLY)
app.include_router(webhook.router, prefix="/api/v1/webhook", tags=["webhook"])
app.include_router(cases.router,   prefix="/api/v1/cases",   tags=["cases"],   dependencies=ADMIN_ONLY)


@app.on_event("startup")
def _bootstrap_admin():
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        seed_admin_from_env(db)
    except Exception:
        pass  # table may not exist yet on a first boot before migrations; harmless
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
