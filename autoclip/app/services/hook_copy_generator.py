"""钩子文案生成器（素材库 P0）

职责边界：
- **本文件只管机制**：输入组装、调用 LLM 管理器、解析与归一化输出结构。
  模板里点名的输入项（钩子编号、剧名全称、剧名缩写、推荐标题条数 K、角色卡有无）
  必须由这里透传——少一个，模板就只能让模型编一个。
- **`app/prompt/hook_copy.txt` / `hook_expand.txt` 是文案规则**，11-03 已按 NAS
  《/Volumes/panda/Drama/共享配置/豆包文案生成模板与规则.md》**11-02 版**对齐重写
  （骨架逐行、三处带编号、1020 起取消项目标题行、恒 10.08s 只能按 10 秒版写、
  推荐标题 K＝号数且各号同钩同标题）。模板里点名的判据与
  `asset_service.check_copy_shape` / `check_prompt_skeleton` / `judge_drift` 一字对齐，
  改这两个文件前先读那份文档，两边不能各说一套。
  改这两个文件前先读那份文档，两边不能各说一套。

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
# 11-06 双产出：出钩子文案时每条候选同步带一份**豆包网页版**完整提示词
# （NAS 模板的网页版裁剪：无段头编号/推荐标题/发布标签，10s/15s 按文案逐条判断）
HOOK_PROMPT_WEB_FILE = APP_DIR / "prompt" / "hook_prompt_web.txt"

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


def load_hook_prompt_web_template() -> str:
    """候选钩子文案 → 豆包网页版完整提示词（每候选一段）模板。"""
    return _load(HOOK_PROMPT_WEB_FILE)


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
        # 这三行必须与 asset_service.check_copy_shape 的判据一字不差：
        # 首句＝到第一个「。！？；，」（含半角）为止，**顿号不算断句**——模板里写宽了，
        # 模型按模板判短、代码按判据判超长，候选会整批卡在审核台之前。
        "硬性形态要求": "含标点（不含空白）不超过 80 字；首句不超过 25 字（首句＝从头到第一个「。！？；，」为止，顿号不算）；不得以逗号或顿号结尾。",
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


def generate_web_prompts(
    script: str,
    candidates: List[Dict[str, Any]],
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """候选钩子文案（列表）→ 每条一段豆包网页版完整提示词。

    规则在 `app/prompt/hook_prompt_web.txt`（NAS 模板的网页版裁剪，2026-11-06
    用户口径：无段头编号/推荐标题/发布标签；10s/15s 模型逐条按文案丰满程度判断）。
    本函数只透传模板点名的输入：详规、候选（seq/text/formula_tag）、剧名全称（可空）。
    """
    template = load_hook_prompt_web_template()
    if not template:
        raise RuntimeError("网页版提示词模板未找到，请检查 autoclip/app/prompt/hook_prompt_web.txt")
    cand_list = []
    for c in candidates or []:
        seq = int((c or {}).get("seq") or 0)
        text = str((c or {}).get("text") or "").strip()
        if not text:
            continue
        cand_list.append({
            "seq": seq,
            "text": text,
            "formula_tag": str((c or {}).get("formula_tag") or "").strip(),
        })
    if not cand_list:
        raise ValueError("候选文案列表为空，无法生成网页版提示词")
    p = params or {}
    input_data = {
        "反推详规（视频脚本，唯一事实来源）": script,
        "候选文案列表": json.dumps(cand_list, ensure_ascii=False),
        # 模板第①行「参考《剧名》剧情」唯一来源；取不到传空，模板自己写《剧名待定》
        "剧名全称": p.get("drama_title") or "",
        "补充要求": p.get("extra_requirements") or "",
        "合规要求": p.get("compliance")
        or "不得出现真实人名、地名、机构名、品牌名，一律使用代称；不涉及真实人物、真实事件与敏感内容。",
    }
    manager = get_llm_manager()
    raw = manager.call_with_retry(template, input_data, max_retries=max_retries)
    if not raw:
        raise RuntimeError("大模型返回空响应，生成网页版提示词失败")
    return _parse_web_prompts(raw)


def _parse_web_prompts(raw: str) -> Dict[str, Any]:
    """解析网页版提示词列表。兼容 {"prompts":[...]} / {"提示词":[...]}；无候选视为失败由调用方兜。"""
    stripped = _strip_fence(raw.strip())
    data = _loads_object(stripped)
    items: List[Any] = []
    if data:
        for key in ("prompts", "提示词", "提示词列表", "items", "list"):
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

    prompts: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        prompt_text = str(
            item.get("prompt_text") or item.get("提示词") or item.get("text") or ""
        ).strip()
        if not prompt_text:
            continue
        try:
            duration = int(item.get("duration") or item.get("时长") or 10)
        except (TypeError, ValueError):
            duration = 10
        prompts.append({
            "seq": int(item.get("seq") or item.get("序号") or 0),
            "duration": 15 if duration >= 15 else 10,   # 只认 10/15 两档，别的口径一律压回 10
            "prompt_text": prompt_text,
        })
    return {"prompts": prompts, "raw": None if data and prompts else stripped}


def expand_hook_copy(
    hook_copy: str,
    seq: int = 1,
    total: int = 1,
    variant_basis: str = "",
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """过审钩子文案 → 一条可投豆包的完整提示词（N 的差异化由 variant_basis 指定）。

    展开规则在 `app/prompt/hook_expand.txt`（已按 NAS 11-02 版对齐），本函数只负责
    把模板点名的输入项凑齐：钩子编号、剧名、K、角色卡有无缺一个都会让模型编数据。
    """
    template = load_hook_expand_template()
    if not template:
        raise RuntimeError("提示词展开模板未找到，请检查 autoclip/app/prompt/hook_expand.txt")

    p = params or {}
    input_data = {
        "过审钩子文案（必须原样出现在产物里，不得改写）": hook_copy,
        "本条序号": int(seq),
        # 段头要写「本钩共 M 条」（0916 数量显性化铁律），M 必须单独给：
        # 只给 "N/M" 合并串等于让模型自己拆，拆错就把条数写进产物了
        "本批总条数": int(total),
        "与同批其它条的差异来源": variant_basis or "",
        "素材编号": p.get("asset_code") or "",
        # 模板第①行要写「参考《剧名全称》剧情」，剧名只能由调用方给——模型自己补会编一个
        "剧名全称": p.get("drama_title") or "",
        "剧名缩写（推荐标题用，取自共享盘剧名缩写表）": p.get("drama_abbr") or "",
        "钩子编号（hook_id.py 取号，模板只照抄不许自己编）": p.get("hook_code") or "",
        "推荐标题条数 K（＝该剧发布号数）": p.get("recommended_title_count") or "",
        "来源平台": p.get("platform") or "",
        "目标时长（秒）": p.get("duration") or "",
        "是否已挂角色卡": ("是" if p.get("has_character_card") else "否") if p.get("has_character_card") is not None else "",
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
    """解析展开产物：prompt_text / dispatch_note / video_titles / 原句存活自报。

    `project_title` 只读历史：11-02 版「1020 起项目标题行已取消」，模板不再要求模型输出，
    后端也不再写入，这里留着只是为了让旧版模板产出的 JSON 还能被读出来。
    """
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
            # 上限 20 与后端 recommended_title_count 的 1..20 校验同口径（截 10 会把 K>10 的批次腰斩）
            "video_titles": [str(t).strip() for t in titles if str(t).strip()][:20],
            # B-9：投放要求（改名/跳过二次确认/并行）单独一字段，绝不混进可投正文
            "dispatch_note": str(data.get("dispatch_note") or data.get("投放要求") or "").strip() or None,
            "deviation_note": str(data.get("deviation_note") or data.get("偏差说明") or "").strip() or None,
            "self_reported_kept": data.get("hook_copy_kept_verbatim"),
        }
    # 非 JSON：整段当提示词，标题行取第一行
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    return {
        "project_title": first_line[:300] or None,
        "prompt_text": stripped or None,
        "video_titles": [],
        "dispatch_note": None,
        "note": "未按 JSON 结构返回，已整段作为提示词",
    }
