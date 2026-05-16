"""Dev-only local file serving route. In production, files come from S3 presigned URLs."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from app.core.config import settings

router = APIRouter()


@router.get("/{bucket}/{path:path}")
def serve_local_file(bucket: str, path: str):
    if not settings.use_local_storage:
        raise HTTPException(status_code=404, detail="Use S3 presigned URLs in production")
    file_path = Path(settings.LOCAL_STORAGE_PATH) / bucket / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path))
