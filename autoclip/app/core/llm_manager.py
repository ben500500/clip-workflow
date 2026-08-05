"""
LLM管理器 - 统一管理多个模型提供商（精简版，去除桌面端配置同步依赖）

保留真实 DashScope 调用能力：
- 从 DASHSCOPE_API_KEY 环境变量读取密钥（未配置时回退 settings.json）
- 指数退避重试 3 次（call_with_retry）
- 默认 model = qwen-plus
"""
import json
import logging
import os
from typing import Dict, Any, Optional, List
from pathlib import Path

from .llm_providers import (
    LLMProvider, LLMProviderFactory, ProviderType,
    ModelInfo, LLMResponse
)

logger = logging.getLogger(__name__)


class LLMManager:
    """LLM管理器"""

    def __init__(self, settings_file: Optional[Path] = None):
        self.settings_file = settings_file or self._get_default_settings_file()
        self.current_provider: Optional[LLMProvider] = None
        self.settings = self._load_settings()
        self._initialize_provider()

    def _get_default_settings_file(self) -> Path:
        """获取默认设置文件路径"""
        app_dir = os.getenv("AUTOCLIP_APP_DIR")
        if app_dir:
            return Path(app_dir) / "settings.json"
        default_app_dir = Path.home() / "Library" / "Application Support" / "AutoClip"
        return default_app_dir / "settings.json"

    def _load_settings(self) -> Dict[str, Any]:
        """加载设置"""
        env_model_name = os.getenv("API_MODEL_NAME", "")
        if env_model_name:
            logger.info(f"模型名来自环境变量 API_MODEL_NAME={env_model_name}")
        default_model_name = env_model_name or "qwen-plus"

        default_settings = {
            "llm_provider": "dashscope",
            "dashscope_api_key": "",
            "openai_api_key": "",
            "gemini_api_key": "",
            "siliconflow_api_key": "",
            "model_name": default_model_name,
            "chunk_size": 5000,
            "min_score_threshold": 0.7,
            "max_clips_per_collection": 5,
        }

        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    saved_settings = json.load(f)
                if "api" in saved_settings and "api_keys" in saved_settings["api"]:
                    api_keys = saved_settings["api"]["api_keys"]
                    default_settings.update({
                        "dashscope_api_key": api_keys.get("dashscope", ""),
                        "openai_api_key": api_keys.get("openai", ""),
                        "gemini_api_key": api_keys.get("gemini", ""),
                        "siliconflow_api_key": api_keys.get("siliconflow", ""),
                        "model_name": saved_settings["api"].get("api_model") or default_model_name,
                    })
                else:
                    if not saved_settings.get("model_name"):
                        saved_settings["model_name"] = default_model_name
                    default_settings.update(saved_settings)
            except Exception as e:
                logger.warning(f"加载设置文件失败: {e}")

        return default_settings

    def _save_settings(self):
        """保存设置"""
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
            raise

    def _initialize_provider(self):
        """初始化当前提供商"""
        try:
            provider_type = ProviderType(self.settings.get("llm_provider", "dashscope"))
            model_name = self.settings.get("model_name", "qwen-plus")
            api_key = self._get_api_key_for_provider(provider_type)

            if api_key:
                self.current_provider = LLMProviderFactory.create_provider(
                    provider_type, api_key, model_name
                )
                logger.info(f"已初始化{provider_type.value}提供商，模型: {model_name}")
            else:
                logger.warning(f"未找到{provider_type.value}的API密钥")
        except Exception as e:
            logger.error(f"初始化提供商失败: {e}")
            self.current_provider = None

    def _get_api_key_for_provider(self, provider_type: ProviderType) -> Optional[str]:
        """获取指定提供商的API密钥"""
        key_mapping = {
            ProviderType.DASHSCOPE: "dashscope_api_key",
            ProviderType.OPENAI: "openai_api_key",
            ProviderType.GEMINI: "gemini_api_key",
            ProviderType.SILICONFLOW: "siliconflow_api_key",
        }
        key_name = key_mapping.get(provider_type)
        api_key = self.settings.get(key_name, "") if key_name else ""

        # 容器部署兜底：未配置时回退到环境变量
        if not api_key:
            env_keys = {
                ProviderType.DASHSCOPE: ("DASHSCOPE_API_KEY", "API_DASHSCOPE_API_KEY"),
                ProviderType.OPENAI: ("OPENAI_API_KEY",),
                ProviderType.GEMINI: ("GEMINI_API_KEY",),
                ProviderType.SILICONFLOW: ("SILICONFLOW_API_KEY",),
            }
            for env_name in env_keys.get(provider_type, ()):
                api_key = os.getenv(env_name, "")
                if api_key:
                    logger.info(f"{provider_type.value} API密钥来自环境变量 {env_name}")
                    break

        return api_key or None

    def update_settings(self, new_settings: Dict[str, Any]):
        """更新设置"""
        self.settings.update(new_settings)
        self._save_settings()
        self._initialize_provider()

    def set_provider(self, provider_type: ProviderType, api_key: str, model_name: str):
        """设置提供商"""
        try:
            provider_settings = {
                "llm_provider": provider_type.value,
                "model_name": model_name,
            }
            key_mapping = {
                ProviderType.DASHSCOPE: "dashscope_api_key",
                ProviderType.OPENAI: "openai_api_key",
                ProviderType.GEMINI: "gemini_api_key",
                ProviderType.SILICONFLOW: "siliconflow_api_key",
            }
            key_name = key_mapping.get(provider_type)
            if key_name:
                provider_settings[key_name] = api_key
            self.update_settings(provider_settings)
            self.current_provider = LLMProviderFactory.create_provider(
                provider_type, api_key, model_name
            )
            logger.info(f"已切换到{provider_type.value}提供商，模型: {model_name}")
        except Exception as e:
            logger.error(f"设置提供商失败: {e}")
            raise

    def call(self, prompt: str, input_data: Any = None, **kwargs) -> str:
        """调用LLM"""
        if not self.current_provider:
            raise ValueError("未配置LLM提供商，请在设置页面配置API密钥")
        try:
            response = self.current_provider.call(prompt, input_data, **kwargs)
            return response.content
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise

    def call_with_retry(self, prompt: str, input_data: Any = None, max_retries: int = 3, **kwargs) -> str:
        """带重试机制的LLM调用（指数退避）"""
        for attempt in range(max_retries):
            try:
                return self.call(prompt, input_data, **kwargs)
            except ValueError:  # API Key 或参数错误，不重试
                raise
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"LLM调用在{max_retries}次重试后彻底失败。")
                    raise
                logger.warning(f"第{attempt + 1}次调用失败，准备重试: {str(e)}")
                import time
                time.sleep(2 ** attempt)  # 指数退避
        return ""

    def test_provider_connection(self, provider_type: ProviderType, api_key: str, model_name: str) -> bool:
        """测试提供商连接"""
        try:
            provider = LLMProviderFactory.create_provider(provider_type, api_key, model_name)
            return provider.test_connection()
        except Exception as e:
            logger.error(f"测试{provider_type.value}连接失败: {e}")
            return False

    def get_current_provider_info(self) -> Dict[str, Any]:
        """获取当前提供商信息"""
        if not self.current_provider:
            return {"provider": None, "model": None, "available": False}
        provider_type = ProviderType(self.settings.get("llm_provider", "dashscope"))
        model_name = self.settings.get("model_name", "qwen-plus")
        return {
            "provider": provider_type.value,
            "model": model_name,
            "available": True,
            "display_name": self._get_provider_display_name(provider_type),
        }

    def _get_provider_display_name(self, provider_type: ProviderType) -> str:
        display_names = {
            ProviderType.DASHSCOPE: "阿里通义千问",
            ProviderType.OPENAI: "OpenAI",
            ProviderType.GEMINI: "Google Gemini",
            ProviderType.SILICONFLOW: "硅基流动",
        }
        return display_names.get(provider_type, provider_type.value)

    def get_all_available_models(self) -> Dict[str, List[Dict[str, Any]]]:
        all_models = LLMProviderFactory.get_all_available_models()
        result = {}
        for provider_type, models in all_models.items():
            result[provider_type.value] = [
                {
                    "name": model.name,
                    "display_name": model.display_name,
                    "max_tokens": model.max_tokens,
                    "description": model.description,
                }
                for model in models
            ]
        return result

    def parse_json_response(self, response: str) -> Any:
        """解析JSON响应（保持与原LLMClient的兼容性）"""
        if not self.current_provider:
            raise ValueError("未配置LLM提供商")
        from ..utils.llm_client import LLMClient
        return LLMClient().parse_json_response(response)


# 全局LLM管理器实例
_llm_manager: Optional[LLMManager] = None


def get_llm_manager() -> LLMManager:
    """获取全局LLM管理器实例"""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
    return _llm_manager


def initialize_llm_manager(settings_file: Optional[Path] = None) -> LLMManager:
    """初始化LLM管理器"""
    global _llm_manager
    _llm_manager = LLMManager(settings_file)
    return _llm_manager
