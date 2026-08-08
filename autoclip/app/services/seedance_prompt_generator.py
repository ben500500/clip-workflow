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


# ════════════════════════════════════════════════════════════════
# 提示词三版本：长提示词 / 短提示词 / AI提示词
# 其中「长 / 短」为固定模板，仅把 [视频文案] 替换为用户输入的文案；
# 「AI 提示词」走下方大模型生成（Seedance 七段结构，当前这套）。
# ════════════════════════════════════════════════════════════════

# 短提示词模板（固定模板，仅替换 [视频文案]，不做其它处理）
SHORT_PROMPT_TEMPLATE = (
    "生成视频：类型：古言甜宠剧情；根据文案生成10秒9:16的短剧视频：[视频文案]\n"
    "；根据文案剧情，依照你的想象力，设定合理的场景，加一些夸张的肢体语言，"
    "参考抖音热播短剧给这个视频添加中文字幕和配音"
)

# 长提示词模板（固定模板，仅替换 [视频文案]，不做其它处理）
LONG_PROMPT_TEMPLATE = (
    "类型：按需匹配当前文案题材（家庭反转/悬疑猎奇/豪门恩怨/乡土故事/亲情冲突/搞笑反转）\n"
    "硬性视频参数：严格锁定视频时长【可填10秒 /15秒】，9:16高清竖屏；全程运镜平稳无抖动，"
    "禁止频繁切镜，单镜头最低停留1.5s，反转、人物情绪特写镜头固定停留2s以上，结尾高光片段"
    "开启慢放，绝不压缩结尾情绪、不堆砌多段剧情。\n\n"
    "时间轴固定节奏（强制执行）\n"
    "方案1‑10秒版：0‑3s强冲突黄金钩子抓人；3‑7s铺垫主线剧情；7‑10s只展示结局反转+人物情绪反应，"
    "不再新增故事情节\n"
    "方案2‑15秒版：0‑3s高能钩子；3‑9s完整铺垫故事经过；9‑15s慢节奏呈现反转爆发、夸张神态肢体\n\n"
    "剧情创作要求：根据给到的短剧文案自主完善真实合理场景、简短人物对白、适配情绪的夸张肢体动作、"
    "面部神情；只推进主线，不加多余配角、无关支线、复杂冗余桥段，贴合抖音热门短剧叙事风格。\n\n"
    "配音音频规范：配音语速舒缓、吐字清晰，人声情绪跟随剧情起伏；口型、画面、旁白音频严格同步，"
    "杜绝音画错位、语速急促、配音快过画面节奏。\n\n"
    "字幕设置：启用加粗白字+黑色粗描边同步中文字幕；单条字幕展示时长≥1.5秒，字幕随配音依次弹出；"
    "禁止字幕一闪而过、多层字幕堆叠错乱。\n\n"
    "画质风格：8K超清写实画质，画面干净，无杂乱花哨特效。\n\n"
    "本次短剧文案：[视频文案]\n\n"
    "负面避坑禁止清单\n"
    "禁止剧情节奏仓促、动作潦草急促；禁止镜头闪切、频繁转场、画面晃动；禁止配音含糊、语速过快、"
    "音画不同步；禁止字幕闪逝、字幕错乱；禁止人脸畸形、画面卡顿模糊；禁止多余花里胡哨特效；"
    "禁止末尾几秒塞入大量新剧情、结尾仓促跳转镜头；禁止添加和主线无关的人物和情节"
)


# 固定模板占位符
PLACEHOLDER_VIDEO_TEXT = "[视频文案]"


def build_short_prompt(text: str) -> str:
    """根据用户文案生成「短提示词」（固定模板，仅替换 [视频文案]）。"""
    return SHORT_PROMPT_TEMPLATE.replace(PLACEHOLDER_VIDEO_TEXT, text)


def build_long_prompt(text: str) -> str:
    """根据用户文案生成「长提示词」（固定模板，仅替换 [视频文案]）。"""
    return LONG_PROMPT_TEMPLATE.replace(PLACEHOLDER_VIDEO_TEXT, text)


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
    """调用配置好的大模型生成 Seedance 提示词（仅 AI 提示词版本）。

    Args:
        text: 用户输入的短剧文案（对白/旁白原文）
        duration: 10 或 15（秒）
        params: 可选附加参数（题材/基调/角色/补充要求）
        max_retries: LLM 调用重试次数

    Returns:
        生成的提示词正文（不含 JSON 包装）
    """
    versions = generate_prompt_versions(text, duration, params, max_retries)
    return versions["ai"]


def generate_prompt_versions(
    text: str,
    duration: int = 15,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> Dict[str, str]:
    """一次生成提示词三个版本：长提示词 / 短提示词 / AI提示词。

    - 长提示词、短提示词：固定模板，仅把 [视频文案] 替换为用户输入的文案，不做其它处理；
    - AI 提示词：调用配置好的大模型按 Seedance 七段结构生成（当前这套）。

    Args:
        text: 用户输入的短剧文案（对白/旁白原文）
        duration: 10 或 15（秒）
        params: 可选附加参数（题材/基调/角色/补充要求）
        max_retries: LLM 调用重试次数

    Returns:
        {"long": 长提示词, "short": 短提示词, "ai": AI提示词}
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("短剧文案不能为空")

    # 长 / 短：固定模板直接替换占位符，无需调用大模型
    long_prompt = build_long_prompt(text)
    short_prompt = build_short_prompt(text)

    # AI：调用大模型生成（保留当前这套 Seedance 七段结构）
    template = load_seedance_template()
    if not template:
        raise RuntimeError("Seedance 提示词模板未找到，请检查 autoclip/prompt/seedance_prompt.txt")

    duration = _normalize_duration(duration)
    input_data = _build_input(text, duration, params)
    manager = get_llm_manager()
    raw = manager.call_with_retry(template, input_data, max_retries=max_retries)
    if not raw:
        raise RuntimeError("大模型返回空响应，生成 AI 提示词失败")

    # 容错：优先按 JSON 包装解析，解析失败则直接把整段文本当作提示词正文返回。
    ai_prompt = _extract_prompt_text(raw)
    # 合规收尾：确保结尾带上「侵权/违规自动改写」确认句
    ai_prompt = _ensure_compliance_footer(ai_prompt)

    return {
        "long": long_prompt,
        "short": short_prompt,
        "ai": ai_prompt,
    }


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
