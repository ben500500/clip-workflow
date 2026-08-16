"""元宝解析客户端（立项决策②：元宝 get_parse_result 作为 P0 主链路）。

端点：`{WECHAT_DL_YUANBAO_API_BASE}/.../get_parse_result`
输入视频号分享链接 → 返回视频元数据（标题/封面/真实播放地址）。

注意：该接口为非公开/易变接口（评审 R1 最高风险点）。本模块将其收敛为
单一可替换实现（YuanbaoClient），统一返回 `ParseResult` 结构；上层在
解析失败时降级到预览层兜底（preview_client）。接口鉴权/限流通过
`WECHAT_DL_YUANBAO_KEY` 与调用方节流策略处理。

为最大可剥离性，本包不依赖主系统 API；但通过 `app.config.settings` 读取
配置（该依赖可在剥离时替换为独立配置）。
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """统一解析结果结构（元宝 / 预览层共用）。"""

    success: bool
    channel: str  # yuanbao / preview
    play_url: Optional[str] = None
    title: Optional[str] = None
    cover_url: Optional[str] = None
    duration: Optional[float] = None
    meta: dict = field(default_factory=dict)
    raw: str = ""
    error: Optional[str] = None


class YuanbaoParseError(Exception):
    """元宝解析失败（触发预览层兜底降级）。"""


class YuanbaoClient:
    """元宝 get_parse_result 客户端。

    - get_parse_result 端点路径可配置（WECHAT_DL_YUANBAO_API_BASE）。
    - 统一返回 ParseResult；解析失败抛 YuanbaoParseError（供上层降级）。
    """

    def __init__(self) -> None:
        self.base = settings.WECHAT_DL_YUANBAO_API_BASE
        self.key = settings.WECHAT_DL_YUANBAO_KEY
        # finder 签名/拉流地址通常在元宝解析结果中带 TTL，直接透传
        self._client = httpx.AsyncClient(
            base_url=self.base,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (clip-workflow/wechat-dl)"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def parse(self, share_url: str) -> ParseResult:
        """调用元宝 get_parse_result 解析分享链接。

        接口路径按需在子类/配置中调整；这里使用设计文档约定的
        `.../get_parse_result` 端点，并允许环境变量注入完整路径。
        """
        # 端点未配置兜底：base 仍是默认占位地址（yuanbao.tencent.com）且未配
        # key 时，该接口必然 405/不可用，直接判为未配置，跳过主链路让上层
        # 走预览层兜底，避免每次都白发一次请求并写无意义失败记录。
        _placeholder_base = "https://yuanbao.tencent.com"
        if (not self.base) or self.base.rstrip("/") == _placeholder_base or (not self.key):
            raise YuanbaoParseError(
                "元宝解析未配置有效端点（WECHAT_DL_YUANBAO_API_BASE 为默认占位地址 "
                "或 WECHAT_DL_YUANBAO_KEY 为空），跳过主链路，等待预览层兜底"
            )
        try:
            payload = {"url": share_url, "need_video_info": True}
            if self.key:
                payload["key"] = self.key
            resp = await self._client.post("/get_parse_result", json=payload)
            if resp.status_code != 200:
                raise YuanbaoParseError(f"yuanbao http {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            return self._normalize(data, raw=resp.text)
        except YuanbaoParseError:
            raise
        except httpx.HTTPError as e:
            raise YuanbaoParseError(f"yuanbao request failed: {e}") from e
        except Exception as e:
            raise YuanbaoParseError(f"yuanbao parse error: {e}") from e

    def _normalize(self, data: dict, raw: str = "") -> ParseResult:
        """把元宝原始响应归一化为 ParseResult。

        真实接口字段名随接口演进，这里做兼容映射：优先从常见字段读取
        play_url/video_url/url、title/name、cover/cover_url、duration。
        """
        play_url = (
            data.get("play_url")
            or data.get("video_url")
            or data.get("url")
            or data.get("video_info", {}).get("play_url")
            or data.get("video_info", {}).get("url")
        )
        title = data.get("title") or data.get("name") or data.get("video_info", {}).get("title")
        cover = data.get("cover") or data.get("cover_url") or data.get("video_info", {}).get("cover")
        duration = data.get("duration") or data.get("video_info", {}).get("duration")
        if not play_url:
            raise YuanbaoParseError("yuanbao response has no play_url")
        return ParseResult(
            success=True,
            channel="yuanbao",
            play_url=str(play_url),
            title=str(title) if title else None,
            cover_url=str(cover) if cover else None,
            duration=float(duration) if duration else None,
            meta=data,
            raw=raw,
        )


# 单例（复用连接，降低元宝接口滥用/限流风险，评审 R2）
_yuanbao_client: Optional[YuanbaoClient] = None


def get_yuanbao_client() -> YuanbaoClient:
    global _yuanbao_client
    if _yuanbao_client is None:
        _yuanbao_client = YuanbaoClient()
    return _yuanbao_client
