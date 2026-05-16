from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import batches, jobs, clients, analytics, upload, files
from app.core.config import settings

app = FastAPI(
    title="Systemize API",
    description="Affordability assessment platform API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://affordability.systemizesolutions.co.uk",
        "https://admin.systemizesolutions.co.uk",
        "https://affordabilityassessment.systemizesolutions.co.uk",
        "https://affordability-systemize.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api/v1/upload", tags=["upload"])
app.include_router(batches.router, prefix="/api/v1/batches", tags=["batches"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(clients.router, prefix="/api/v1/clients", tags=["clients"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(files.router, prefix="/api/v1/files", tags=["files"])


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
