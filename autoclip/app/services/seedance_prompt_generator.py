"""
Seedance 短剧视频提示词生成器

依据《Seedance短剧视频生成提示词模板-需求文档》实现：
- 输入：短剧文案（对白/旁白原文）、时长（10s/15s）、题材、基调、角色信息（可选）
- 输出：按 7 段固定结构（题材基调→故事→场景人物→镜头执行→音频→画面风格→性别声明）
  组装好的 Seedance 提示词正文
- 模型：复用 autoclip 的 LLM 管理器（LLMManager，读取 autoclip 中配置的模型/API Key），
  与选点流水线使用同一套配置（DASHSCOPE_API_KEY / API_MODEL_NAME / 提供商设置）
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.llm_manager import get_llm_manager

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
SEEDANCE_PROMPT_FILE = APP_DIR / "prompt" / "seedance_prompt.txt"


def load_seedance_template() -> str:
    """加载 Seedance 提示词生成模板（角色设定）。"""
    if SEEDANCE_PROMPT_FILE.exists():
        return SEEDANCE_PROMPT_FILE.read_text(encoding="utf-8")
    logger.warning("Seedance prompt template not found: %s", SEEDANCE_PROMPT_FILE)
    return ""


def _build_input(text: str, duration: int, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把前端传入参数组装成模型输入。"""
    p = params or {}
    return {
        "text": text,
        "duration": duration,
        "题材": p.get("theme") or "现代都市情感",
        "基调": p.get("tone") or "先压抑后爽快",
        "角色": p.get("characters") or "",
        "补充要求": p.get("extra_requirements") or "",
        "合规要求": "全片禁止出现真实人名、地名、机构名、品牌名，一律使用代称；"
        "用户文案中的专有名词须同步替换为代称后再锁定为对白/旁白原文。",
    }


def generate_seedance_prompt(
    text: str,
    duration: int = 15,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> str:
    """调用配置好的大模型生成 Seedance 提示词。

    Args:
        text: 用户输入的短剧文案（对白/旁白原文）
        duration: 10 或 15（秒）
        params: 可选附加参数（题材/基调/角色/补充要求）
        max_retries: LLM 调用重试次数

    Returns:
        生成的提示词正文（不含 JSON 包装）
    """
    template = load_seedance_template()
    if not template:
        raise RuntimeError("Seedance 提示词模板未找到，请检查 autoclip/prompt/seedance_prompt.txt")

    duration = _normalize_duration(duration)

    input_data = _build_input(text, duration, params)
    manager = get_llm_manager()
    raw = manager.call_with_retry(template, input_data, max_retries=max_retries)
    if not raw:
        raise RuntimeError("大模型返回空响应，生成提示词失败")

    # 容错：优先按 JSON 包装解析（model_config 可能要求返回 JSON），
    # 解析失败则直接把整段文本当作提示词正文返回。
    prompt = _extract_prompt_text(raw)

    # 合规收尾：确保结尾带上「侵权/违规自动改写」确认句
    return _ensure_compliance_footer(prompt)


def _normalize_duration(duration: int) -> int:
    """时长归一化：支持 10s / 15s 及任意自定义秒数。

    返回 3~300 秒内的整数（超出范围回退默认 15s），
    供模板中的 {duration} 占位符与镜头分配使用。
    """
    try:
        d = int(duration)
    except (TypeError, ValueError):
        return 15
    if d < 3 or d > 300:
        return 15
    return d


# 合规收尾确认句（固定追加在提示词末尾）
COMPLIANCE_FOOTER = (
    "⚠️ 合规说明：如生成的提示词中出现任何侵权或违规内容"
    "（如真实人名、地名、机构、品牌等），请直接帮我改写为代称或合规表述，"
    "并在改写后发我确认。"
)


def _ensure_compliance_footer(prompt: str) -> str:
    """在提示词末尾追加「侵权/违规自动改写并发我确认」确认句（幂等）。"""
    prompt = (prompt or "").strip()
    if not prompt:
        return prompt
    if COMPLIANCE_FOOTER in prompt:
        return prompt
    return f"{prompt}\n\n{COMPLIANCE_FOOTER}"


def _extract_prompt_text(raw: str) -> str:
    """从模型原始响应中提取提示词正文。

    兼容两种返回形态：
    1. 纯文本：直接作为提示词正文
    2. JSON 包装：{"prompt": "..."} 或 {"prompt_text": "..."} 或 {"content": "..."}
    """
    stripped = raw.strip()
    if stripped.startswith("```"):
        # 去掉 markdown 代码块围栏
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            for key in ("prompt", "prompt_text", "content", "text"):
                if data.get(key):
                    return str(data[key]).strip()
            # 字典但无已知 key：把字段按固定顺序拼接
            return _dict_to_prompt(data)
    except (json.JSONDecodeError, ValueError):
        pass
    return stripped


def _dict_to_prompt(data: Dict[str, Any]) -> str:
    """当模型返回的是字段字典（非约定 key）时，按模板 7 段顺序拼接。"""
    sections = [
        ("①题材基调", data.get("题材基调") or data.get("题材")),
        ("②故事", data.get("故事")),
        ("③场景与人物", data.get("场景与人物") or data.get("场景")),
        ("④镜头执行", data.get("镜头执行") or data.get("镜头")),
        ("⑤音频", data.get("音频")),
        ("⑥画面风格", data.get("画面风格")),
        ("⑦性别声明", data.get("性别声明")),
    ]
    lines = []
    for title, content in sections:
        if content:
            lines.append(f"{title}：\n{content}")
    return "\n\n".join(lines)
