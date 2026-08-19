"""「去重处理」独立入口 API（圆桌定稿 Phase 2 可观测）。

提供：
- POST /dedupe/upload：批量文件拖入——把视频上传到服务器本地临时目录，
  返回本地 path 供 batch-slice/run 复用（batch_slice_task 处理完会自动清理临时文件）。

设计：只补「文件落地」这一环，去重/变体逻辑完全复用现有链路：
batch-slice/run（上传→切片）→ variants/generate-batch（对 SliceOutput 生成变体）。
"""
import ast
import logging
import os
import uuid

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.auth import get_current_user
from app.config import settings
from app.models.models import User
from app.services.upload_service import validate_file_name

logger = logging.getLogger(__name__)

router = APIRouter()

# 去重处理上传的临时落地目录（batch_slice_task 处理完自动清理对应源文件）
DEDUPE_UPLOAD_DIR = "/tmp/dedupe_upload"

# ---------------------------------------------------------------------------
# 去重配置单一来源化（Issue #252）
#
# engines/slice.py 的 DEDUPE_PRESETS 是去重档位的**权威来源**。前端页面此前各自
# 硬编码档位列表与字段定义，新增去重手段时需人工多处同步、容易漏。这里把
# DEDUPE_PRESETS 以只读方式暴露为 GET /api/dedupe/presets：
#   - presets ：档位列表（value + 中文 label + 描述）
#   - fields  ：字段定义（key/中文label/类型/min/max/step/UI控件）——前端据此动态渲染
#   - defaults：每档全量默认参数（即 DEDUPE_PRESETS 原文）
# 引擎 build_dedupe_filter 逻辑不动，本接口只是把数据暴露出去；字段 key 与引擎
# _resolve_dedupe_config 读取的 manual 键一一对应。
# ---------------------------------------------------------------------------

DEDUPE_ENGINE_FILE = "slice.py"


# 字段定义（UI 渲染契约）。key 必须与 engines/slice.py DEDUPE_PRESETS 键一致，
# 新增去重手段只需在此追加一条定义，前端自动出现对应控件。
# type: number|bool|string|dict（数据类型）
# control: number|slider|switch|select|text|group（UI 控件类型）
# hidden=True 表示引擎支持该键但当前 UI 不暴露（如色彩串/音频指纹），不影响默认值。
DEDUPE_FIELD_DEFS = [
    # ── 空间层 ──
    {
        "key": "crop", "label": "裁切比例", "type": "number", "control": "number",
        "group": "空间层", "min": 0, "max": 0.2, "step": 0.005,
        "tip": "裁掉四周的比例（改构图/像素对齐），0~20%，越大越明显。",
    },
    {
        "key": "hflip", "label": "水平镜像", "type": "bool", "control": "switch",
        "group": "空间层", "default": False,
        "tip": "水平翻转画面，直接破坏帧哈希。",
    },
    # ── 时域层 ──
    {
        "key": "speed", "label": "变速系数", "type": "number", "control": "number",
        "group": "时域层", "min": 1, "max": 1.2, "step": 0.01, "default": 1.0,
        "tip": "整体提速系数（1.0~1.2），改变时长与帧对齐。",
    },
    # ── 色彩层 ──
    {
        "key": "saturation", "label": "饱和度", "type": "number", "control": "slider",
        "group": "色彩层", "min": 0.5, "max": 1.5, "step": 0.01, "default": 1.0,
        "tip": "饱和度系数，越小越灰（去重常用降饱和）。",
    },
    {
        "key": "gamma", "label": "伽马", "type": "number", "control": "number",
        "group": "色彩层", "min": 0.8, "max": 1.4, "step": 0.01, "default": 1.0,
        "tip": "伽马值，微调亮度层次。",
    },
    {
        "key": "contrast", "label": "对比度", "type": "number", "control": "number",
        "group": "色彩层", "min": 0.8, "max": 1.4, "step": 0.01, "default": 1.0,
        "tip": "对比度系数。",
    },
    {
        "key": "brightness", "label": "亮度", "type": "number", "control": "number",
        "group": "色彩层", "min": -0.2, "max": 0.2, "step": 0.005, "default": 0,
        "tip": "亮度调整（-0.2~0.2）。",
    },
    # 色彩串字段：引擎支持、UI 暂不直接暴露（保持既有面板不变），hidden 不渲染
    {
        "key": "colorbalance", "label": "复古偏色", "type": "string", "control": "text",
        "group": "色彩层", "hidden": True,
    },
    {
        "key": "colortemperature", "label": "暖冷色温", "type": "string", "control": "text",
        "group": "色彩层", "hidden": True,
    },
    # ── 质感层（老电视效果） ──
    {
        "key": "noise", "label": "颗粒噪点", "type": "number", "control": "slider",
        "group": "质感层", "min": 0, "max": 20, "step": 1, "default": 0,
        "tip": "胶片颗粒/老电视颗粒强度，0 关闭。",
    },
    {
        "key": "sharpen", "label": "锐化/降噪", "type": "number", "control": "slider",
        "group": "质感层", "min": 0, "max": 2, "step": 0.1, "default": 0,
        "tip": "unsharp 锐化量，微调画质细节差异，0 关闭。",
    },
    {
        "key": "scanline", "label": "扫描线", "type": "dict", "control": "group",
        "group": "质感层", "hidden": True,
        "tip": "老电视扫描线（dict 或 None）。",
    },
    {
        "key": "vignette", "label": "暗角", "type": "string", "control": "select",
        "group": "质感层",
        "options": [
            {"value": "", "label": "关闭"},
            {"value": "PI/6", "label": "轻"},
            {"value": "PI/5", "label": "中"},
            {"value": "PI/4", "label": "重"},
        ],
        "tip": "边缘压暗（PI/6 轻 ~ PI/4 重），空值关闭。",
    },
    {
        "key": "roll_band", "label": "滚动暗带", "type": "number", "control": "slider",
        "group": "质感层", "min": 0, "max": 30, "step": 1, "default": 0,
        "tip": "上下缓慢滚动的亮度条带强度，0 关闭。",
    },
    {
        "key": "jitter", "label": "画面抖动", "type": "number", "control": "slider",
        "group": "质感层", "min": 0, "max": 8, "step": 1, "default": 0,
        "tip": "正弦摆动强度（px），0 关闭。",
    },
    # ── 贴纸水印叠加（dict 子字段） ──
    {
        "key": "watermark", "label": "贴纸水印叠加", "type": "dict", "control": "group",
        "group": "贴纸水印叠加", "default": None,
        "tip": "叠加半透明文字标识作为去重差异化（区别于动态水印）。",
        "fields": [
            {"key": "enabled", "label": "开启贴纸水印", "type": "bool", "control": "switch", "default": False},
            {"key": "text", "label": "水印文字", "type": "string", "control": "text", "default": "Clip", "max_len": 20},
            {"key": "opacity", "label": "透明度", "type": "number", "control": "slider", "min": 0.05, "max": 0.9, "step": 0.05, "default": 0.25},
            {
                "key": "position", "label": "位置", "type": "string", "control": "select", "default": "bottom-right",
                "options": [
                    {"value": "top-left", "label": "左上"}, {"value": "top-right", "label": "右上"},
                    {"value": "top-center", "label": "上中"}, {"value": "center", "label": "居中"},
                    {"value": "bottom-left", "label": "左下"}, {"value": "bottom-right", "label": "右下"},
                    {"value": "bottom-center", "label": "下中"},
                ],
            },
            {"key": "drift", "label": "缓慢漂移", "type": "bool", "control": "switch", "default": False,
             "tip": "水印随时间缓慢移动，增强时序差异化。"},
        ],
    },
    # ── 音频指纹差异化（引擎支持、UI 暂不直接暴露） ──
    {
        "key": "audio", "label": "音频指纹差异化", "type": "string", "control": "text",
        "group": "音频层", "hidden": True,
        "tip": "L3 音频指纹差异化，None 不叠加。",
    },
    # ── 扩展特效（星星点 / 人脸漂浮水印） ──
    {
        "key": "sparkle", "label": "若隐若现星星点", "type": "dict", "control": "group",
        "group": "扩展特效（星星点 / 人脸漂浮水印）", "default": None,
        "tip": "叠加带呼吸闪烁的星点/光点，几乎不可察觉但在帧级特征上增加差异化。",
        "fields": [
            {"key": "enabled", "label": "开启星星点", "type": "bool", "control": "switch", "default": False},
            {"key": "count", "label": "光点数量", "type": "number", "control": "number", "min": 1, "max": 8, "step": 1, "default": 3},
            {"key": "size", "label": "光点大小", "type": "number", "control": "number", "min": 1, "max": 6, "step": 1, "default": 3},
            {"key": "opacity", "label": "峰值亮度", "type": "number", "control": "slider", "min": 1, "max": 40, "step": 1, "default": 10},
        ],
    },
    {
        "key": "face_watermark", "label": "人脸漂浮水印", "type": "dict", "control": "group",
        "group": "扩展特效（星星点 / 人脸漂浮水印）", "default": None,
        "tip": "跟随人脸移动的极淡水印（复用人脸检测引擎），人脸位置变化时水印随之漂浮。",
        "fields": [
            {"key": "enabled", "label": "开启人脸漂浮水印", "type": "bool", "control": "switch", "default": False},
            {"key": "text", "label": "水印文字", "type": "string", "control": "text", "default": "W", "max_len": 10},
            {"key": "opacity", "label": "透明度", "type": "number", "control": "slider", "min": 0.02, "max": 0.3, "step": 0.01, "default": 0.08},
            {"key": "font_size", "label": "字号", "type": "number", "control": "number", "min": 12, "max": 60, "step": 1, "default": 24},
        ],
    },
]


# 档位列表（中文名 + 描述）。value 与 DEDUPE_PRESETS 键一一对应。
DEDUPE_PRESET_META = [
    {"value": "std_crop_desat", "label": "保守裁切降饱和（推荐）",
     "desc": "默认配方：裁切+变速+轻微降饱和，画面几乎无感，查重风险最低。"},
    {"value": "std_retro_scan", "label": "复古扫描",
     "desc": "还原老电视扫描线+噪点质感（复古暖调+噪点+扫描线+暗角）。"},
    {"value": "light", "label": "轻", "desc": "画质优先，轻微处理。"},
    {"value": "standard", "label": "标准", "desc": "均衡去重强度。"},
    {"value": "heavy", "label": "重", "desc": "更强去重，画质影响稍大。"},
]


def _resolve_engines_dir() -> str:
    """解析引擎目录绝对路径（与 workers._resolve_engines_dir 一致）。"""
    p = os.path.abspath(settings.ENGINES_DIR)
    return p


def _load_dedupe_presets() -> dict:
    """以只读方式从 engines/slice.py 提取 DEDUPE_PRESETS 权威值。

    采用 AST 静态解析（DEDUPE_PRESETS 为纯字面量 dict），不执行整个引擎脚本，
    避免触发 OpenCV 等可选依赖。解析失败时回退为空 dict（接口仍返回字段定义，
    前端可继续展示）。
    """
    engine_path = os.path.join(_resolve_engines_dir(), DEDUPE_ENGINE_FILE)
    try:
        with open(engine_path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=engine_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "DEDUPE_PRESETS":
                        return ast.literal_eval(node.value)
    except Exception as exc:  # pragma: no cover - 引擎文件缺失/语法变更时的兜底
        logger.warning("读取 DEDUPE_PRESETS 失败，接口回退空默认：%s", exc)
    return {}


def _dedupe_presets_payload() -> dict:
    """组装 GET /dedupe/presets 的响应体。"""
    defaults = _load_dedupe_presets()
    # 档位列表按 DEDUPE_PRESETS 实际存在的键收敛（后端新增档位自动出现在前端）
    presets = [m for m in DEDUPE_PRESET_META if m["value"] in defaults]
    return {
        "presets": presets,
        "fields": DEDUPE_FIELD_DEFS,
        "defaults": defaults,
    }


@router.get("/dedupe/presets")
def get_dedupe_presets(
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """去重配置单一来源接口：返回档位列表 + 字段定义 + 每档全量默认参数。"""
    return _dedupe_presets_payload()


@router.post("/dedupe/upload")
async def upload_dedupe_video(
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """批量文件拖入入口：上传一个视频到服务器本地临时目录。

    返回 {path, file_name, file_size, content_type}。前端用 path 组装
    batch-slice/run 的 episodes[].path 触发切片，切片完成后变体逻辑走
    variants/generate-batch。
    """
    file_name = file.filename or ""
    try:
        safe_name = validate_file_name(file_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    upload_id = uuid.uuid4().hex
    os.makedirs(DEDUPE_UPLOAD_DIR, exist_ok=True)
    local_path = os.path.join(DEDUPE_UPLOAD_DIR, f"{upload_id}_{safe_name}")

    size = 0
    try:
        with open(local_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.UPLOAD_MAX_SIZE:
                    out.close()
                    os.unlink(local_path)
                    raise HTTPException(status_code=413, detail="文件超过大小上限")
                out.write(chunk)
    except Exception:
        if os.path.isfile(local_path):
            try:
                os.unlink(local_path)
            except OSError:
                pass
        raise

    if size == 0:
        os.unlink(local_path)
        raise HTTPException(status_code=400, detail="文件为空")

    logger.info("去重处理上传完成 path=%s size=%s user=%s", local_path, size,
                getattr(current_user, "username", None))
    return {
        "path": local_path,
        "file_name": safe_name,
        "file_size": size,
        "content_type": file.content_type or "video/mp4",
    }
