import io
import logging
from typing import Optional
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from app.config import settings

logger = logging.getLogger(__name__)


def get_minio_client() -> Minio:
    """Create and return a MinIO client instance."""
    endpoint = settings.MINIO_ENDPOINT
    secure = settings.MINIO_USE_SSL

    # If endpoint has a scheme, parse it
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        parsed = urlparse(endpoint)
        secure = parsed.scheme == "https"
        endpoint = parsed.netloc

    client = Minio(
        endpoint,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=secure,
    )
    return client


async def upload_file(
    bucket: str,
    object_key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> bool:
    """Upload bytes to MinIO asynchronously (wraps synchronous MinIO client)."""
    try:
        client = get_minio_client()
        # Ensure bucket exists
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        client.put_object(
            bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.info(f"Uploaded {object_key} to bucket {bucket}")
        return True
    except S3Error as e:
        logger.error(f"MinIO upload failed: {e}")
        return False


async def upload_file_from_path(
    bucket: str,
    object_key: str,
    file_path: str,
    content_type: str = "application/octet-stream",
) -> bool:
    """Upload a local file to MinIO."""
    try:
        client = get_minio_client()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        result = client.fput_object(
            bucket,
            object_key,
            file_path,
            content_type=content_type,
        )
        logger.info(f"Uploaded {file_path} -> {bucket}/{object_key} (etag={result.etag})")
        return True
    except S3Error as e:
        logger.error(f"MinIO file upload failed: {e}")
        return False


async def download_file(
    bucket: str,
    object_key: str,
) -> Optional[bytes]:
    """Download a file from MinIO as bytes."""
    try:
        client = get_minio_client()
        response = client.get_object(bucket, object_key)
        data = response.read()
        response.close()
        response.release_conn()
        return data
    except S3Error as e:
        logger.error(f"MinIO download failed: {e}")
        return None


async def get_presigned_url(
    bucket: str,
    object_key: str,
    expires_seconds: int = 3600,
) -> Optional[str]:
    """Generate a presigned GET URL for temporary access."""
    try:
        client = get_minio_client()
        url = client.presigned_get_object(
            bucket,
            object_key,
            expires=expires_seconds,
        )
        return url
    except S3Error as e:
        logger.error(f"MinIO presigned URL generation failed: {e}")
        return None


async def delete_file(bucket: str, object_key: str) -> bool:
    """Delete a file from MinIO."""
    try:
        client = get_minio_client()
        client.remove_object(bucket, object_key)
        logger.info(f"Deleted {bucket}/{object_key}")
        return True
    except S3Error as e:
        logger.error(f"MinIO delete failed: {e}")
        return False


async def list_files(bucket: str, prefix: str = "") -> list[dict]:
    """List files in a MinIO bucket under a given prefix."""
    try:
        client = get_minio_client()
        objects = client.list_objects(bucket, prefix=prefix, recursive=True)
        result = []
        for obj in objects:
            result.append({
                "key": obj.object_name,
                "size": obj.size,
                "etag": obj.etag,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
            })
        return result
    except S3Error as e:
        logger.error(f"MinIO list failed: {e}")
        return []


async def get_file_info(bucket: str, object_key: str) -> Optional[dict]:
    """Get metadata for a file in MinIO."""
    try:
        client = get_minio_client()
        info = client.stat_object(bucket, object_key)
        return {
            "key": object_key,
            "size": info.size,
            "etag": info.etag,
            "last_modified": info.last_modified.isoformat() if info.last_modified else None,
            "content_type": info.content_type,
        }
    except S3Error:
        return None


async def ensure_bucket(bucket: str) -> bool:
    """Ensure a bucket exists, creating it if necessary."""
    try:
        client = get_minio_client()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info(f"Created bucket: {bucket}")
        return True
    except S3Error as e:
        logger.error(f"Failed to ensure bucket {bucket}: {e}")
        return False