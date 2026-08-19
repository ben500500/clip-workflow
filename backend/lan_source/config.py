"""lan_source 配置合并加载（环境变量 + system_config 覆盖）。

设计目的：让「局域网获取剧集」配置可从系统设置页（system_config 表）热更，
无需改 .env / 重启后端。优先级：
    system_config 显式字段 > 环境变量(.env settings) > 内置默认。

system_config key = `lan_source_config`（JSON）：
    {
      "enabled": false,             # 总开关（默认关闭）
      "base_url": "http://192.168.1.163:8765",   # dupload cdn 源基础地址
      "manage_base": "",            # IAA 小程序管理平台基础地址（可选）
      "api_prefix": "",             # 剧集清单接口路径前缀（可选）
      "download_timeout": 900,      # 单集拉流整体超时（秒）
      "queue": "lan_source",        # 导入任务队列
      "default_project": "局域网导入",  # 默认入库归属项目名
      "concurrency": 2,             # 每集 HTTP 下载并发数
    }

调用方（client / downloader / service / api）统一从 settings 或注入的
LanSourceConfig 读取，避免重复解析逻辑。
"""

from dataclasses import dataclass, field
from typing import Optional

# 与 backend/app/api/config.py DEFAULT_CONFIGS 中 lan_source_config 保持一致
DEFAULT_LAN_SOURCE_CONFIG: dict = {
    "enabled": False,
    "base_url": "http://192.168.1.163:8765",
    "manage_base": "",
    "api_prefix": "",
    "download_timeout": 900,
    "queue": "lan_source",
    "default_project": "局域网导入",
    "concurrency": 2,
}


@dataclass
class LanSourceConfig:
    """局域网源合并后的配置（对外只读，不含任何密钥）。"""

    enabled: bool = False
    base_url: str = "http://192.168.1.163:8765"
    manage_base: str = ""
    api_prefix: str = ""
    download_timeout: int = 900
    queue: str = "lan_source"
    default_project: str = "局域网导入"
    concurrency: int = 2

    def __post_init__(self) -> None:
        # 统一收尾：base 去掉尾部斜杠，prefix 去掉首尾斜杠
        self.base_url = (self.base_url or "").rstrip("/")
        self.manage_base = (self.manage_base or "").rstrip("/")
        self.api_prefix = (self.api_prefix or "").strip("/")

    def to_public_dict(self) -> dict:
        """对外暴露的只读配置（供 /api/lan-source/config 使用）。"""
        return {
            "enabled": bool(self.enabled),
            "base_url": self.base_url,
            "manage_base": self.manage_base,
            "api_prefix": self.api_prefix,
            "download_timeout": self.download_timeout,
            "queue": self.queue,
            "default_project": self.default_project,
            "concurrency": self.concurrency,
        }

    def to_db_dict(self) -> dict:
        """完整的可编辑字段（含所有配置项，用于写回 system_config）。"""
        return self.to_public_dict()


def _as_bool(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on", "y")
    return False


def _as_int(value, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_lan_source_config(
    db_config: Optional[dict] = None,
    env: Optional[dict] = None,
) -> LanSourceConfig:
    """从环境变量(.env) + system_config 合并构建局域网源配置。

    Args:
        db_config: system_config.lan_source_config 的 JSON 值（可空）
        env: 配置源字典；默认取 app.config.settings（读取 .env）。
            兼容测试注入 dict / os.environ。

    优先级：db_config 显式字段 > env(.env settings) > 内置默认。
    """
    # 取环境/默认配置源
    if env is None:
        try:
            from app.config import settings
        except Exception:  # pragma: no cover
            settings = None
        env_source = settings
    else:
        env_source = env

    def _env_get(key: str):
        """从 settings 或 dict 读取，返回 None 表示未显式配置。"""
        if env_source is None:
            return None
        if isinstance(env_source, dict):
            return env_source.get(key)
        # pydantic BaseSettings 对象：仅当字段存在时返回其值
        return getattr(env_source, key, None) if hasattr(env_source, key) else None

    # 环境变量（.env）优先值，缺失时用内置默认
    env_enabled = _env_get("LAN_SOURCE_ENABLED")
    env_base_url = _env_get("LAN_SOURCE_BASE_URL")
    env_manage_base = _env_get("LAN_SOURCE_MANAGE_BASE")
    env_api_prefix = _env_get("LAN_SOURCE_API_PREFIX")
    env_download_timeout = _env_get("LAN_SOURCE_DOWNLOAD_TIMEOUT")
    env_queue = _env_get("LAN_SOURCE_QUEUE")
    env_default_project = _env_get("LAN_SOURCE_DEFAULT_PROJECT")
    env_concurrency = _env_get("LAN_SOURCE_CONCURRENCY")

    cfg = LanSourceConfig(
        enabled=_as_bool(env_enabled) if env_enabled is not None else DEFAULT_LAN_SOURCE_CONFIG["enabled"],
        base_url=(env_base_url or DEFAULT_LAN_SOURCE_CONFIG["base_url"]),
        manage_base=(env_manage_base or DEFAULT_LAN_SOURCE_CONFIG["manage_base"]),
        api_prefix=(env_api_prefix or DEFAULT_LAN_SOURCE_CONFIG["api_prefix"]),
        download_timeout=_as_int(env_download_timeout, DEFAULT_LAN_SOURCE_CONFIG["download_timeout"]),
        queue=(env_queue or DEFAULT_LAN_SOURCE_CONFIG["queue"]),
        default_project=(env_default_project or DEFAULT_LAN_SOURCE_CONFIG["default_project"]),
        concurrency=_as_int(env_concurrency, DEFAULT_LAN_SOURCE_CONFIG["concurrency"]),
    )

    # system_config 显式覆盖（仅覆盖已显式给出的字段）
    db = db_config or {}
    if "enabled" in db:
        cfg.enabled = _as_bool(db.get("enabled"))
    if db.get("base_url"):
        cfg.base_url = str(db.get("base_url"))
    if db.get("manage_base"):
        cfg.manage_base = str(db.get("manage_base"))
    if db.get("api_prefix"):
        cfg.api_prefix = str(db.get("api_prefix"))
    if "download_timeout" in db:
        cfg.download_timeout = _as_int(db.get("download_timeout"), cfg.download_timeout)
    if db.get("queue"):
        cfg.queue = str(db.get("queue"))
    if db.get("default_project"):
        cfg.default_project = str(db.get("default_project"))
    if "concurrency" in db:
        cfg.concurrency = _as_int(db.get("concurrency"), cfg.concurrency)

    # 重新归一化（db 覆盖的 base/prefix 也可能带斜杠）
    cfg.base_url = (cfg.base_url or "").rstrip("/")
    cfg.manage_base = (cfg.manage_base or "").rstrip("/")
    cfg.api_prefix = (cfg.api_prefix or "").strip("/")

    return cfg
