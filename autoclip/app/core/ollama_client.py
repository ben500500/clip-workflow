"""
Ollama 客户端 - 本地视觉模型（MiniCPM-V 等）HTTP 调用

与 llm_manager 的在线 LLM 无关，专门服务「画面理解」链路：
抽帧后把图片 base64 发给本地 Ollama，返回结构化 JSON 描述。

特性：
- think=false（关闭推理过程，直接输出答案）
- format=json（Ollama 原生强制 JSON 输出，解决字段缺失问题）
- 超时与重试、错误静默降级（Ollama 不可用时返回 None，不影响主流程）
"""
import base64
import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Ollama 服务地址（docker-compose 内为 ollama:11434，本地开发为 localhost:11434）
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434").rstrip("/")
# 默认视觉模型（openbmb/minicpm-v4.6，Q4 量化约 1.6GB）
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "openbmb/minicpm-v4.6")
# 单次调用超时（秒）。CPU 推理单帧 8-10s，60s 足够覆盖慢速场景
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
# 最大重试次数（Ollama 首次加载模型需要时间，首次调用可能较慢）
OLLAMA_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "2"))


class OllamaClient:
    """Ollama HTTP 客户端（/api/generate，OpenAI 兼容可选）"""

    def __init__(self, host: Optional[str] = None, model: Optional[str] = None):
        self.host = (host or OLLAMA_HOST).rstrip("/")
        self.model = model or OLLAMA_MODEL

    @property
    def available(self) -> bool:
        """探测 Ollama 服务是否可用（快速健康检查）。"""
        try:
            req = urllib.request.Request(
                f"{self.host}/api/version",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return bool(data.get("version"))
        except Exception as e:
            logger.warning(f"Ollama 服务不可用（{self.host}）: {e}")
            return False

    def describe_image(self, image_bytes: bytes, prompt: str) -> Optional[Dict[str, Any]]:
        """
        发送单张图片到 Ollama 视觉模型，返回结构化 JSON。

        Args:
            image_bytes: 图片原始字节（JPEG/PNG）
            prompt: 分析提示词（要求输出 JSON）

        Returns:
            解析后的 dict；失败返回 None（调用方静默降级）。
        """
        if not image_bytes:
            return None

        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "format": "json",          # Ollama 原生强制 JSON 输出
            "think": False,            # 关闭推理过程，直接输出答案
            "options": {"temperature": 0.2},
        }

        last_err: Optional[Exception] = None
        for attempt in range(OLLAMA_MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(
                    f"{self.host}/api/generate",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode())
                raw = data.get("response", "")
                return self._parse_json(raw)
            except urllib.error.HTTPError as e:
                # 404 = 模型未拉取；500 = 服务端错误（如上下文超限）
                logger.warning(f"Ollama HTTP {e.code}（第{attempt + 1}次）: {e.reason}")
                last_err = e
            except Exception as e:
                logger.warning(f"Ollama 调用失败（第{attempt + 1}次）: {e}")
                last_err = e
            if attempt < OLLAMA_MAX_RETRIES:
                import time
                time.sleep(2 ** attempt)

        logger.error(f"Ollama 图片分析最终失败: {last_err}")
        return None

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
        """解析模型输出为 dict：先直接解析，再剥 markdown 代码块，最后用正则兜底。"""
        if not raw:
            return None

        # 1) 直接解析
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # 2) 剥 markdown 代码块 ```json ... ```
        import re
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if m:
            try:
                parsed = json.loads(m.group(1).strip())
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        # 3) 正则找第一个 { ... } 对象
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        logger.warning(f"Ollama 输出无法解析为 JSON，原始输出: {raw[:200]}")
        return None


# 模块级单例（进程内复用连接状态）
_client: Optional[OllamaClient] = None


def get_ollama_client() -> OllamaClient:
    """获取 Ollama 客户端单例。"""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client
