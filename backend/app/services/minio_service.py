import asyncio
import io
import logging
import os
from functools import partial
from typing import Optional
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from datetime import timedelta

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[Minio] = None
_external_client: Optional[Minio] = None


def _parse_endpoint(endpoint: str) -> tuple[str, bool]:
    """解析 endpoint 为 (host:port, secure)。"""
    secure = settings.MINIO_USE_SSL
    ep = endpoint.strip()
    if ep.startswith("http://") or ep.startswith("https://"):
        parsed = urlparse(ep)
        secure = parsed.scheme == "https"
        ep = parsed.netloc
    return ep, secure


def get_minio_client() -> Minio:
    """Return a cached MinIO client instance (created once, reused thereafter)."""
    global _client
    if _client is not None:
        return _client

    endpoint, secure = _parse_endpoint(settings.MINIO_ENDPOINT)
    _client = Minio(
        endpoint,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=secure,
    )
    return _client


def get_external_minio_client() -> Optional[Minio]:
    """返回使用浏览器可访问外部 endpoint 的 MinIO client。

    容器内 MINIO_ENDPOINT=minio:9000 生成的 presigned URL 主机名为 minio，
    浏览器无法解析，导致视频不播放、下载提示"minio 拒绝连接"。
    设置 MINIO_EXTERNAL_ENDPOINT（如 localhost:9000）后，用外部地址重新生成
    签名 URL，保证签名 host 与浏览器访问地址一致（直接替换 host 会使
    SigV4 签名失效）。
    """
    global _external_client
    external = (settings.MINIO_EXTERNAL_ENDPOINT or "").strip()
    if not external:
        return None
    if _external_client is not None:
        return _external_client

    endpoint, secure = _parse_endpoint(external)
    _external_client = Minio(
        endpoint,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=secure,
    )
    return _external_client


def _generate_presigned_url(
    client: Minio,
    bucket: str,
    object_key: str,
    expires_seconds: int,
    method: str = "GET",
    response_headers: Optional[dict] = None,
) -> Optional[str]:
    """用指定 client 生成 presigned URL（同步执行）。

    response_headers：附加到签名的响应头覆盖参数（如
    {'response-content-disposition': 'attachment; filename="x.mp4"'}），
    让跨域 a 标签点击时强制下载而非播放。
    """
    try:
        if method == "PUT":
            return client.presigned_put_object(
                bucket,
                object_key,
                expires=timedelta(seconds=expires_seconds),
            )
        return client.presigned_get_object(
            bucket,
            object_key,
            expires=timedelta(seconds=expires_seconds),
            response_headers=response_headers,
        )
    except S3Error as e:
        logger.error(f"MinIO presigned URL generation failed: {e}")
        return None
    except Exception as e:
        logger.error(f"MinIO presigned URL generation failed: {e}")
        return None


async def upload_file(
    bucket: str,
    object_key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> bool:
    """Upload bytes to MinIO asynchronously (wraps synchronous MinIO client)."""
    try:
        client = get_minio_client()
        loop = asyncio.get_event_loop()

        # Ensure bucket exists
        exists = await loop.run_in_executor(None, client.bucket_exists, bucket)
        if not exists:
            await loop.run_in_executor(None, client.make_bucket, bucket)

        await loop.run_in_executor(
            None,
            partial(
                client.put_object,
                bucket,
                object_key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            ),
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
        loop = asyncio.get_event_loop()

        exists = await loop.run_in_executor(None, client.bucket_exists, bucket)
        if not exists:
            await loop.run_in_executor(None, client.make_bucket, bucket)

        await loop.run_in_executor(
            None,
            partial(
                client.fput_object,
                bucket,
                object_key,
                file_path,
                content_type=content_type,
            ),
        )
        logger.info(f"Uploaded {file_path} -> {bucket}/{object_key}")
        return True
    except S3Error as e:
        logger.error(f"MinIO file upload failed: {e}")
        return False


def _download_sync(bucket: str, object_key: str) -> bytes:
    """Synchronous helper: download object and return bytes."""
    client = get_minio_client()
    response = client.get_object(bucket, object_key)
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()
    return data


async def download_file(
    bucket: str,
    object_key: str,
) -> Optional[bytes]:
    """Download a file from MinIO as bytes."""
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, partial(_download_sync, bucket, object_key))
        return data
    except S3Error as e:
        logger.error(f"MinIO download failed: {e}")
        return None


async def get_presigned_url(
    bucket: str,
    object_key: str,
    expires_seconds: int = 3600,
    as_attachment: bool = False,
    filename: Optional[str] = None,
    internal: bool = False,
) -> Optional[str]:
    """Generate a presigned GET URL for temporary access.

    若配置了 MINIO_EXTERNAL_ENDPOINT，则用外部地址重新生成签名 URL，
    保证浏览器可访问且签名有效（直接替换 host 会使 SigV4 签名失效）。
    as_attachment=True 时附加 response-content-disposition=attachment，
    使浏览器跨域访问该链接时强制下载而非内联播放。

    internal=True 时强制使用内部 MinIO client（MINIO_ENDPOINT，如 minio:9000）。
    供 Worker 节点消费的 URL（源视频/封面/钩子/角标下载、成品上传）必须走内部
    client：Worker 与 MinIO 同处 Docker 网络、可直连 minio:9000；而 MINIO_EXTERNAL_ENDPOINT
    通常是 localhost:9000 或宿主机 LAN 地址，从后端容器内无法直连（region 探测会
    Connection refused），导致 presigned 生成失败、Worker 拿到空 URL 而下载素材报错。
    """
    response_headers = None
    if as_attachment:
        safe_name = (filename or os.path.basename(object_key) or "download.mp4").replace('"', "")
        response_headers = {
            "response-content-disposition": f'attachment; filename="{safe_name}"',
        }
    client = get_minio_client() if internal else (get_external_minio_client() or get_minio_client())
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(
            _generate_presigned_url,
            client,
            bucket,
            object_key,
            expires_seconds,
            "GET",
            response_headers,
        ),
    )


async def get_presigned_upload_url(
    bucket: str,
    object_key: str,
    expires_seconds: int = 7200,
    internal: bool = False,
) -> Optional[str]:
    """Generate a presigned PUT URL for Worker to upload files.

    优先用 MINIO_EXTERNAL_ENDPOINT 生成（外部 Worker 无法解析容器内 minio 主机名）；
    未配置时回退内部 endpoint，与旧行为兼容。

    internal=True 时强制使用内部 MinIO client（MINIO_ENDPOINT，如 minio:9000）。
    成品上传由同处 Docker 网络的 Worker 发起，必须走内部 client 才能生成可用 URL
    （见 get_presigned_url 同名校验说明）。
    """
    client = get_minio_client() if internal else (get_external_minio_client() or get_minio_client())
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_generate_presigned_url, client, bucket, object_key, expires_seconds, "PUT"),
    )


async def delete_file(bucket: str, object_key: str) -> bool:
    """Delete a file from MinIO."""
    try:
        client = get_minio_client()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, client.remove_object, bucket, object_key)
        logger.info(f"Deleted {bucket}/{object_key}")
        return True
    except S3Error as e:
        logger.error(f"MinIO delete failed: {e}")
        return False


def _list_objects_sync(bucket: str, prefix: str) -> list[dict]:
    """Synchronous helper: list objects and collect results."""
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


async def list_files(bucket: str, prefix: str = "") -> list[dict]:
    """List files in a MinIO bucket under a given prefix."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, partial(_list_objects_sync, bucket, prefix))
        return result
    except S3Error as e:
        logger.error(f"MinIO list failed: {e}")
        return []


async def get_file_info(bucket: str, object_key: str) -> Optional[dict]:
    """Get metadata for a file in MinIO."""
    try:
        client = get_minio_client()
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, client.stat_object, bucket, object_key)
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
        loop = asyncio.get_event_loop()
        exists = await loop.run_in_executor(None, client.bucket_exists, bucket)
        if not exists:
            await loop.run_in_executor(None, client.make_bucket, bucket)
            logger.info(f"Created bucket: {bucket}")
        return True
    except S3Error as e:
        logger.error(f"Failed to ensure bucket {bucket}: {e}")
        return False


async def download_to_file(
    bucket: str,
    object_key: str,
    local_path: str,
) -> bool:
    """Download an object from MinIO to a local file."""
    try:
        client = get_minio_client()
        loop = asyncio.get_event_loop()

        dir_name = os.path.dirname(local_path)
        if dir_name:
            # 第二个位置参数是 mode，不能传 True（会被当作 0o111）。
            # 使用显式关键字避免创建出仅可执行的目录。
            await loop.run_in_executor(None, os.makedirs, dir_name, 0o755, True)

        await loop.run_in_executor(
            None,
            partial(client.fget_object, bucket, object_key, local_path),
        )
        return True
    except S3Error as e:
        logger.error(f"MinIO download to file failed: {e}")
        return False
