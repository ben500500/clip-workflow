"""
AutoClip Service - AI 选点服务
真实调用阿里云百炼 DashScope（通义千问）：
  ASR (aliyun_speech 或 whisper) -> 大纲 -> 时间线 -> 评分 -> 标题
保留对外 API 契约不变：
  POST /api/v1/projects
  POST /api/v1/upload?project_id=X
  POST /api/v1/pipeline/run
  GET  /api/v1/progress/{project_id}
  GET  /api/v1/clips?project_id=X&min_score=60&max_clips=30
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

# 让所有子模块（llm_providers / pipeline / speech_recognizer）的日志输出到 stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

from app.core.shared_config import PROMPT_FILES, METADATA_DIR  # noqa: E402
from app.utils.speech_recognizer import (  # noqa: E402
    SpeechRecognitionConfig,
    SpeechRecognitionMethod,
    SpeechRecognitionError,
    SpeechRecognizer,
)
from app.pipeline.step1_outline import run_step1_outline  # noqa: E402
from app.pipeline.step2_timeline import run_step2_timeline  # noqa: E402
from app.pipeline.step3_scoring import run_step3_scoring  # noqa: E402
from app.pipeline.step4_title import run_step4_title  # noqa: E402
from app.services.seedance_prompt_generator import (  # noqa: E402
    generate_prompt_versions,
    generate_seedance_prompt,
)
from app.services.publish_material_generator import generate_publish_material  # noqa: E402
from app.services.script_optimizer import optimize_script_text  # noqa: E402
from app.core.llm_manager import get_llm_manager  # noqa: E402

logger = logging.getLogger("autoclip.main")

MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", "/app/media"))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# In-memory project registry. 项目重启后丢失，属于轻量模拟服务可接受的行为。
projects: dict[str, dict] = {}

app = FastAPI(title="AutoClip Service", version="2.0.0")


def ffprobe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _update_progress(proj: dict, status: str, progress: int, message: str) -> None:
    proj["status"] = status
    proj["progress"] = progress
    proj["message"] = message
    logger.info(f"[project={proj.get('id')}] {message}")


def _fail(proj: dict, message: str) -> None:
    logger.error(f"[project={proj.get('id')}] {message}")
    proj["status"] = "failed"
    proj["message"] = message
    # 保留失败时的进度，便于排查
    if not proj.get("progress"):
        proj["progress"] = 0


# ----------------------- 契约转换层 -----------------------

def _srt_time_to_seconds(value) -> float:
    """SRT 时间字符串 "HH:MM:SS,mmm"（或秒数值）转秒。"""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(',', '.')
    parts = s.split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _safe_str(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, list):
        return "；".join(str(x) for x in value)
    if isinstance(value, dict):
        if "title" in value:
            return str(value.get("title") or "")
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _to_contract_clips(raw_clips: list) -> list:
    """
    把真实流水线输出转换为契约格式。
    真实字段: outline(dict|str), start_time("01:10:25,500"), final_score(0~1),
              generated_title, content, recommend_reason
    契约字段: clip_index, start_time/end_time/duration(秒), title, content,
              outline(str), score(0~100), recommend_reason
    """
    result = []
    for i, c in enumerate(raw_clips, start=1):
        start = _srt_time_to_seconds(c.get("start_time"))
        end = _srt_time_to_seconds(c.get("end_time"))
        if end < start:
            end = start

        outline_str = _safe_str(c.get("outline"))
        content_str = _safe_str(c.get("content"))

        title = c.get("generated_title")
        if not title or not str(title).strip():
            title = outline_str or f"高光片段 {i}"

        try:
            score = round(max(0.0, min(1.0, float(c.get("final_score", 0.0)))) * 100, 2)
        except (TypeError, ValueError):
            score = 0.0

        reason = c.get("recommend_reason") or "基于 ASR 文本与剧情节奏综合评分"

        result.append({
            "clip_index": i,
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "duration": round(max(end - start, 0.0), 3),
            "title": str(title),
            "content": content_str,
            "outline": outline_str,
            "score": score,
            "recommend_reason": str(reason),
        })
    return result


# ----------------------- 真实流水线（后台执行） -----------------------

def _parse_srt_ts(ts: str) -> float:
    """解析 SRT 时间戳 '00:01:25,000' -> 秒数 85.0"""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _filter_srt_by_time(srt_path: Path, out_path: Path,
                        start_time: Optional[float] = None,
                        end_time: Optional[float] = None) -> Path:
    """按时间范围过滤 SRT 字幕（窗口化），返回新的 SRT 路径。

    - start_time / end_time 单位秒；None 表示不限制该侧。
    - 保留与窗口有交集的字幕块，重写序号。
    """
    if start_time is None and end_time is None:
        return srt_path
    if not srt_path.exists() or srt_path.stat().st_size == 0:
        return srt_path

    lines = srt_path.read_text(encoding="utf-8").splitlines()
    kept = []
    i = 0
    while i < len(lines):
        if lines[i].strip().isdigit() and i + 1 < len(lines) and "-->" in lines[i + 1]:
            t_line = lines[i + 1]
            try:
                s_sec = _parse_srt_ts(t_line.split("-->")[0])
                e_sec = _parse_srt_ts(t_line.split("-->")[1])
            except Exception:
                i += 1
                continue
            in_range = True
            if start_time is not None and e_sec < start_time:
                in_range = False
            if end_time is not None and s_sec > end_time:
                in_range = False
            if in_range:
                j = i + 2
                texts = []
                while j < len(lines) and lines[j].strip() != "":
                    texts.append(lines[j])
                    j += 1
                kept.append((t_line, texts))
                i = j
                continue
        i += 1

    with open(out_path, "w", encoding="utf-8") as f:
        for n, (t_line, texts) in enumerate(kept, 1):
            f.write(f"{n}\n{t_line}\n" + "\n".join(texts) + "\n\n")
    return out_path


def _run_asr(video_path: str, srt_path: Path, api_key: str) -> None:
    """按环境变量 AUTOCLIP_ASR_METHOD 选择 ASR 方式生成 SRT。

    支持 aliyun_speech（默认，需 DASHSCOPE_API_KEY）与 whisper（本地 faster-whisper）。
    whisper 无需 API Key；模型用 WHISPER_MODEL 选择（默认 small）。

    转写结果按「视频内容哈希 + ASR 方式」缓存到 MEDIA_DIR/data/asr_cache，
    同一视频再次启动 AI 选点时可直接复用，避免重复转写（尤其 whisper 本地推理耗时）。
    可用环境变量 AUTOCLIP_ASR_CACHE=false 关闭缓存。
    """
    method_name = os.getenv("AUTOCLIP_ASR_METHOD", "aliyun_speech").strip().lower()
    method = SpeechRecognitionMethod(method_name)
    config = SpeechRecognitionConfig(
        method=method,
        output_format="srt",
    )
    if method == SpeechRecognitionMethod.ALIYUN_SPEECH:
        config.aliyun_access_key = api_key

    video = Path(video_path)
    if not video.exists():
        raise SpeechRecognitionError(f"视频文件不存在: {video_path}")

    cache_key = _asr_cache_key(video, method_name)
    cached = _asr_cache_get(cache_key)
    if cached is not None:
        logger.info("命中 ASR 字幕缓存，直接复用: %s", cached)
        srt_path.parent.mkdir(parents=True, exist_ok=True)
        srt_path.write_text(cached, encoding="utf-8")
        return

    recognizer = SpeechRecognizer(config)
    recognizer.generate_subtitle(video, srt_path, config)

    if srt_path.exists() and srt_path.stat().st_size > 0:
        _asr_cache_put(cache_key, srt_path.read_text(encoding="utf-8"))
        logger.info("ASR 字幕已写入缓存: %s", cache_key)


def _asr_cache_enabled() -> bool:
    """ASR 字幕缓存开关，默认开启。"""
    return os.getenv("AUTOCLIP_ASR_CACHE", "true").strip().lower() not in ("0", "false", "no")


def _asr_cache_dir() -> Path:
    """ASR 字幕缓存目录（持久化 volume，容器重建不丢失）。"""
    cache_dir = Path(os.getenv("ASR_CACHE_DIR", "/app/media/data/asr_cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _asr_cache_key(video: Path, method_name: str) -> str:
    """根据视频内容生成缓存键：文件名(前40) + 内容哈希(前12) + ASR方式。"""
    digest = hashlib.sha256()
    try:
        with open(video, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as e:
        raise SpeechRecognitionError(f"读取视频内容失败（无法计算缓存键）: {e}") from e
    stem = re.sub(r"[^\w.-]+", "_", video.stem)[:40] or "video"
    return f"{stem}-{digest.hexdigest()[:12]}-{method_name}.srt"


def _asr_cache_get(cache_key: str) -> Optional[str]:
    """读取 ASR 字幕缓存；未开启或不存在时返回 None。"""
    if not _asr_cache_enabled():
        return None
    cache_path = _asr_cache_dir() / cache_key
    try:
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("读取 ASR 字幕缓存失败: %s: %s", cache_path, e)
    return None


def _asr_cache_put(cache_key: str, content: str) -> None:
    """写入 ASR 字幕缓存（原子写，失败不影响主流程）。"""
    if not _asr_cache_enabled():
        return
    cache_path = _asr_cache_dir() / cache_key
    try:
        tmp = cache_path.with_suffix(".srt.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(cache_path)
    except OSError as e:
        logger.warning("写入 ASR 字幕缓存失败: %s: %s", cache_path, e)


async def _run_pipeline(project_id: str, steps: list[int],
                        max_clips: Optional[int] = None,
                        start_time: Optional[float] = None,
                        end_time: Optional[float] = None,
                        frame_analysis: Optional[bool] = None,
                        model_name: Optional[str] = None,
                        llm_provider: Optional[str] = None) -> None:
    proj = projects.get(project_id)
    if not proj:
        return

    try:
        # 运行时覆盖选点模型（来自系统设置 default_autoclip_config / 请求参数），不落盘
        if model_name:
            get_llm_manager().set_runtime_model(model_name, llm_provider)
            logger.info(f"[project={project_id}] 本次选点使用模型覆盖: {model_name}")
        else:
            logger.info(f"[project={project_id}] 本次选点使用默认模型: {_current_llm_model()}")

        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY 环境变量，无法调用阿里云百炼 DashScope")

        video_path = proj.get("video_path")
        if not video_path or not Path(video_path).exists():
            raise RuntimeError("项目未上传视频或视频文件不存在")

        meta_dir = METADATA_DIR / project_id
        meta_dir.mkdir(parents=True, exist_ok=True)
        srt_path = meta_dir / "subtitle.srt"

        # Step 0: ASR 语音识别
        asr_method = os.getenv("AUTOCLIP_ASR_METHOD", "aliyun_speech").strip().lower()
        asr_label = {"whisper": "本地 whisper", "aliyun_speech": "阿里云 qwen3-asr-flash"}.get(asr_method, asr_method)
        _update_progress(proj, "running", 5, f"开始 ASR 语音识别（{asr_label}）")
        await asyncio.to_thread(_run_asr, video_path, srt_path, api_key)
        if srt_path.stat().st_size == 0:
            logger.warning(f"[project={project_id}] ASR 未识别到语音内容（视频可能无声音/静音）")
        _update_progress(proj, "running", 20, "ASR 语音识别完成，开始大纲提取")

        # 时间范围窗口化：过滤 SRT 字幕，只保留 [start_time, end_time] 内的内容
        pipeline_srt = srt_path
        if start_time is not None or end_time is not None:
            windowed = meta_dir / "subtitle_windowed.srt"
            pipeline_srt = _filter_srt_by_time(srt_path, windowed, start_time, end_time)
            window_desc = f"[{start_time if start_time is not None else 0}s ~ {end_time if end_time is not None else '结尾'}s]"
            _update_progress(proj, "running", 20, f"按时间范围 {window_desc} 窗口化字幕")

        # Step 1: 大纲提取
        outlines = await asyncio.to_thread(
            run_step1_outline, pipeline_srt, meta_dir, None, PROMPT_FILES)
        _update_progress(proj, "running", 40,
                         f"大纲提取完成（{len(outlines)} 个话题），定位时间线")

        # Step 2: 时间线定位
        duration_config = proj.get("config") or {}
        timeline = await asyncio.to_thread(
            run_step2_timeline, meta_dir / "step1_outline.json", meta_dir, None, PROMPT_FILES,
            duration_config=duration_config)
        _update_progress(proj, "running", 60,
                         f"时间线定位完成（{len(timeline)} 个片段），开始评分")

        # Step 3: 评分（画面理解：把源视频路径注入环境变量，供 frame_analyzer 抽帧分析）
        if video_path:
            os.environ["FRAME_ANALYSIS_VIDEO_PATH"] = str(video_path)
        scored = await asyncio.to_thread(
            run_step3_scoring, meta_dir / "step2_timeline.json", meta_dir, None, PROMPT_FILES,
            frame_analysis_enabled=frame_analysis)
        _update_progress(proj, "running", 80,
                         f"评分完成（{len(scored)} 个高分片段），生成标题")

        # 切片数量控制：按 final_score 降序取 top-N，并重写 step3 结果供 step4 使用
        if max_clips and max_clips > 0 and len(scored) > max_clips:
            scored = sorted(scored, key=lambda c: c.get("final_score", 0), reverse=True)[:max_clips]
            with open(meta_dir / "step3_high_score_clips.json", "w", encoding="utf-8") as f:
                json.dump(scored, f, ensure_ascii=False, indent=2)
            _update_progress(proj, "running", 85, f"按分数取前 {max_clips} 个片段")

        # Step 4: 标题生成
        titled = await asyncio.to_thread(
            run_step4_title, meta_dir / "step3_high_score_clips.json",
            None, str(meta_dir), PROMPT_FILES)

        clips = _to_contract_clips(titled)
        proj["clips"] = clips
        _update_progress(proj, "completed", 100,
                         f"流水线完成，生成 {len(clips)} 个高光片段")

    except SpeechRecognitionError as e:
        _fail(proj, f"语音识别失败: {e}")
    except RuntimeError as e:
        _fail(proj, str(e))
    except Exception as e:
        _fail(proj, f"流水线执行失败: {e}")


# ----------------------- 对外 API -----------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


class SeedancePromptRequest(BaseModel):
    text: str = ""
    duration: int = 15          # 10 / 15 / 20 / 25 / 30 秒
    params: dict = {}           # 可选：theme/tone/characters/extra_requirements
    templates: dict = {}        # 可选：用户自定义长/短提示词模板 {"long":.., "short":..}
    max_retries: int = 3


@app.post("/api/v1/prompt/generate")
async def generate_prompt(data: SeedancePromptRequest):
    """根据短剧文案一次生成提示词三版本：长提示词 / 短提示词 / AI提示词。

    - 长 / 短：固定模板，仅把 [视频文案] 替换为用户输入的文案，不做其它处理；
    - AI：复用 autoclip 中配置的大模型（DASHSCOPE_API_KEY / API_MODEL_NAME），
      依据《Seedance短剧视频生成提示词模板》七段结构组装提示词正文（当前这套）。
    返回结构：{"prompt": 兼容旧字段(AI版), "versions": {"long":.., "short":.., "ai":..}, ...}
    """
    if not data.text or not data.text.strip():
        raise HTTPException(status_code=400, detail="请输入短剧文案")
    try:
        versions = await asyncio.to_thread(
            generate_prompt_versions,
            data.text.strip(),
            duration=data.duration,
            params=data.params or {},
            max_retries=data.max_retries,
            templates=data.templates or {},
        )
    except Exception as e:
        logger.error("Seedance prompt generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"提示词生成失败: {e}")
    return {
        "prompt": versions.get("ai") or "",
        "versions": versions,
        "duration": data.duration,
        "model": _current_llm_model(),
    }


def _current_llm_model() -> str:
    """返回当前 autoclip LLM 配置中的模型名（尽力而为，失败返回空）。"""
    try:
        info = get_llm_manager().get_current_provider_info()
        return info.get("model") or ""
    except Exception:
        return ""


class SubtitleGenerateRequest(BaseModel):
    """字幕生成请求：给定视频 URL，ASR 识别后返回 SRT 字幕内容。"""
    video_url: str = ""
    # 可选：仅转写 [start_time, end_time] 区间（秒，None 表示不限）
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    # 可选：直接传视频内容 base64（与 video_url 二选一）
    video_b64: Optional[str] = None


@app.post("/api/v1/subtitle/generate")
async def generate_subtitle(data: SubtitleGenerateRequest):
    """对给定视频做 ASR 语音识别，返回 SRT 字幕内容（供切片烧录字幕用）。

    - 优先用 video_b64（避免跨容器下载），否则用 video_url 下载；
    - 复用 _run_asr 的字幕缓存（按视频内容哈希 + ASR 方式），同一视频不重复转写；
    - 返回 {srt: "...", method: "aliyun_speech|whisper", duration: 秒, cached: bool}。
    """
    if not data.video_b64 and not data.video_url:
        raise HTTPException(status_code=400, detail="必须提供 video_url 或 video_b64")

    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip() or os.getenv("API_DASHSCOPE_API_KEY", "").strip()
    asr_method = os.getenv("AUTOCLIP_ASR_METHOD", "aliyun_speech").strip().lower()
    if asr_method == "aliyun_speech" and not api_key:
        raise HTTPException(status_code=400, detail="未配置 DASHSCOPE_API_KEY，无法使用阿里云 ASR；可改用 AUTOCLIP_ASR_METHOD=whisper")

    video_path: Optional[Path] = None
    tmp_dir = Path(tempfile.mkdtemp(prefix="subtitle_"))
    try:
        if data.video_b64:
            import base64
            try:
                video_path = tmp_dir / "input_video.mp4"
                video_path.write_bytes(base64.b64decode(data.video_b64))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"video_b64 解码失败: {e}")
        else:
            if not data.video_url.startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail="video_url 必须是 http(s) 地址")
            video_path = tmp_dir / "input_video.mp4"
            try:
                with requests.get(data.video_url, stream=True, timeout=(10, 300)) as r:
                    if r.status_code != 200:
                        raise HTTPException(status_code=502, detail=f"下载视频失败: HTTP {r.status_code}")
                    with open(video_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                f.write(chunk)
            except requests.RequestException as e:
                raise HTTPException(status_code=502, detail=f"下载视频失败: {e}")

        if not video_path.exists() or video_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="视频内容为空")

        duration = ffprobe_duration(str(video_path))

        # 生成完整 SRT（复用 ASR 缓存）
        srt_path = tmp_dir / "subtitle.srt"
        try:
            await asyncio.to_thread(_run_asr, str(video_path), srt_path, api_key)
        except SpeechRecognitionError as e:
            raise HTTPException(status_code=502, detail=f"语音识别失败: {e}")

        srt_content = ""
        if srt_path.exists():
            srt_content = srt_path.read_text(encoding="utf-8")

        # 时间范围窗口化（可选）
        if (data.start_time is not None or data.end_time is not None) and srt_content.strip():
            windowed = tmp_dir / "subtitle_windowed.srt"
            out = _filter_srt_by_time(srt_path, windowed, data.start_time, data.end_time)
            if out.exists():
                srt_content = out.read_text(encoding="utf-8")

        return {
            "srt": srt_content,
            "method": asr_method,
            "duration": round(duration, 3),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("generate_subtitle failed: %s", e)
        raise HTTPException(status_code=500, detail=f"字幕生成失败: {e}")
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


class PublishMaterialRequest(BaseModel):
    story: str = ""           # 短剧剧情梗概（必填）
    params: dict = {}          # 可选：title/theme/tone/platform/extra_requirements
    max_retries: int = 3


class ScriptOptimizeRequest(BaseModel):
    text: str = ""            # 待优化的短剧文案（必填）
    params: dict = {}          # 可选：theme/tone/extra_requirements
    max_retries: int = 3


@app.post("/api/v1/script/optimize")
async def optimize_script(data: ScriptOptimizeRequest):
    """短剧文案 AI 优化：调用 autoclip 配置的大模型改写文案。

    - 保留主线与核心反转，增强冲突 / 悬念 / 情绪张力
    - 保持对白 / 旁白标注格式，人名地名用代称
    - 直接返回优化后的文案正文
    """
    if not data.text or not data.text.strip():
        raise HTTPException(status_code=400, detail="请输入短剧文案")
    try:
        optimized = await asyncio.to_thread(
            optimize_script_text,
            data.text.strip(),
            params=data.params or {},
            max_retries=data.max_retries,
        )
    except Exception as e:
        logger.error("Script optimize failed: %s", e)
        raise HTTPException(status_code=500, detail=f"文案优化失败: {e}")
    return {
        "optimized_text": optimized,
        "model": _current_llm_model(),
    }


@app.post("/api/v1/publish-material/generate")
async def generate_material(data: PublishMaterialRequest):
    """根据短剧剧情梗概生成一套可发布的短剧发布素材。

    输出结构严格顺序：短标题 → 三款视频配文 → 成套话题标签 → 三条置顶互动神评。
    复用 autoclip 中配置的大模型（DASHSCOPE_API_KEY / API_MODEL_NAME）。
    """
    if not data.story or not data.story.strip():
        raise HTTPException(status_code=400, detail="请输入短剧剧情梗概")
    try:
        material = await asyncio.to_thread(
            generate_publish_material,
            data.story.strip(),
            params=data.params or {},
            max_retries=data.max_retries,
        )
    except Exception as e:
        logger.error("Publish material generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"发布素材生成失败: {e}")
    return {
        "material": material,
        "model": _current_llm_model(),
    }


# 兼容别名：后端可能通过 /api/v1 前缀调用 health
@app.get("/api/v1/health")
async def health_v1():
    return {"status": "ok"}


class ProjectCreate(BaseModel):
    name: str
    config: dict = {}


@app.post("/api/v1/projects")
async def create_project(data: ProjectCreate):
    pid = str(uuid.uuid4())
    projects[pid] = {
        "id": pid,
        "name": data.name,
        "config": data.config,
        "video_path": None,
        "duration": 0.0,
        "status": "created",
        "progress": 0,
        "message": "项目已创建",
        "clips": [],
    }
    return {"id": pid, "name": data.name, "config": data.config}


@app.post("/api/v1/upload")
async def upload(project_id: str, file: UploadFile = File(...)):
    proj = projects.get(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    path = MEDIA_DIR / f"{project_id}{ext}"
    with open(path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    proj["video_path"] = str(path)
    proj["duration"] = ffprobe_duration(str(path))
    return {"ok": True, "path": str(path), "duration": proj["duration"]}


class PipelineRun(BaseModel):
    project_id: str
    steps: list[int] = [1, 2, 3, 4, 5, 6]
    # 切片数量控制：按评分降序取前 N 个高光片段
    max_clips: Optional[int] = None
    # 选点时间范围（秒）：仅在该窗口内选点
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    # 画面理解（MiniCPM-V）开关：None 时回退到环境变量 FRAME_ANALYSIS_ENABLED
    frame_analysis: Optional[bool] = None
    # 选点模型覆盖（来自系统设置 default_autoclip_config.llm_model / 请求参数）；
    # 指定后本次运行使用该模型，不修改磁盘上的用户配置
    model_name: Optional[str] = None
    llm_provider: Optional[str] = None


@app.post("/api/v1/pipeline/run")
async def pipeline_run(data: PipelineRun):
    proj = projects.get(data.project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not proj.get("video_path"):
        raise HTTPException(status_code=400, detail="请先上传视频")
    proj["status"] = "running"
    proj["progress"] = 0
    proj["message"] = "流水线启动"
    proj["clips"] = []
    asyncio.create_task(_run_pipeline(
        data.project_id, data.steps,
        max_clips=data.max_clips,
        start_time=data.start_time,
        end_time=data.end_time,
        frame_analysis=data.frame_analysis,
        model_name=data.model_name,
        llm_provider=data.llm_provider,
    ))
    return {"ok": True, "project_id": data.project_id}


@app.get("/api/v1/progress/{project_id}")
async def progress(project_id: str):
    proj = projects.get(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "status": proj["status"],
        "progress": proj["progress"],
        "message": proj["message"],
    }


@app.get("/api/v1/clips")
async def clips(project_id: str, min_score: float = 0.0, max_clips: int = 30,
                 min_duration: float = 0.0, max_duration: float = 0.0):
    proj = projects.get(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    result = list(proj.get("clips") or [])
    if min_score > 0:
        result = [c for c in result if c["score"] >= min_score]
    if min_duration > 0:
        result = [c for c in result if c.get("duration", 0) >= min_duration]
    if max_duration > 0:
        result = [c for c in result if c.get("duration", 0) <= max_duration]
    return result[:max_clips]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
