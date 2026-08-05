"""
AutoClip Service - AI 选点服务
真实调用阿里云百炼 DashScope（通义千问）：
  ASR (qwen3-asr-flash) -> 大纲 -> 时间线 -> 评分 -> 标题
保留对外 API 契约不变：
  POST /api/v1/projects
  POST /api/v1/upload?project_id=X
  POST /api/v1/pipeline/run
  GET  /api/v1/progress/{project_id}
  GET  /api/v1/clips?project_id=X&min_score=60&max_clips=30
"""
import asyncio
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path

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

def _run_asr(video_path: str, srt_path: Path, api_key: str) -> None:
    """按环境变量 AUTOCLIP_ASR_METHOD 选择 ASR 方式生成 SRT。

    支持 aliyun_speech（默认，需 DASHSCOPE_API_KEY）与 whisper（本地 faster-whisper）。
    whisper 无需 API Key；模型用 WHISPER_MODEL 选择（默认 small）。
    """
    method_name = os.getenv("AUTOCLIP_ASR_METHOD", "aliyun_speech").strip().lower()
    method = SpeechRecognitionMethod(method_name)
    config = SpeechRecognitionConfig(
        method=method,
        output_format="srt",
    )
    if method == SpeechRecognitionMethod.ALIYUN_SPEECH:
        config.aliyun_access_key = api_key
    recognizer = SpeechRecognizer(config)
    recognizer.generate_subtitle(Path(video_path), srt_path, config)


async def _run_pipeline(project_id: str, steps: list[int]) -> None:
    proj = projects.get(project_id)
    if not proj:
        return

    try:
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
        _update_progress(proj, "running", 5, "开始 ASR 语音识别（qwen3-asr-flash）")
        await asyncio.to_thread(_run_asr, video_path, srt_path, api_key)
        if srt_path.stat().st_size == 0:
            logger.warning(f"[project={project_id}] ASR 未识别到语音内容（视频可能无声音/静音）")
        _update_progress(proj, "running", 20, "ASR 语音识别完成，开始大纲提取")

        # Step 1: 大纲提取
        outlines = await asyncio.to_thread(
            run_step1_outline, srt_path, meta_dir, None, PROMPT_FILES)
        _update_progress(proj, "running", 40,
                         f"大纲提取完成（{len(outlines)} 个话题），定位时间线")

        # Step 2: 时间线定位
        timeline = await asyncio.to_thread(
            run_step2_timeline, meta_dir / "step1_outline.json", meta_dir, None, PROMPT_FILES)
        _update_progress(proj, "running", 60,
                         f"时间线定位完成（{len(timeline)} 个片段），开始评分")

        # Step 3: 评分
        scored = await asyncio.to_thread(
            run_step3_scoring, meta_dir / "step2_timeline.json", meta_dir, None, PROMPT_FILES)
        _update_progress(proj, "running", 80,
                         f"评分完成（{len(scored)} 个高分片段），生成标题")

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
    asyncio.create_task(_run_pipeline(data.project_id, data.steps))
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
async def clips(project_id: str, min_score: float = 0.0, max_clips: int = 30):
    proj = projects.get(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    result = list(proj.get("clips") or [])
    if min_score > 0:
        result = [c for c in result if c["score"] >= min_score]
    return result[:max_clips]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
