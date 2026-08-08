"""
短剧发布素材生成器

依据用户需求（ISSUE #34）实现「短剧发布素材」自动产出：
- 输入：短剧剧情梗概 / 生成好的 Seedance 提示词 / 短剧标题
- 输出：结构化发布素材
  1. 短标题（8-18 字，反差悬念，用作封面标题）
  2. 三款视频配文（悬念钩子 / 精简爆款 / 情绪爽文，用户任选其一）
  3. 成套话题标签（通用短剧 / 剧情垂直 / 长尾搜流，共 6-8 个）
  4. 三条置顶互动神评（调侃 / 感慨 / 脑洞，带动评论互动）
- 模型：复用 autoclip 的 LLM 管理器（与选点 / Seedance 提示词生成同一套
  DASHSCOPE_API_KEY / API_MODEL_NAME 配置），无需额外配置。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.llm_manager import get_llm_manager

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PUBLISH_MATERIAL_FILE = APP_DIR / "prompt" / "publish_material.txt"


def load_publish_material_template() -> str:
    """加载短剧发布素材生成模板（角色设定）。"""
    if PUBLISH_MATERIAL_FILE.exists():
        return PUBLISH_MATERIAL_FILE.read_text(encoding="utf-8")
    logger.warning("Publish material template not found: %s", PUBLISH_MATERIAL_FILE)
    return ""


def _build_input(story: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把前端传入参数组装成模型输入。"""
    p = params or {}
    return {
        "剧情梗概": story,
        "短剧标题（可选）": p.get("title") or "",
        "题材": p.get("theme") or "",
        "基调": p.get("tone") or "",
        "发布平台": p.get("platform") or "抖音、视频号",
        "补充要求": p.get("extra_requirements") or "",
        "合规要求": "不得出现真实人名、地名、机构名、品牌名，一律使用代称；不涉及真实人物、真实事件与敏感内容。",
    }


def generate_publish_material(
    story: str,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """调用配置好的大模型生成短剧发布素材。

    Args:
        story: 短剧剧情梗概（或已生成的 Seedance 提示词 / 短剧标题）
        params: 可选附加参数（title/theme/tone/platform/extra_requirements）
        max_retries: LLM 调用重试次数

    Returns:
        结构化发布素材 dict：
        {
          "short_title": str,
          "captions": {"suspense_hook": str, "concise_viral": str, "emotional": str},
          "tags": {"通用短剧": [...], "剧情垂直": [...], "长尾搜流": [...]},
          "comments": [{"type": str, "content": str}, ...]
        }
    """
    template = load_publish_material_template()
    if not template:
        raise RuntimeError("发布素材模板未找到，请检查 autoclip/prompt/publish_material.txt")

    input_data = _build_input(story, params)
    manager = get_llm_manager()
    raw = manager.call_with_retry(template, input_data, max_retries=max_retries)
    if not raw:
        raise RuntimeError("大模型返回空响应，生成发布素材失败")

    return _parse_material(raw)


def _parse_material(raw: str) -> Dict[str, Any]:
    """从模型原始响应中解析发布素材 JSON。

    兼容三种返回形态：
    1. 纯 JSON：直接 json.loads
    2. markdown 代码块包裹的 JSON：去掉 ```json ... ``` 围栏后解析
    3. 文本中内嵌 JSON：截取首个 { ... } 区间解析
    """
    stripped = raw.strip()

    # 去掉 markdown 代码块围栏
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    # 直接解析
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return _normalize_material(data)
    except (json.JSONDecodeError, ValueError):
        pass

    # 文本中截取 JSON 区间
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(stripped[start:end + 1])
            if isinstance(data, dict):
                return _normalize_material(data)
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("发布素材解析失败，返回原始文本占位结构")
    return {"raw": stripped}


def _normalize_material(data: Dict[str, Any]) -> Dict[str, Any]:
    """归一化模型返回的发布素材结构，保证前端字段完整。"""
    captions = data.get("captions") or {}
    if not isinstance(captions, dict):
        captions = {}

    tags = data.get("tags") or {}
    if not isinstance(tags, dict):
        tags = {}

    comments = data.get("comments") or []
    if not isinstance(comments, list):
        comments = []

    return {
        "short_title": str(data.get("short_title") or "").strip(),
        "captions": {
            "suspense_hook": str(captions.get("suspense_hook") or captions.get("version_a") or "").strip(),
            "concise_viral": str(captions.get("concise_viral") or captions.get("version_b") or "").strip(),
            "emotional": str(captions.get("emotional") or captions.get("version_c") or "").strip(),
        },
        "tags": {str(k): v if isinstance(v, list) else [] for k, v in tags.items()},
        "comments": [
            {
                "type": str(c.get("type") or ""),
                "content": str(c.get("content") or ""),
            }
            for c in comments
            if isinstance(c, dict)
        ],
    }
