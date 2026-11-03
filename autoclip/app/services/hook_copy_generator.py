"""钩子文案生成器（素材库 P0）

职责边界（和 CodeBuddy 的分工写死在这里，别互相覆盖）：
- **本文件只管机制**：输入组装、调用 LLM 管理器、解析与归一化输出结构。
- **`app/prompt/hook_copy.txt` / `hook_expand.txt` 的文案规则由 CodeBuddy 维护**，
  权威口径是 NAS《/Volumes/panda/Drama/共享配置/文档/豆包文案生成模板与规则.md》。
  本仓库里这两个 .txt 只是**能跑通链路的最小占位版**，不是最终规则。

模型：复用 autoclip 的 LLM 管理器（DASHSCOPE_API_KEY / API_MODEL_NAME），
与选点 / Seedance 提示词 / 发布素材同一套配置，不新增凭证。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.llm_manager import get_llm_manager

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
HOOK_COPY_FILE = APP_DIR / "prompt" / "hook_copy.txt"
HOOK_EXPAND_FILE = APP_DIR / "prompt" / "hook_expand.txt"

# 候选风格（与后端 asset_models.HOOK_STYLES 同一套取值）
STYLE_QUESTION = "question"
STYLE_STATEMENT = "statement"
STYLE_DIALOGUE = "dialogue"
DEFAULT_STYLES = (STYLE_QUESTION, STYLE_STATEMENT, STYLE_DIALOGUE)


def _load(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("Hook copy template not found: %s", path)
    return ""


def load_hook_copy_template() -> str:
    """钩子文案（概要文案）生成模板。"""
    return _load(HOOK_COPY_FILE)


def load_hook_expand_template() -> str:
    """钩子文案 → 可投豆包完整提示词的展开模板。"""
    return _load(HOOK_EXPAND_FILE)


def _build_generate_input(script: str, count: int, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    p = params or {}
    return {
        "反推详规（视频脚本，唯一事实来源）": script,
        "候选条数": int(count),
        "候选风格": list(DEFAULT_STYLES[: max(1, int(count))]),
        "素材标题（可选）": p.get("title") or "",
        "来源平台（可选）": p.get("platform") or "",
        "补充要求": p.get("extra_requirements") or "",
        "合规要求": p.get("compliance")
        or "不得出现真实人名、地名、机构名、品牌名，一律使用代称；不涉及真实人物、真实事件与敏感内容。",
        "硬性形态要求": "每条一句话到三句话；首句必须是需要悬念；含标点不超过 80 字；不得以逗号/顿号结尾。",
    }


def generate_hook_candidates(
    script: str,
    count: int = 3,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """把反推详规压成 N 条候选钩子文案（概要文案）。

    Returns:
        {"candidates": [{"seq","text","style_tag","formula_tag","is_recommended"}...],
         "raw": 原始文本（解析失败时兜底）}
    """
    template = load_hook_copy_template()
    if not template:
        raise RuntimeError("钩子文案模板未找到，请检查 autoclip/app/prompt/hook_copy.txt")

    manager = get_llm_manager()
    raw = manager.call_with_retry(template, _build_generate_input(script, count, params), max_retries=max_retries)
    if not raw:
        raise RuntimeError("大模型返回空响应，生成钩子文案失败")
    return _parse_candidates(raw, count)


def expand_hook_copy(
    hook_copy: str,
    seq: int = 1,
    total: int = 1,
    variant_basis: str = "",
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """过审钩子文案 → 一条可投豆包的完整提示词（N 的差异化由 variant_basis 指定）。

    权威展开规则在 NAS 文档里，模板 `hook_expand.txt` 由 CodeBuddy 对齐后维护。
    """
    template = load_hook_expand_template()
    if not template:
        raise RuntimeError("提示词展开模板未找到，请检查 autoclip/app/prompt/hook_expand.txt")

    p = params or {}
    input_data = {
        "过审钩子文案（必须原样出现在产物里，不得改写）": hook_copy,
        "本条序号": f"{int(seq)}/{int(total)}",
        "与同批其它条的差异来源": variant_basis or "",
        "素材编号": p.get("asset_code") or "",
        "来源平台": p.get("platform") or "",
        "目标时长（秒）": p.get("duration") or "",
        "合规要求": p.get("compliance")
        or "不得出现真实人名、地名、机构名、品牌名，一律使用代称。",
    }
    manager = get_llm_manager()
    raw = manager.call_with_retry(template, input_data, max_retries=max_retries)
    if not raw:
        raise RuntimeError("大模型返回空响应，展开豆包提示词失败")
    return _parse_expand(raw, hook_copy)


# ─────────────────────────  解析  ─────────────────────────


def _strip_fence(stripped: str) -> str:
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _loads_object(stripped: str) -> Optional[dict]:
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(stripped[start:end + 1])
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _parse_candidates(raw: str, count: int) -> Dict[str, Any]:
    """解析候选列表。兼容 {"candidates":[...]} / {"文案":[...]} / 裸数组 / 逐行文本。"""
    stripped = _strip_fence(raw.strip())
    data = _loads_object(stripped)
    items: List[Any] = []
    if data:
        for key in ("candidates", "钩子文案", "文案", "items", "list"):
            value = data.get(key)
            if isinstance(value, list):
                items = value
                break
    if not items and stripped.lstrip().startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                items = parsed
        except (json.JSONDecodeError, ValueError):
            items = []

    candidates: List[Dict[str, Any]] = []
    for idx, item in enumerate(items[: max(1, int(count))], start=1):
        if isinstance(item, str):
            text = item.strip()
            entry: Dict[str, Any] = {"text": text}
        elif isinstance(item, dict):
            entry = dict(item)
            text = str(entry.get("text") or entry.get("文案") or entry.get("content") or "").strip()
        else:
            continue
        if not text:
            continue
        candidates.append({
            "seq": int(entry.get("seq") or idx),
            "text": text,
            "style_tag": str(entry.get("style_tag") or entry.get("风格") or "").strip() or None,
            "formula_tag": str(entry.get("formula_tag") or entry.get("公式") or "").strip() or None,
            "is_recommended": bool(entry.get("is_recommended") or entry.get("推荐")),
        })

    if not candidates:
        # 兜底：模型没按结构返回时，按行切（每行一条候选），仍交后端做形态校验
        lines = [l.strip("-—、0123456789. )） ").strip() for l in stripped.splitlines()]
        for idx, line in enumerate([l for l in lines if l][: max(1, int(count))], start=1):
            candidates.append({"seq": idx, "text": line, "style_tag": None, "formula_tag": None, "is_recommended": idx == 1})

    if not any(c["is_recommended"] for c in candidates) and candidates:
        candidates[0]["is_recommended"] = True
    return {"candidates": candidates, "raw": stripped if not data else None}


def _parse_expand(raw: str, hook_copy: str) -> Dict[str, Any]:
    """解析展开产物：project_title / prompt_text / video_titles。"""
    stripped = _strip_fence(raw.strip())
    data = _loads_object(stripped)
    if data:
        prompt_text = str(
            data.get("prompt_text") or data.get("提示词") or data.get("视频提示词") or ""
        ).strip()
        titles = data.get("video_titles") or data.get("推荐标题") or []
        if not isinstance(titles, list):
            titles = []
        return {
            "project_title": str(data.get("project_title") or data.get("项目标题") or "").strip() or None,
            "prompt_text": prompt_text or None,
            "video_titles": [str(t).strip() for t in titles if str(t).strip()][:10],
        }
    # 非 JSON：整段当提示词，标题行取第一行
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    return {
        "project_title": first_line[:300] or None,
        "prompt_text": stripped or None,
        "video_titles": [],
        "note": "未按 JSON 结构返回，已整段作为提示词",
    }
