from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from app.api.routes import batches, jobs, clients, analytics, upload, files, webhook
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

app.include_router(upload.router, prefix="/api/v1/upload", tags=["upload"])
app.include_router(batches.router, prefix="/api/v1/batches", tags=["batches"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(clients.router, prefix="/api/v1/clients", tags=["clients"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(files.router,   prefix="/api/v1/files",   tags=["files"])
app.include_router(webhook.router, prefix="/api/v1/webhook", tags=["webhook"])


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
