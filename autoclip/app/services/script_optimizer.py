"""短剧文案 AI 优化器（短片制作「AI 优化文案」按钮）。

用户在「短剧文案」输入框上方点击「AI 优化」后，
调用 autoclip 配置的大模型（与选点 / Seedance 提示词生成 / 发布素材
同一套 DASHSCOPE_API_KEY / API_MODEL_NAME 配置）对原始文案做优化改写：
- 保留主线、人物关系与核心反转，不改变故事走向
- 增强冲突 / 悬念 / 情绪张力，开头 3 秒强钩子
- 对白更口语化、有冲击力，精简冗余、节奏紧凑
- 保持「画外音旁白 / 对白」标注格式，人名地名一律用代称
- 直接输出优化后的文案正文（便于后续直接生成提示词）
"""
import json
import logging
from typing import Any, Dict, Optional

from ..core.llm_manager import get_llm_manager

logger = logging.getLogger(__name__)

# 优化改写角色设定（system prompt）
OPTIMIZE_SYSTEM_PROMPT = """你是资深短剧编剧，擅长把普通文案改写成适合竖屏短剧的高能剧本。

请对用户输入的短剧文案进行优化改写，严格遵循以下要求：
1. 保留原有剧情主线、人物关系和核心反转，不改变故事走向。
2. 增强冲突、悬念和情绪张力，开头 3 秒要有强钩子（冲突或悬念直接砸出来）。
3. 优化对白：更口语化、更有冲击力、更贴合人物身份与情绪。
4. 精简冗余描述，节奏更紧凑，适合 10-30 秒竖屏短剧。
5. 保持标注格式不变：
   - 对白用【角色名】标注，如：【女主】你凭什么开除我！
   - 旁白用（画外音旁白）标注，如：（画外音旁白）她不知道，眼前这个男人，就是当年救她的那个人。
6. 人名、地名、机构名、品牌名一律用代称（如：女主、男主、某公司、某都市），全片保持一致。
7. 直接输出优化后的文案正文，不要任何解释、前缀或 Markdown 代码块。
8. 字数控制在 150~500 字之间，足够支撑 10~30 秒竖屏短剧。"""


def _build_input(text: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把前端传入参数组装成模型输入。"""
    p = params or {}
    return {
        "待优化文案": text,
        "题材（可选）": p.get("theme") or "",
        "基调（可选）": p.get("tone") or "",
        "补充要求（可选）": p.get("extra_requirements") or "",
    }


def optimize_script_text(
    text: str,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> str:
    """调用配置好的大模型优化短剧文案。

    Args:
        text: 用户输入的原始短剧文案
        params: 可选附加参数（theme/tone/extra_requirements）
        max_retries: LLM 调用重试次数

    Returns:
        优化后的文案正文（纯文本）
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("短剧文案不能为空")

    input_data = _build_input(text, params)
    manager = get_llm_manager()
    raw = manager.call_with_retry(
        OPTIMIZE_SYSTEM_PROMPT,
        input_data,
        max_retries=max_retries,
    )
    if not raw:
        raise RuntimeError("大模型返回空响应，文案优化失败")

    return _clean_output(raw)


def _clean_output(raw: str) -> str:
    """清理模型输出：去掉 Markdown 代码块围栏与多余解释。"""
    stripped = (raw or "").strip()

    # 去掉 markdown 代码块围栏
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    # 若模型用 JSON 包装，则提取文案字段
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                for key in ("optimized_text", "text", "content", "文案"):
                    if data.get(key):
                        return str(data[key]).strip()
        except (json.JSONDecodeError, ValueError):
            pass

    return stripped
