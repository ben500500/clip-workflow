"""
在线视觉模型客户端（OpenAI 兼容 /chat/completions，用于「画面理解」切换）

与 ollama_client 的本地 Ollama 视觉链路并列，服务「画面理解」的在线切换：
抽帧后把图片以 base64 data URL 塞进 OpenAI 兼容消息的 image_url content part，
POST 到 `{base}/chat/completions`，返回结构化 JSON 描述。

特性：
- 复用 shared_config 的 LLM_API_BASE / LLM_API_KEY / FRAME_ANALYSIS_MODEL
- 与 Ollama 链路输出契约完全一致（frame_analyzer 的 _normalize_description 兜底）
- 超时与重试、错误静默降级（在线不可用时返回 None，不影响主流程）
"""
import base64
import json
import logging
import os
from typing import Any, Dict, Optional

from .shared_config import LLM_API_BASE, LLM_API_KEY, FRAME_ANALYSIS_MODEL

logger = logging.getLogger(__name__)

# 在线调用超时（秒）。视觉理解含图片上传与推理，适当放宽；
# 统一走 MiMo(mimo-v2.5) 后推理耗时长，默认 240s（2026-09-02）
VISION_TIMEOUT = int(os.getenv("VISION_TIMEOUT", "240"))
# 最大重试次数
VISION_MAX_RETRIES = int(os.getenv("VISION_MAX_RETRIES", "2"))


class VisionLLMClient:
    """OpenAI 兼容在线视觉模型客户端（/chat/completions，image_url base64）。"""

    # 类级失败切换链（2026-11-23 用户需求）：frame_analyzer 每 clip 新建实例，
    # 链与状态 hook 必须挂类上才能跨实例生效；条目 {model, api_base, api_key}
    _failover_chain: list = []
    _status_hook = None

    @classmethod
    def set_failover_chain(cls, chain: list, status_hook=None) -> None:
        """设置视觉失败切换链（main.py 每次选点前注入）与状态回调。"""
        cls._failover_chain = list(chain or [])
        cls._status_hook = status_hook

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.base_url = (base_url or LLM_API_BASE).rstrip("/")
        self.api_key = api_key or LLM_API_KEY
        self.model = model or FRAME_ANALYSIS_MODEL

    @property
    def available(self) -> bool:
        """探测在线视觉模型是否可用（配置了 base_url + api_key + model）。"""
        if not self.api_key:
            logger.warning("在线视觉模型未配置 LLM_API_KEY，将回退本地 Ollama")
            return False
        if not self.model:
            logger.warning("在线视觉模型未配置 FRAME_ANALYSIS_MODEL，将回退本地 Ollama")
            return False
        return True

    def describe_image(self, image_bytes: bytes, prompt: str) -> Optional[Dict[str, Any]]:
        """
        发送单张图片到在线视觉模型，返回结构化 JSON。

        Args:
            image_bytes: 图片原始字节（JPEG/PNG）
            prompt: 分析提示词（要求输出 JSON）

        Returns:
            解析后的 dict；失败返回 None（调用方静默降级）。
        """
        if not image_bytes:
            return None
        if not self.available:
            return None

        # 失败切换：主模型耗尽重试仍失败 → 依链切换下一个视觉模型重试同一帧
        chain = type(self)._failover_chain or []
        for entry in [None] + list(chain):
            if entry is not None:
                self._apply_failover_entry(entry)
            result = self._describe_once(image_bytes, prompt)
            if result is not None:
                return result
        return None

    def _apply_failover_entry(self, entry: dict) -> None:
        """切换到链中下一个视觉模型并经 status_hook 实时透出。"""
        prev = self.model
        self.model = entry.get("model") or self.model
        if entry.get("api_base"):
            self.base_url = entry["api_base"].rstrip("/")
        if entry.get("api_key"):
            self.api_key = entry["api_key"]
        detail = f"视觉模型 {prev} 无响应，已切换到 {self.model}"
        logger.warning(detail)
        hook = type(self)._status_hook
        if hook:
            try:
                hook(detail)
            except Exception:
                pass

    def _describe_once(self, image_bytes: bytes, prompt: str) -> Optional[Dict[str, Any]]:
        """单模型尝试（含 VISION_MAX_RETRIES 重试）；失败返回 None。"""
        b64 = base64.b64encode(image_bytes).decode()
        data_url = f"data:image/jpeg;base64,{b64}"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "stream": False,
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        try:
            from curl_cffi import requests as cfrequests
        except ImportError:
            logger.error("在线视觉模型需要 curl_cffi（pip install curl_cffi）")
            return None

        last_err: Optional[Exception] = None
        # 有切换链时每模型最多 2 次尝试（快速让位给下一模型），无链维持原重试数
        max_attempts = (VISION_MAX_RETRIES + 1) if not (type(self)._failover_chain or []) else 2
        for attempt in range(max_attempts):
            try:
                resp = cfrequests.post(
                    url,
                    headers=headers,
                    json=payload,
                    impersonate="chrome",
                    timeout=VISION_TIMEOUT,
                )
                if resp.status_code >= 400:
                    logger.warning(
                        f"在线视觉模型 HTTP {resp.status_code}（第{attempt + 1}次）: {resp.text[:300]}"
                    )
                    last_err = RuntimeError(f"HTTP {resp.status_code}")
                    continue
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                return self._parse_json(raw)
            except Exception as e:
                logger.warning(f"在线视觉模型调用失败（第{attempt + 1}次）: {e}")
                last_err = e
            if attempt < VISION_MAX_RETRIES:
                import time
                time.sleep(2 ** attempt)

        logger.error(f"在线视觉模型图片分析最终失败: {last_err}")
        return None

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
        """解析模型输出为 dict：先直接解析，再剥 markdown 代码块，最后用正则兜底。"""
        if not raw:
            return None

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        import re
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if m:
            try:
                parsed = json.loads(m.group(1).strip())
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        logger.warning(f"在线视觉模型输出无法解析为 JSON，原始输出: {raw[:200]}")
        return None


# 模块级单例（进程内复用）
_client: Optional[VisionLLMClient] = None


def get_vision_llm_client() -> VisionLLMClient:
    """获取在线视觉模型客户端单例。"""
    global _client
    if _client is None:
        _client = VisionLLMClient()
    return _client
