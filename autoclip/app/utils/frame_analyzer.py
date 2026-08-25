"""
画面理解分析器（Frame Analyzer）

在 AI 智能选点链路上新增「画面理解」：从源视频按候选片段时间抽帧，
送本地 Ollama（MiniCPM-V）生成结构化画面描述（场景/动作/情绪/OCR/精彩度），
供 step3 打分时与台词文本并列参考。

设计要点：
- 开关控制：FRAME_ANALYSIS_ENABLED=false 时完全跳过（默认关闭，不改变现有流程）
- 静默降级：Ollama 不可用 / 抽帧失败 / 解析失败 → 返回空，不影响主流程
- 结果缓存：同视频同片段不重复分析（按视频 hash + 片段时间戳做 key）
- 抽帧策略：每候选片段取「中段 1 帧 + 时间线内能量采样」，最多 FRAME_ANALYSIS_PER_CLIP 帧
"""
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.ollama_client import get_ollama_client
from ..core.shared_config import MEDIA_DIR, METADATA_DIR, FRAME_ANALYSIS_PROVIDER

logger = logging.getLogger(__name__)

# ── 配置（环境变量，compose 注入）──
FRAME_ANALYSIS_ENABLED = os.getenv("FRAME_ANALYSIS_ENABLED", "false").strip().lower() in ("1", "true", "yes")
# 每候选片段最多抽几帧（默认 2：中段 + 前 1/3）
FRAME_ANALYSIS_PER_CLIP = int(os.getenv("FRAME_ANALYSIS_PER_CLIP", "2"))
# 抽帧分辨率（宽，高自动等比；视觉描述 480p 足够）
FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", "480"))
# 画面分析超时兜底：单片段全部帧分析失败时最多重试 1 轮
FRAME_ANALYSIS_MAX_RETRY = 1

# 画面描述 prompt（要求结构化 JSON，字段与 step3 打分使用方对齐）
FRAME_PROMPT = """你是短剧运营分析师。分析这张短剧截图，严格只输出一个 JSON 对象（不要任何其他文字、不要 markdown 代码块），字段：
{"scene":"场景描述","action":"人物动作","emotion":"情绪","elements":"画面元素","ocr":"画面内文字(如有则原文,无则空字符串)","quality":5,"highlight":8,"reason":"一句话说明"}
quality=画面质量1-5分, highlight=作为短视频切片吸引力的精彩度1-10分"""

# 描述字段兜底默认值（模型漏字段时补齐，避免下游解析崩溃）
_DEFAULTS = {
    "scene": "",
    "action": "",
    "emotion": "",
    "elements": "",
    "ocr": "",
    "quality": 0,
    "highlight": 0,
    "reason": "",
}


def _seconds_to_ffmpeg_ts(sec: float) -> str:
    """秒 → ffmpeg 时间戳（HH:MM:SS.mmm）。"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _extract_frame(video_path: str, timestamp: float, out_path: str) -> bool:
    """用 ffmpeg 抽取指定时间点的一帧（缩放到 FRAME_WIDTH 宽）。"""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", _seconds_to_ffmpeg_ts(timestamp),
        "-i", video_path,
        "-frames:v", "1",
        "-vf", f"scale={FRAME_WIDTH}:-1",
        out_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0:
            logger.warning(f"抽帧失败（{timestamp}s）: {proc.stderr.decode(errors='ignore')[:200]}")
            return False
        return Path(out_path).exists() and Path(out_path).stat().st_size > 0
    except Exception as e:
        logger.warning(f"抽帧异常（{timestamp}s）: {e}")
        return False


def _normalize_description(raw: Dict[str, Any]) -> Dict[str, Any]:
    """补齐缺失字段，统一类型（quality/highlight 转 int）。"""
    desc = dict(_DEFAULTS)
    for k, v in raw.items():
        if v is None:
            continue
        if k in ("quality", "highlight"):
            try:
                desc[k] = max(0, min(10, int(float(v))))
            except (TypeError, ValueError):
                desc[k] = 0
        elif k in desc:
            desc[k] = str(v).strip()
    return desc


def _cache_key(video_path: str, start_sec: float, end_sec: float) -> str:
    """缓存 key：视频文件 hash 前 12 位 + 片段起止秒。"""
    try:
        h = hashlib.md5(open(video_path, "rb").read(1024 * 1024 * 2)).hexdigest()[:12]
    except OSError:
        h = "unknown"
    return f"{h}_{int(start_sec)}_{int(end_sec)}"


def _cache_dir() -> Path:
    d = METADATA_DIR.parent / "frame_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_cache(key: str) -> Optional[Dict[str, Any]]:
    try:
        p = _cache_dir() / f"{key}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"读取画面分析缓存失败: {e}")
    return None


def _write_cache(key: str, desc: Dict[str, Any]) -> None:
    try:
        p = _cache_dir() / f"{key}.json"
        p.write_text(json.dumps(desc, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.warning(f"写入画面分析缓存失败: {e}")


def analyze_clip_frames(
    video_path: str,
    start_time: str,
    end_time: str,
    project_id: Optional[str] = None,
    provider: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    分析单个候选片段的画面，返回结构化描述（合并该片段所有抽帧的结果）。

    Args:
        video_path: 源视频绝对路径（容器内 /app/media/xxx.mp4）
        start_time: 片段开始时间（HH:MM:SS,mmm 或 HH:MM:SS.mmm）
        end_time:   片段结束时间
        project_id: 项目 ID（用于日志，可选）
        provider:   视觉模型提供商（`ollama`/`llm`），None 时回退环境变量 FRAME_ANALYSIS_PROVIDER

    Returns:
        合并后的画面描述 dict；不可用/失败返回 None。
    """
    if not FRAME_ANALYSIS_ENABLED:
        return None

    video = Path(video_path)
    if not video.exists():
        logger.warning(f"画面分析：视频不存在 {video_path}，跳过")
        return None

    # 时间解析：兼容逗号/点号毫秒
    def to_sec(t: str) -> Optional[float]:
        try:
            t = t.replace(",", ".")
            parts = t.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        except Exception:
            pass
        return None

    start_sec = to_sec(start_time)
    end_sec = to_sec(end_time)
    if start_sec is None or end_sec is None or end_sec <= start_sec:
        logger.warning(f"画面分析：时间格式异常（{start_time}~{end_time}），跳过")
        return None

    # 缓存命中直接返回
    key = _cache_key(str(video), start_sec, end_sec)
    cached = _read_cache(key)
    if cached:
        logger.info(f"画面分析缓存命中: {key}")
        return cached

    # 抽帧时间点：中段 + 前 1/3（最多 FRAME_ANALYSIS_PER_CLIP 帧）
    mid = (start_sec + end_sec) / 2
    early = start_sec + (end_sec - start_sec) / 3
    ts_list = []
    if FRAME_ANALYSIS_PER_CLIP >= 2:
        ts_list = [early, mid]
    else:
        ts_list = [mid]

    # 视觉模型提供商分发：默认本地 Ollama；配置为 `llm` 时走在线 OpenAI 兼容视觉模型（如 Agnes）
    # 在线不可用（未配置 key/模型）时自动回退本地 Ollama，本地也不可用则跳过。
    eff_provider = (provider or FRAME_ANALYSIS_PROVIDER or "ollama").strip().lower()
    online_client = None
    if eff_provider in ("llm", "online"):
        from ..core.vision_llm_client import get_vision_llm_client
        online_client = get_vision_llm_client()
        if not online_client.available:
            logger.warning("画面分析：在线视觉模型未配置（LLM_API_KEY/模型），回退本地 Ollama")
            online_client = None

    client = None
    if online_client is None:
        client = get_ollama_client()
        if not client.available:
            logger.warning("画面分析：Ollama 服务不可用，跳过")
            return None

    descriptions: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="frame_") as tmp:
        for i, ts in enumerate(ts_list):
            frame_path = os.path.join(tmp, f"frame_{i}.jpg")
            if not _extract_frame(str(video), ts, frame_path):
                continue
            try:
                with open(frame_path, "rb") as f:
                    img_bytes = f.read()
            except OSError:
                continue
            if online_client is not None:
                desc = online_client.describe_image(img_bytes, FRAME_PROMPT)
            else:
                desc = client.describe_image(img_bytes, FRAME_PROMPT)
            if desc:
                descriptions.append(_normalize_description(desc))
            logger.info(
                f"画面分析 [{project_id or video.name}] {start_time}~{end_time} "
                f"帧{i + 1}/{len(ts_list)} @{ts:.1f}s: highlight={desc.get('highlight', '?') if desc else '失败'}"
            )

    if not descriptions:
        logger.warning(f"画面分析：片段 {start_time}~{end_time} 全部帧分析失败，跳过")
        return None

    # 合并多帧结果：取最高精彩度帧为主，其余补充
    best = max(descriptions, key=lambda d: d.get("highlight", 0))
    merged = dict(best)
    if len(descriptions) > 1:
        ocrs = [d.get("ocr", "") for d in descriptions if d.get("ocr")]
        if ocrs:
            merged["ocr"] = " | ".join(ocrs)
    merged["_frame_count"] = len(descriptions)

    _write_cache(key, merged)
    return merged


def analyze_timeline_frames(
    timeline_data: List[Dict],
    video_path: str,
    project_id: Optional[str] = None,
    enabled: Optional[bool] = None,
    provider: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    批量分析时间线中所有候选片段的画面。

    Args:
        enabled: 画面理解开关，None 时回退到环境变量 FRAME_ANALYSIS_ENABLED
        provider: 视觉模型提供商（`ollama`/`llm`），None 时回退环境变量 FRAME_ANALYSIS_PROVIDER

    Returns:
        {片段 id: 画面描述} 映射；未开启/失败返回空 dict。
    """
    if enabled is None:
        enabled = FRAME_ANALYSIS_ENABLED
    if not enabled:
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    for clip in timeline_data:
        clip_id = str(clip.get("id", ""))
        if not clip_id:
            continue
        desc = analyze_clip_frames(
            video_path,
            clip.get("start_time", ""),
            clip.get("end_time", ""),
            project_id,
            provider=provider,
        )
        if desc:
            results[clip_id] = desc
    return results
