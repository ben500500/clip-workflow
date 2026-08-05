import logging
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def create_autoclip_project(name: str, config: dict) -> Optional[str]:
    """Create a project on the AutoClip service.

    Returns the AutoClip project ID, or None on failure.
    """
    url = f"{settings.AUTOCLIP_URL}/projects"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json={"name": name, "config": config})
            resp.raise_for_status()
            data = resp.json()
            return data.get("id")
        except httpx.HTTPStatusError as e:
            logger.error(f"AutoClip create project failed: {e.response.status_code} {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"AutoClip request error: {e}")
    return None


async def upload_video(autoclip_project_id: str, video_path: str, file_name: str) -> bool:
    """Upload video to AutoClip service."""
    url = f"{settings.AUTOCLIP_URL}/upload"
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            with open(video_path, "rb") as f:
                files = {"file": (file_name, f, "video/mp4")}
                resp = await client.post(
                    url,
                    params={"project_id": autoclip_project_id},
                    files=files,
                )
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"AutoClip upload video failed: {e.response.status_code} {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"AutoClip upload request error: {e}")
        except OSError as e:
            logger.error(f"Failed to read video file: {e}")
    return False


async def trigger_pipeline(
    autoclip_project_id: str,
    steps: Optional[list[int]] = None,
) -> bool:
    """Trigger the AutoClip 6-step pipeline."""
    url = f"{settings.AUTOCLIP_URL}/pipeline/run"
    if steps is None:
        steps = [1, 2, 3, 4, 5, 6]
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                url,
                json={"project_id": autoclip_project_id, "steps": steps},
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"AutoClip pipeline trigger failed: {e.response.status_code} {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"AutoClip pipeline request error: {e}")
    return False


async def get_pipeline_progress(autoclip_project_id: str) -> Optional[dict]:
    """Get the current pipeline progress from AutoClip."""
    url = f"{settings.AUTOCLIP_URL}/progress/{autoclip_project_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"AutoClip progress query failed: {e.response.status_code} {e.response.text}"
            )
        except httpx.RequestError as e:
            logger.error(f"AutoClip progress request error: {e}")
    return None


async def get_clips(
    autoclip_project_id: str,
    min_score: float = 60.0,
    max_clips: int = 30,
) -> list[dict[str, Any]]:
    """Get clip candidates from AutoClip."""
    url = f"{settings.AUTOCLIP_URL}/clips"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                url,
                params={
                    "project_id": autoclip_project_id,
                    "min_score": min_score,
                    "max_clips": max_clips,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("clips", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"AutoClip get clips failed: {e.response.status_code} {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"AutoClip get clips request error: {e}")
    return []


async def check_autoclip_health() -> bool:
    """Check if the AutoClip service is reachable.

    注意：AutoClip 的 /health 端点在根路径，但 AUTOCLIP_URL 默认带 /api/v1 前缀。
    这里同时探测两种路径，避免因前缀不匹配误判服务不可达。
    """
    base = settings.AUTOCLIP_URL.rstrip("/")
    candidates = [
        f"{base}/health",
        f"{base.replace('/api/v1', '')}/health",
    ]
    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in candidates:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True
            except Exception:
                continue
    return False


async def delete_autoclip_project(autoclip_project_id: str) -> bool:
    """Delete a project on the AutoClip service (used for rollback)."""
    url = f"{settings.AUTOCLIP_URL}/projects/{autoclip_project_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.delete(url)
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"AutoClip delete project failed: {e.response.status_code} {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"AutoClip delete request error: {e}")
    return False