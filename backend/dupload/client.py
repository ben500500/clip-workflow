"""dupload 客户端（对接 192.168.1.21:8800 dramaupload / dupload 独立服务）。

调用 `POST {base_url}{import_path}`（默认 `POST /api/dupload/tasks`），
body 单条任务：
    {
      "dramaName": <剧名>,
      "shareUrl": <网盘地址>,
      "action": "only_download",      # 仅下载
      "appID": [""],                   # only_download 时不关联小程序
      "extKeyWords": [],
      "extIgnoreDirNames": [],
      "extCoverKeyWords": []
    }

「仅下载」动作：dupload 服务自行去百度网盘下载该剧入库，clip-workflow 只转交
shareUrl，不做网盘解析/登录。鉴权头由 dupload_config.auth_headers 注入（可配置）。
"""

import logging
from typing import Optional

import httpx

from dupload.config import DuploadConfig, load_dupload_config

logger = logging.getLogger(__name__)


class DuploadError(Exception):
    """dupload 客户端错误。"""


class DuploadClient:
    """dupload 推送客户端。"""

    def __init__(self, config: Optional[DuploadConfig] = None) -> None:
        cfg = config or load_dupload_config()
        self.base = cfg.base_url.rstrip("/")
        self.path = cfg.import_path
        self.action = cfg.action
        self.timeout = cfg.request_timeout
        self.auth_headers = cfg.auth_headers or {}
        self.config = cfg

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        for k, v in (self.auth_headers or {}).items():
            if v is not None:
                headers[str(k)] = str(v)
        return headers

    async def push_task(self, drama_name: str, share_url: str) -> dict:
        """推送单条任务到 dupload 批量导入接口（action=only_download）。

        Args:
            drama_name: 剧名
            share_url: 素材链接（百度网盘 shareUrl）

        Returns:
            dupload 服务的响应体（dict）。非 2xx 或非 JSON 响应会抛 DuploadError。
        """
        if not (drama_name or "").strip():
            raise DuploadError("剧名不能为空")
        if not (share_url or "").strip():
            raise DuploadError("素材链接(shareUrl)不能为空")

        body = {
            "dramaName": drama_name,
            "shareUrl": share_url,
            "action": self.action or "only_download",
            "appID": [""],  # only_download 时不关联小程序（与 21:8800 前端实际调用一致）
            "extKeyWords": [],
            "extIgnoreDirNames": [],
            "extCoverKeyWords": [],
        }
        url = f"{self.base}{self.path}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers=self._build_headers(),
            ) as client:
                resp = await client.post(url, json=body)
        except DuploadError:
            raise
        except Exception as e:
            raise DuploadError(f"请求 dupload 服务失败: {e}") from e

        try:
            payload = resp.json()
        except Exception:
            payload = {"status_code": resp.status_code, "text": resp.text[:500]}

        if resp.status_code >= 400:
            raise DuploadError(
                f"dupload 接口 http {resp.status_code}: {payload if isinstance(payload, dict) else payload}"
            )
        return payload


_client: Optional[DuploadClient] = None


def get_client(config: Optional[DuploadConfig] = None) -> DuploadClient:
    """获取客户端；显式传入 config 时重建（用于 system_config 热更）。"""
    global _client
    if _client is None or config is not None:
        _client = DuploadClient(config=config)
    return _client
