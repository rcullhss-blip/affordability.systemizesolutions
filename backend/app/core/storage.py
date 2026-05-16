"""
Unified storage layer — local filesystem in dev, S3 in production.
Switch is automatic based on whether AWS_ACCESS_KEY_ID is set.
"""
import os
from pathlib import Path
from app.core.config import settings


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    if settings.use_local_storage:
        return _local_write(bucket, key, data)
    from app.core.s3 import upload_bytes as s3_upload
    return s3_upload(bucket, key, data, content_type)


def download_bytes(bucket: str, key: str) -> bytes:
    if settings.use_local_storage:
        return _local_read(bucket, key)
    from app.core.s3 import download_bytes as s3_download
    return s3_download(bucket, key)


def get_download_url(bucket: str, key: str) -> str:
    if settings.use_local_storage:
        return f"/api/v1/files/{bucket}/{key}"
    from app.core.s3 import generate_presigned_url
    return generate_presigned_url(bucket, key)


def _local_path(bucket: str, key: str) -> Path:
    p = Path(settings.LOCAL_STORAGE_PATH) / bucket / key
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _local_write(bucket: str, key: str, data: bytes) -> str:
    _local_path(bucket, key).write_bytes(data)
    return key


def _local_read(bucket: str, key: str) -> bytes:
    return _local_path(bucket, key).read_bytes()
