"""dupload 客户端（对接 192.168.1.21:8800 dramaupload / dupload 独立服务）。

调用 `POST {base_url}{import_path}`（默认 `POST /api/dupload/tasks`），
body 单条任务（与 21:8800 前端批量导入单条一致）：
    {
      "workHost": <workHost 配置项>,
      "appID": "",                     # only_download 时用字符串 ""（不关联小程序）
      "appSecret": <appSecret 配置项>,
      "cpID": <cpID 配置项>,
      "dramaName": <剧名>,
      "shareUrl": <网盘地址>,
      "action": "only_download",      # 仅下载
      "extKeyWords": [],
      "extIgnoreDirNames": [],
      "extCoverKeyWords": []
    }

「仅下载」动作：dupload 服务自行去百度网盘下载该剧入库，clip-workflow 只转交
shareUrl，不做网盘解析/登录。实测 POST /api/dupload/tasks 为公开接口（无鉴权），
故不再依赖 auth_headers；workHost/appSecret/cpID 从 dupload_config 读取。
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
        self.work_host = cfg.work_host or ""
        self.app_secret = cfg.app_secret or ""
        self.cp_id = cfg.cp_id or ""
        self.config = cfg

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

        # workHost/appSecret/cpID 为接口必填；缺任一 dupload 返回 422。
        # 这些配置在系统设置（dupload_config）中录入，这里读 self.* 取值。
        body = {
            "workHost": self.work_host,
            "appID": "",  # action=only_download 时 appID 用字符串 ""（非数组）
            "appSecret": self.app_secret,
            "cpID": self.cp_id,
            "dramaName": drama_name,
            "shareUrl": share_url,
            "action": self.action or "only_download",
            "extKeyWords": [],
            "extIgnoreDirNames": [],
            "extCoverKeyWords": [],
        }
        url = f"{self.base}{self.path}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
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
