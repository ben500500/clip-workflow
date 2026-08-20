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

多主机推送（与 21:8800 前端批量导入一致）：
- `GET /api/dupload/hosts`（公开接口）返回全部主机数组，如
  ["10.10.0.5:8765", ..., "mps.mi-von.com:25465", ...]，前端默认全选；
- 本客户端推送时：若配置了 `work_host`（或 `work_hosts` 列表）则推送配置的
  主机；否则拉取全部 hosts 逐个推送，覆盖全部下载节点；
- `appSecret` 按 workHost 匹配：若配置了 app_secret 则全主机共用；否则尝试
  从 hosts 接口响应中按主机探测，探测不到则传空串（由下载平台自行处理）。
"""

import asyncio
import logging
from typing import Optional

import httpx

from dupload.config import DuploadConfig, load_dupload_config

logger = logging.getLogger(__name__)

HOSTS_PATH = "/api/dupload/hosts"


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
        self.work_hosts = list(cfg.work_hosts or [])
        self.app_secret = cfg.app_secret or ""
        self.cp_id = cfg.cp_id or ""
        self.config = cfg

    async def _get_hosts(self) -> list:
        """从 `GET {base}/api/dupload/hosts` 拉取全部主机列表。

        Returns:
            主机字符串列表（如 ["10.10.0.5:8765", "mps.mi-von.com:25465"]）。
            接口异常或响应结构不符时返回空列表（由调用方决定兜底）。
        """
        url = f"{self.base}{HOSTS_PATH}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            ) as client:
                resp = await client.get(url)
            if resp.status_code >= 400:
                logger.warning("拉取 dupload hosts 失败 http %s: %s", resp.status_code, resp.text[:200])
                return []
            data = resp.json()
        except Exception as e:
            logger.warning("拉取 dupload hosts 异常: %s", e)
            return []

        if isinstance(data, list):
            hosts = [str(h).strip() for h in data if str(h).strip()]
        elif isinstance(data, dict):
            # 兼容 {"hosts": [...]} / {"data": [...]} / {"items": [...]} 结构
            hosts = []
            for key in ("hosts", "data", "items", "list"):
                val = data.get(key)
                if isinstance(val, list):
                    hosts = [str(h).strip() for h in val if str(h).strip()]
                    break
        else:
            hosts = []
        return hosts

    async def _resolve_targets(self) -> list:
        """解析推送目标主机列表（去重保序）。

        优先级：配置 work_host（单个） > 配置 work_hosts（列表） > hosts 接口全量。
        """
        configured = [h.strip() for h in ([self.work_host] if self.work_host else self.work_hosts or []) if h.strip()]
        if configured:
            return list(dict.fromkeys(configured))
        hosts = await self._get_hosts()
        return list(dict.fromkeys(hosts))

    async def push_task(self, drama_name: str, share_url: str) -> dict:
        """推送单条任务到 dupload 批量导入接口（action=only_download）。

        默认推送到全部主机（每个主机各发一条 POST）；若配置了 work_host /
        work_hosts 则只推送到配置的主机。聚合各主机响应返回。

        Args:
            drama_name: 剧名
            share_url: 素材链接（百度网盘 shareUrl）

        Returns:
            聚合后的响应体 dict：
            {
              "targets": [<各主机名>],
              "results": [{host, ok, status_code, response, error?}, ...],
              "success_count": int,
              "failed_count": int
            }
            任一主机请求非 2xx 或非 JSON 时对应结果 ok=False（不整体抛错，
            由调用方根据 success_count / failed_count 判定）。
            若目标主机为空则抛 DuploadError。
        """
        if not (drama_name or "").strip():
            raise DuploadError("剧名不能为空")
        if not (share_url or "").strip():
            raise DuploadError("素材链接(shareUrl)不能为空")

        targets = await self._resolve_targets()
        if not targets:
            raise DuploadError("没有可推送的 workHost：未配置 work_host/work_hosts，且 dupload hosts 接口未返回任何主机")

        # 按主机探测 appSecret（hosts 接口若返回 {host: secret} 结构，按主机匹配）
        secret_by_host = {}
        if not self.app_secret:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout),
                    follow_redirects=True,
                    headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                ) as client:
                    resp = await client.get(f"{self.base}{HOSTS_PATH}")
                if resp.status_code < 400:
                    data = resp.json()
                    if isinstance(data, dict):
                        for key in ("secrets", "appSecrets", "app_secrets"):
                            val = data.get(key)
                            if isinstance(val, dict):
                                for h, s in val.items():
                                    if s is not None:
                                        secret_by_host[str(h).strip()] = str(s)
                                break
            except Exception as e:
                logger.debug("探测 hosts 接口 appSecret 失败（忽略）: %s", e)

        async def _post(host: str) -> dict:
            body = {
                "workHost": host,
                "appID": "",  # action=only_download 时 appID 用字符串 ""（非数组）
                "appSecret": self.app_secret or secret_by_host.get(host, ""),
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
            except Exception as e:
                return {"host": host, "ok": False, "error": str(e)}
            try:
                payload = resp.json()
            except Exception:
                payload = {"status_code": resp.status_code, "text": resp.text[:500]}
            ok = resp.status_code < 400
            result = {"host": host, "ok": ok, "status_code": resp.status_code, "response": payload}
            if not ok:
                result["error"] = f"http {resp.status_code}"
            return result

        results = await asyncio.gather(*[_post(h) for h in targets])
        success_count = sum(1 for r in results if r["ok"])
        return {
            "targets": targets,
            "results": results,
            "success_count": success_count,
            "failed_count": len(results) - success_count,
        }


_client: Optional[DuploadClient] = None


def get_client(config: Optional[DuploadConfig] = None) -> DuploadClient:
    """获取客户端；显式传入 config 时重建（用于 system_config 热更）。"""
    global _client
    if _client is None or config is not None:
        _client = DuploadClient(config=config)
    return _client
