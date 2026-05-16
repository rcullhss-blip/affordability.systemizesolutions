import boto3
from botocore.exceptions import ClientError
from app.core.config import settings

_s3 = None


def get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        )
    return _s3


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    get_s3().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return key


def download_bytes(bucket: str, key: str) -> bytes:
    response = get_s3().get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def generate_presigned_url(bucket: str, key: str, expires_in: int = 3600) -> str:
    return get_s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )
