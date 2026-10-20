"""智令「文件上传」客户端（doc/125 取签名 → 直传 S3 temp 桶）。

链路（官方文档 https://api.17zhiling.com/doc/125）：
1. `GET /api/upload/signature?key=&fileName=&contentType=&expiresIn=`
   → `data`: uploadUrl（S3 POST 端点）/ method=POST / formFields（AWS4 签名字段）/
     objectKey / fileUrl（可直接作为 doc/120 的 videoUrl）
2. 用 `multipart/form-data` POST 到 uploadUrl：**formFields 各字段在前、file 最后**
   （AWS S3 POST policy 要求 file 必须是最后一个字段，顺序错了直接 403）

约束与坑：
- 文件落智令自有 S3 temp 桶，**6 小时后自动删除**，因此拿到 fileUrl 必须尽快提交 doc/120；
- 上传只传 `file` 字段，**不要自己设 Content-Type 头**：multipart 的 part 头由 httpx 生成，
  手写会覆盖签名里的 Content-Type 导致 policy 校验失败；
- formFields 是签名产物，原样透传（含 x-amz-* 与 policy），不要改写/排序；
- 超时按文件大小动态算（大文件 6MB/s 量级），固定超时会把慢网的长传直接掐断；
- fail-soft 与 doc/120 一致：一律抛 UploadError，由上层写库 failed，不在 API 层抬 500。
"""

import logging
import os
from dataclasses import dataclass
from typing import BinaryIO, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class UploadError(Exception):
    """上传链路（签名 / S3 POST）失败，供上层记 failed 而不抬 500。"""


@dataclass
class UploadTicket:
    """doc/125 返回的一次上传凭据。"""

    upload_url: str
    form_fields: dict
    object_key: Optional[str] = None
    file_url: Optional[str] = None


def _truncate(text: Optional[str], limit: int = 300) -> Optional[str]:
    if not text:
        return None
    text = str(text).strip()
    return text[:limit] if len(text) > limit else text


class UploadClient:
    """智令文件上传客户端（doc/125）。密钥与 doc/107、doc/120 复用同一个 env。"""

    def __init__(self) -> None:
        self.base = (settings.WECHAT_DL_ZHILING_PROMPT_BASE or "").rstrip("/")
        self.key = (
            os.getenv("WECHAT_DL_ZHILING_KEY", "")
            or getattr(settings, "WECHAT_DL_ZHILING_KEY", "")
            or ""
        ).strip()
        self.sign_path = settings.WECHAT_DL_ZHILING_UPLOAD_SIGN_PATH
        self.timeout = settings.WECHAT_DL_PROMPT_TIMEOUT
        self.min_upload_timeout = settings.WECHAT_DL_PROMPT_UPLOAD_TIMEOUT
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(float(self.timeout)),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (clip-workflow/wechat-dl)"},
        )

    def _url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    async def sign(
        self,
        file_name: str,
        content_type: str = "video/mp4",
        expires_in: int = 900,
    ) -> UploadTicket:
        """取一次上传签名（doc/125）。业务异常（code != 200）抛 UploadError。"""
        if not self.key:
            raise UploadError("未配置 WECHAT_DL_ZHILING_KEY，无法申请上传签名")
        params = {
            "key": self.key,
            "fileName": file_name or "video.mp4",
            "contentType": content_type or "video/mp4",
            "expiresIn": str(expires_in),
        }
        try:
            resp = await self._client.get(self._url(self.sign_path), params=params)
        except httpx.HTTPError as e:
            raise UploadError(f"申请上传签名请求失败: {e}") from e

        if resp.status_code != 200:
            raise UploadError(f"申请上传签名 http {resp.status_code}: {_truncate(resp.text)}")
        try:
            body = resp.json()
        except Exception:
            raise UploadError(
                f"申请上传签名响应非 JSON（可能被 WAF 拦截），body 前 120 字节: {resp.text[:120]}"
            )

        code = body.get("code")
        if code != 200:
            raise UploadError(f"申请上传签名失败（code={code}）: {body.get('msg') or '未知原因'}")

        data = body.get("data") or {}
        if not isinstance(data, dict):
            raise UploadError("申请上传签名响应缺少 data")
        upload_url = (data.get("uploadUrl") or "").strip()
        form_fields = data.get("formFields") or {}
        if not upload_url or not isinstance(form_fields, dict):
            raise UploadError(f"上传签名缺少 uploadUrl/formFields: {_truncate(str(body))}")
        file_url = (data.get("fileUrl") or "").strip() or None
        if not file_url:
            # 没 fileUrl 就无法喂给 doc/120，提前失败比传到一半再报错好
            raise UploadError("上传签名未返回 fileUrl，无法提交反推任务")
        return UploadTicket(
            upload_url=upload_url,
            form_fields={str(k): str(v) for k, v in form_fields.items()},
            object_key=(data.get("objectKey") or None),
            file_url=file_url,
        )

    async def post_file(
        self,
        ticket: UploadTicket,
        file_obj: BinaryIO,
        file_name: str,
        size_bytes: int,
        content_type: str = "video/mp4",
    ) -> None:
        """按签名把文件直传 S3（multipart/form-data，formFields 在前、file 最后）。"""
        # 动态超时：6MB/s 量级 + 120s 兜底，避免固定 15s/120s 掐断大文件
        size_mb = max(1.0, size_bytes / (1024 * 1024))
        upload_timeout = max(float(self.min_upload_timeout), size_mb * 6.0)
        # formFields 在前、file 最后：AWS POST policy 的硬要求（顺序错 → 403）
        fields = list(ticket.form_fields.items())
        file_obj.seek(0)
        files = {"file": (file_name, file_obj, content_type or "video/mp4")}
        try:
            resp = await self._client.post(
                ticket.upload_url,
                data=fields,
                files=files,
                timeout=httpx.Timeout(upload_timeout),
            )
        except httpx.HTTPError as e:
            raise UploadError(f"上传视频到存储失败: {e}") from e

        if not (200 <= resp.status_code < 300):
            raise UploadError(f"上传视频到存储 http {resp.status_code}: {_truncate(resp.text)}")
        # S3 POST 成功响应是 204 空体；部分网关回 200 带 XML 错误体，这里做二次兜底
        if resp.status_code == 200 and "<Error>" in (resp.text or ""):
            raise UploadError(f"上传视频到存储被拒: {_truncate(resp.text)}")

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass
