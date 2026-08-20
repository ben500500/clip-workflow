"""dupload 配置合并加载（环境变量 + system_config 覆盖）。

设计目的：让「推送到下载平台」配置可从系统设置页（system_config 表）热更，
无需改 .env / 重启后端。优先级：
    system_config 显式字段 > 环境变量(.env settings) > 内置默认。

system_config key = `dupload_config`（JSON）：
    {
      "enabled": false,          # 总开关（默认关闭）
      "base_url": "http://192.168.1.21:8800",  # dupload 服务基础地址
      "import_path": "/api/dupload/tasks",     # 批量导入接口路径
      "action": "only_download", # 动作：only_download(仅下载)/upload_miniapp(上传小程序)
      "share_url_field": "material_link",      # 剧目模型里素材链接(shareUrl)的字段名
      "request_timeout": 30,     # 单次请求超时（秒）
      "auth_headers": {},        # 附加鉴权请求头（JSON，可放 Authorization/Cookie 等）
    }

调用方（client / api）统一从 settings 或注入的 DuploadConfig 读取。
"""

from dataclasses import dataclass, field
from typing import Optional

# 与 backend/app/api/config.py DEFAULT_CONFIGS 中 dupload_config 保持一致
DEFAULT_DUPLOAD_CONFIG: dict = {
    "enabled": False,
    "base_url": "http://192.168.1.21:8800",
    "import_path": "/api/dupload/tasks",
    "action": "only_download",
    "share_url_field": "material_link",
    "request_timeout": 30,
    "auth_headers": {},
}


@dataclass
class DuploadConfig:
    """dupload 合并后的配置（对外只读，不含 auth_headers 明文）。"""

    enabled: bool = False
    base_url: str = "http://192.168.1.21:8800"
    import_path: str = "/api/dupload/tasks"
    action: str = "only_download"
    share_url_field: str = "material_link"
    request_timeout: int = 30
    auth_headers: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or "").rstrip("/")
        if not self.import_path.startswith("/"):
            self.import_path = f"/{self.import_path}"

    def to_public_dict(self) -> dict:
        """对外暴露的只读配置（供 /api/dupload/config 使用，不含 auth_headers 明文）。"""
        return {
            "enabled": bool(self.enabled),
            "base_url": self.base_url,
            "import_path": self.import_path,
            "action": self.action,
            "share_url_field": self.share_url_field,
            "request_timeout": self.request_timeout,
            # 只暴露是否已配置鉴权头，不暴露其明文
            "has_auth_headers": bool(self.auth_headers),
        }


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


def load_dupload_config(
    db_config: Optional[dict] = None,
    env: Optional[dict] = None,
) -> DuploadConfig:
    """从环境变量(.env) + system_config 合并���建 dupload 配置。

    Args:
        db_config: system_config.dupload_config 的 JSON 值（可空）
        env: 配置源字典；默认取 app.config.settings（读取 .env）。
            兼容测试注入 dict / os.environ。

    优先级：db_config 显式字段 > env(.env settings) > 内置默认。
    """
    if env is None:
        try:
            from app.config import settings
        except Exception:  # pragma: no cover
            settings = None
        env_source = settings
    else:
        env_source = env

    def _env_get(key: str):
        if env_source is None:
            return None
        if isinstance(env_source, dict):
            return env_source.get(key)
        return getattr(env_source, key, None) if hasattr(env_source, key) else None

    env_enabled = _env_get("DUPLOAD_ENABLED")
    env_base_url = _env_get("DUPLOAD_BASE_URL")
    env_import_path = _env_get("DUPLOAD_IMPORT_PATH")
    env_action = _env_get("DUPLOAD_ACTION")
    env_share_url_field = _env_get("DUPLOAD_SHARE_URL_FIELD")
    env_request_timeout = _env_get("DUPLOAD_REQUEST_TIMEOUT")

    cfg = DuploadConfig(
        enabled=_as_bool(env_enabled) if env_enabled is not None else DEFAULT_DUPLOAD_CONFIG["enabled"],
        base_url=(env_base_url or DEFAULT_DUPLOAD_CONFIG["base_url"]),
        import_path=(env_import_path or DEFAULT_DUPLOAD_CONFIG["import_path"]),
        action=(env_action or DEFAULT_DUPLOAD_CONFIG["action"]),
        share_url_field=(env_share_url_field or DEFAULT_DUPLOAD_CONFIG["share_url_field"]),
        request_timeout=_as_int(env_request_timeout, DEFAULT_DUPLOAD_CONFIG["request_timeout"]),
    )

    # system_config 显式覆盖（仅覆盖已显式给出的字段）
    db = db_config or {}
    if "enabled" in db:
        cfg.enabled = _as_bool(db.get("enabled"))
    if db.get("base_url"):
        cfg.base_url = str(db.get("base_url"))
    if db.get("import_path"):
        cfg.import_path = str(db.get("import_path"))
    if db.get("action"):
        cfg.action = str(db.get("action"))
    if db.get("share_url_field"):
        cfg.share_url_field = str(db.get("share_url_field"))
    if "request_timeout" in db:
        cfg.request_timeout = _as_int(db.get("request_timeout"), cfg.request_timeout)
    if db.get("auth_headers") is not None:
        hdrs = db.get("auth_headers")
        cfg.auth_headers = hdrs if isinstance(hdrs, dict) else {}

    # 重新归一化
    cfg.base_url = (cfg.base_url or "").rstrip("/")
    if not cfg.import_path.startswith("/"):
        cfg.import_path = f"/{cfg.import_path}"

    return cfg
