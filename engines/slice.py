#!/usr/bin/env python3
"""ffmpeg-based slice engine for Clip Workflow.

Usage:
  slice.py <source> <cutlist> <output_dir> --mode fast|dedupe|scrub [--intervals FILE] [--watermark JSON]

Cutlist format (per line):  start end name   (HH:MM:SS.mmm times)
Interval format (per line): start end

Prints OUTPUT:<name>:<duration> and PROGRESS:<pct> lines to stdout.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

# 允许导入同目录下的竖屏转横屏引擎（vert2horiz_crop.py 依赖 OpenCV）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import vert2horiz_crop
except ImportError:  # pragma: no cover - OpenCV 未安装时动态模式不可用
    vert2horiz_crop = None

# 去重扩展特效（三方向：星星点/小光环 sparkle、mask 加速、人脸跟踪水印）。
# 与 vert2horiz_crop 一样做可选导入，OpenCV/依赖缺失时特效自动禁用，不影响既有链路。
try:
    from dedupe_effects import build_sparkle_filter, build_face_watermark_filter
except ImportError:  # pragma: no cover
    build_sparkle_filter = None
    build_face_watermark_filter = None

# ── sparkle 生产安全开关（与 backend/app/services/variant_service.py 的
#    _SPARKLE_ENABLED 对齐）──
# sparkle 走 ffmpeg geq 全分辨率渲染约 0.5fps，1080p 竖屏 + 多光点会把切片任务
# 拖到超时/进程被杀（2026-08-20 实测 8 个 geq 让 ffmpeg 卡 6.5h+、2 个僵尸进程
# 卡 13h）。生产默认关闭：即使 dedupe_config.manual 传入 sparkle 也被强制忽略。
SPARKLE_ENABLED = False  # 生产默认关闭；True 时 manual.sparkle 生效（测试/受控使用）


# 引擎使用了 PEP 604 联合类型（str | None 等），要求 Python 3.10+。
# 版本检查必须放在任何 def 之前（注解在模块加载时求值，低版本会抛
# "unsupported operand type(s) for |" 的 TypeError，误导排查）。
# 快速失败 + 明确报错，避免在错误版本下运行到一半才炸。
if sys.version_info < (3, 10):
    sys.stderr.write(
        f"[slice.py] 需要 Python 3.10+（当前 {sys.version_info.major}.{sys.version_info.minor}），"
        f"引擎使用了 PEP 604 联合类型（str | None）。\n"
        f"请用 Python 3.10+ 运行（如: SLICE_PYTHON=/usr/local/bin/python3 或调整 worker PATH）。\n"
    )
    sys.exit(1)


# 默认 CPU 资源分配比例（%）：切片时限制 ffmpeg 编码线程数，避免占满整机 CPU
DEFAULT_CPU_PERCENT = 50


# ──────────────────────────────────────────────
# 去重（老电视质感）滤镜链：轻/标准/重 三档
# ──────────────────────────────────────────────
# 去重不是堆得越多越好，而是"空间 + 时域 + 色彩 + 质感"四层组合，
# 让成品与原素材在帧级特征、色彩直方图、时域指纹三个维度同时拉开距离。
# 老电视效果本质是质感层，同时天然改变亮度（扫描线）、噪点结构（颗粒）、色调
# （复古偏色），本身即是一种很「润」的去重手段。
#
# 每档参数：
#   crop      空间层：相对裁切比例（裁掉四周后缩放回原尺寸，改像素对齐/构图）
#   hflip     空间层：是否水平镜像（直接破坏帧哈希）
#   speed     时域层：变速系数（改时长与帧对齐）
#   saturation/gamma/contrast/brightness  色彩层：降饱和 + 复古调色
#   colorbalance / colortemperature       色彩层：复古偏色（暖黄/冷调）
#   noise     质感层：颗粒噪点强度（alls，时域+空域）
#   scanline  质感层：扫描线（drawgrid h 间隔 / 黑条透明度）
#   vignette  质感层：暗角角度
#   roll_band 质感层：滚动暗带强度（0 关闭）
#   jitter    质感层：画面微抖动（0 关闭）
#   sharpen   质感层：锐化/降噪强度（unsharp 亮度锐化量，0 关闭）
#   watermark 质感层：叠加半透明贴纸水印（dict 或 None；见 build_dedupe_watermark）
#
# 手动配置：调用方可传入 manual 覆盖字典（可单独覆盖上述任一字段，
# 不指定时沿用 preset 预设值），实现"所有去重手段均可手动配置"。
DEDUPE_PRESETS = {
    # 画质优先：所有默认档位统一不做镜像（hflip=False），并将明显影响画质的
    # 效果（颗粒噪点 noise / 扫描线 scanline / 复古偏色 colorbalance /
    # 暖冷色温 colortemperature / 暗角 vignette / 滚动暗带 roll_band / 抖动 jitter）
    # 去掉或降到最低值。保留对画面影响小但同样能拉低查重风险的手段：
    # 轻微裁切 crop / 变速 speed / 轻微降饱和 saturation / 轻微亮度与锐化。
    "light": {
        "crop": 0.02,
        "hflip": False,
        "speed": 1.02,
        "saturation": 0.92,
        "gamma": 1.02,
        "contrast": 1.01,
        "brightness": 0.005,
        "colorbalance": "rs=0:gs=0:bs=0:rm=0:gm=0:bm=0",
        "colortemperature": "temperature=6500",
        "noise": 0,
        "scanline": None,
        "vignette": None,
        "roll_band": 0,
        "jitter": 0,
        "sharpen": 0,
        "watermark": None,
        "audio": None,  # 音频指纹差异化（L3），None 不叠加，仅多版本变体使用
        "sparkle": None,  # 方向一：若隐若现星星点/小光环（dict 或 None，None 关闭）
        "face_watermark": None,  # 方向三：人脸跟踪漂浮淡色水印（dict 或 None，None 关闭）
    },
    "standard": {
        "crop": 0.03,
        "hflip": False,
        "speed": 1.03,
        "saturation": 0.88,
        "gamma": 1.02,
        "contrast": 1.02,
        "brightness": 0.008,
        "colorbalance": "rs=.02:gs=.01:bs=-.02:rm=.02:gm=.01:bm=-.02",
        "colortemperature": "temperature=6400",
        "noise": 1,
        "scanline": None,
        "vignette": None,
        "roll_band": 0,
        "jitter": 0,
        "sharpen": 0.4,
        "watermark": None,
        "audio": None,  # 音频指纹差异化（L3），None 不叠加，仅多版本变体使用
        "sparkle": None,  # 方向一：若隐若现星星点/小光环（dict 或 None，None 关闭）
        "face_watermark": None,  # 方向三：人脸跟踪漂浮淡色水印（dict 或 None，None 关闭）
    },
    "heavy": {
        "crop": 0.05,
        "hflip": False,
        "speed": 1.05,
        "saturation": 0.84,
        "gamma": 1.03,
        "contrast": 1.03,
        "brightness": 0.012,
        "colorbalance": "rs=.03:gs=.02:bs=-.03:rm=.03:gm=.02:bm=-.03",
        "colortemperature": "temperature=6300",
        "noise": 2,
        "scanline": None,
        "vignette": None,
        "roll_band": 0,
        "jitter": 0,
        "sharpen": 0.6,
        "watermark": None,
        "audio": None,  # 音频指纹差异化（L3），None 不叠加，仅多版本变体使用
        "sparkle": None,  # 方向一：若隐若现星星点/小光环（dict 或 None，None 关闭）
        "face_watermark": None,  # 方向三：人脸跟踪漂浮淡色水印（dict 或 None，None 关闭）
    },
    # 实测推荐的配方（对原画面影响最小 + 平台查重风险最低），无镜像。
    # 默认配方切为 std_crop_desat（保守裁切降饱和）：裁切 + 变速 + 轻微降饱和，
    #   画面几乎无感，把明显影响画质的噪点/扫描线/偏色/色温/暗角均去掉或降到最低。
    "std_crop_desat": {
        "crop": 0.05,
        "hflip": False,
        "speed": 1.03,
        "saturation": 0.90,
        "gamma": 1.02,
        "contrast": 1.02,
        "brightness": 0.008,
        "colorbalance": "rs=0:gs=0:bs=0:rm=0:gm=0:bm=0",
        "colortemperature": "temperature=6500",
        "noise": 0,
        "scanline": None,
        "vignette": None,
        "roll_band": 0,
        "jitter": 0,
        "sharpen": 0.3,
        "watermark": None,
        "audio": None,  # 音频指纹差异化（L3），None 不叠加，仅多版本变体使用
        "sparkle": None,  # 方向一：若隐若现星星点/小光环（dict 或 None，None 关闭）
        "face_watermark": None,  # 方向三：人脸跟踪漂浮淡色水印（dict 或 None，None 关闭）
    },
    # std_retro_scan 复古扫描（第二选择，非默认）：还原老电视扫描线+噪点质感——
    #   复古暖调（偏色+色温5800）+ 噪点 + 扫描线 + 暗角，适合追求复古出片质感的场景。
    #   默认仍是 std_crop_desat（画质优先），本档位保留作为手动选择的第二档。
    "std_retro_scan": {
        "crop": 0.05,
        "hflip": False,
        "speed": 1.04,
        "saturation": 0.85,
        "gamma": 1.03,
        "contrast": 1.03,
        "brightness": 0.01,
        "colorbalance": "rs=.06:gs=.03:bs=-.06:rm=.06:gm=.03:bm=-.06",
        "colortemperature": "temperature=5800",
        "noise": 7,
        "scanline": {"h": 3, "color": "black@0.10"},
        "vignette": "PI/5",
        "roll_band": 0,
        "jitter": 0,
        "sharpen": 0.4,
        "watermark": None,
        "audio": None,  # 音频指纹差异化（L3），None 不叠加，仅多版本变体使用
        "sparkle": None,  # 方向一：若隐若现星星点/小光环（dict 或 None，None 关闭）
        "face_watermark": None,  # 方向三：人脸跟踪漂浮淡色水印（dict 或 None，None 关闭）
    },
}


def _even(n: int) -> int:
    """把整数收敛为偶数（保证 yuv420p 编码时宽高为偶数）。"""
    n = int(n)
    if n < 2:
        return 2
    return n if n % 2 == 0 else n - 1


def _resolve_dedupe_config(cfg: dict) -> dict:
    """解析去重配置，返回合并后的完整参数 dict。

    cfg 支持：
      - preset: "light|standard|heavy"（基础档位）或推荐配方
        "std_crop_desat"（默认/首选，保守裁切降饱和）/ "std_retro_scan"，作为基础档位；
      - manual: 手动覆盖字典，可覆盖四层中任一手段参数（crop/hflip/speed/
        saturation/gamma/contrast/brightness/colorbalance/colortemperature/
        noise/scanline/vignette/roll_band/jitter/sharpen/watermark）。

    未指定 manual 时沿用 preset 预设值，实现"所有去重手段均可手动配置"。
    兼容旧式扁平配置：manual 为空时仍优先读取 cfg 顶层同名字段作为覆盖。
    """
    cfg = cfg or {}
    preset = str(cfg.get("preset") or "std_crop_desat").lower()
    if preset not in DEDUPE_PRESETS:
        preset = "std_crop_desat"
    p = dict(DEDUPE_PRESETS[preset])  # 以预设为基础

    # 手动覆盖字典优先
    manual = cfg.get("manual")
    if not isinstance(manual, dict):
        manual = {}
    # 兼容旧式扁平配置（把顶层同名字段也作为覆盖，manual 优先）
    for key in list(p.keys()):
        if key in cfg and key != "preset":
            manual.setdefault(key, cfg[key])

    # 应用手动覆盖
    for key, val in manual.items():
        if key in p:
            p[key] = val
    return p


def build_dedupe_filter(cfg: dict, width: int = 0, height: int = 0, framerate: str = "", source_path: str = "") -> tuple[str, str]:
    """根据去重配置构造 (vf, af) 滤镜链。

    cfg 支持 preset（light/standard/heavy 基础档位，或推荐配方 std_crop_desat/
    std_retro_scan）与 manual（每项手段手动覆盖），
    四层组合：空间（缩放裁切 + 可选镜像）、时域（变速）、色彩（降饱和 + 复古偏色 + 轻微亮度）、
    质感（噪点 / 扫描线 / 暗角 / 滚动暗带 / 画面抖动 / 锐化 / 贴纸水印）。
    默认档位为 std_crop_desat（保守裁切降饱和）：统一不做镜像，明显影响画质的
    噪点/扫描线/复古偏色/色温/暗角/滚动暗带/抖动均去掉或降到最低值。

    width/height 用于在裁切后缩放回原始分辨率（保持输出尺寸一致）；未提供或为 0 时
    仅做相对裁切（轻微改变分辨率，同样有效）。

    framerate：源视频帧率（ffmpeg fps 参数形式，如 '30000/1001'）。变速会压缩视频
    PTS 但不会自动调整帧率，若不在 setpts 后追加 fps 重采样，ffmpeg 会按原帧率重新
    对齐帧并丢帧，使视频实际变速比例偏离 speed，与音频 atempo 产生漂移、音画逐渐
    不同步。传入源帧率并在 setpts 后追加 fps 即可把视频时间轴拉回与音频精确一致。
    未提供/未知时回退为旧行为（不追加 fps）。
    """
    p = _resolve_dedupe_config(cfg or {})

    crop = float(p["crop"])
    speed = float(p["speed"])

    # 空间层：裁切（改构图/像素对齐），有原始分辨率则缩放回原尺寸
    if width > 0 and height > 0:
        cw = _even(width * (1.0 - crop))
        ch = _even(height * (1.0 - crop))
        spatial = f"crop={cw}:{ch},scale={width}:{height}"
    else:
        spatial = f"crop=iw*{1.0 - crop:.4f}:ih*{1.0 - crop:.4f}"
    if p["hflip"]:
        spatial += ",hflip"

    # 时域层：变速（视频 setpts 与音频 atempo 需一一对应）。
    # setpts 只压缩 PTS 不改帧率；变速后需用 fps 按源帧率重采样帧，否则视频实际
    # 变速比例偏离 speed、与音频 atempo 漂移导致音画不同步（见函数 docstring）。
    vf_parts = [spatial, f"setpts=PTS/{speed:.3f}"]
    if speed != 1.0 and framerate:
        vf_parts.append(f"fps={framerate}")
    af = f"atempo={speed:.3f}"

    # 音频层（L3 盲区覆盖）：在 atempo 之后追加音频指纹差异化滤镜。
    # 仅用于多视频号素材去重的变体生成；普通去重模式 manual.audio 为空则不叠加。
    af_extra = build_dedupe_audio_filter(p.get("audio"))
    if af_extra:
        af = f"{af},{af_extra}"

    # 色彩层：降饱和 + 复古调色 + 轻微亮度
    vf_parts.append(
        f"eq=saturation={p['saturation']}:gamma={p['gamma']}"
        f":contrast={p['contrast']}:brightness={p['brightness']}"
    )
    vf_parts.append(f"colorbalance={p['colorbalance']}")
    vf_parts.append(f"colortemperature={p['colortemperature']}")

    # 质感层：颗粒噪点（时域+空域，老电视颗粒感；>0 才叠加，0 不引入颗粒）
    if float(p["noise"] or 0) > 0:
        vf_parts.append(f"noise=alls={p['noise']}:allf=t+u")

    # 质感层：扫描线（每 N px 一条 1px 暗线）
    if p["scanline"]:
        h = p["scanline"]["h"]
        color = p["scanline"]["color"]
        vf_parts.append(f"drawgrid=w=iw:h={h}:t=1:color={color}")

    # 质感层：暗角（老电视边缘压暗）
    if p["vignette"]:
        vf_parts.append(f"vignette=angle={p['vignette']}")

    # 质感层：滚动暗带（上下缓慢滚动的亮度条带，重档开启）
    if p["roll_band"]:
        band = float(p["roll_band"])
        vf_parts.append(f"geq=lum='lum(X,Y)-{band}*sin(2*PI*T*0.4+2*PI*Y/H)'")

    # 质感层：画面微抖动（正弦摆动裁切后缩放回原尺寸，重档开启）
    if p["jitter"]:
        j = float(p["jitter"])
        if width > 0 and height > 0:
            cw = _even(width - 2 * j)
            ch = _even(height - 2 * j)
            vf_parts.append(
                f"crop={cw}:{ch}:x='{j}+{j}*sin(2*PI*t*3)':y='{j}+{j}*cos(2*PI*t*2)'"
                f",scale={width}:{height}"
            )
        else:
            vf_parts.append(
                f"crop=iw-{int(2*j)}:ih-{int(2*j)}"
                f":x='{j}+{j}*sin(2*PI*t*3)':y='{j}+{j}*cos(2*PI*t*2)'"
            )

    # 质感层：锐化/降噪（unsharp，微调画质细节差异；0 关闭）
    sharpen = float(p.get("sharpen") or 0)
    if sharpen > 0:
        vf_parts.append(f"unsharp=5:5:{sharpen:.2f}:5:5:0.0")

    # 质感层：贴纸水印叠加（半透明标识，去重差异化；None 关闭）
    wm = p.get("watermark")
    if wm:
        wm_filter = build_dedupe_watermark(wm, width, height)
        if wm_filter:
            vf_parts.append(wm_filter)

    # ── 扩展特效层（三方向，均默认关闭，可选开启） ──
    # 方向一：若隐若现星星点/小光环（sparkle）。复用 dedupe_effects 生成带正弦
    #   呼吸透明度的光点 sprite 叠加，几乎不可察觉，却在帧级特征上增加差异化。
    # 生产安全：SPARKLE_ENABLED=False 时强制忽略 manual.sparkle（geq 0.5fps 会
    #   把 1080p 切片拖到超时/进程被杀，2026-08-20 实测卡 6.5h+）。
    sparkle = p.get("sparkle")
    if (SPARKLE_ENABLED and isinstance(sparkle, dict) and sparkle.get("enabled")
            and build_sparkle_filter is not None):
        eff_parts = build_sparkle_filter(sparkle, width=width, height=height)
        if eff_parts:
            vf_parts.extend(eff_parts)

    # 方向三：人脸跟踪 + 动态漂浮淡色水印（face_watermark）。
    #   复用 vert2horiz_crop.FaceDetector 算出脸中心轨迹，用 drawtext 跟随漂浮。
    face_wm = p.get("face_watermark")
    if (isinstance(face_wm, dict) and face_wm.get("enabled") and source_path
            and build_face_watermark_filter is not None):
        fw_filter = build_face_watermark_filter(
            face_wm, source_path, width=width, height=height
        )
        if fw_filter:
            vf_parts.append(fw_filter)

    return ",".join(vf_parts), af


def build_dedupe_audio_filter(mode) -> str:
    """构造音频指纹差异化滤镜（L3 盲区覆盖）。

    模式（mode）：
      - None / "" / "none"：不叠加（默认，普通去重保持不变）。
      - "volume"：音量增益（默认 1.28，改变响度分布；此前 1.12 实测音频距离不稳超 0.15）。
      - "eq_mild"：中频 EQ（提升/压低），改变频谱指纹。
      - "eq_strong"：更强 EQ（多频段均衡），频谱指纹差异更明显。
      - "pitch" / "pitch_down"：降调（asetrate+aresample），改音高/节奏指纹。
      - "pitch_up"：升调（asetrate+aresample）。
      - "bandpass"：带通滤波（切除极低/极高），改频谱包络。
      - "bass_boost"：低频增强 + 高频衰减。
      - "vocal_boost"：人声带通增强（350Hz~9kHz 带通 + 1.8kHz 人声带提升）。
    返回空字符串表示不叠加。
    """
    if not mode:
        return ""
    m = str(mode).lower()
    if m in ("none", "null"):
        return ""
    if m == "volume":
        return "volume=1.28"
    if m == "eq_mild":
        return ("equalizer=f=2500:t=q:w=0.8:g=5,equalizer=f=400:t=q:w=0.8:g=-3,"
                "equalizer=f=8000:t=q:w=0.8:g=2")
    if m == "eq_strong":
        return ("equalizer=f=300:t=q:w=0.6:g=7,equalizer=f=1000:t=q:w=0.6:g=-5,"
                "equalizer=f=3500:t=q:w=0.7:g=6,equalizer=f=8000:t=q:w=0.6:g=-4,"
                "equalizer=f=12000:t=q:w=0.6:g=3")
    if m in ("pitch", "pitch_down"):
        # 降调加深（0.90 → 0.85）并叠轻 EQ：安静音轨频谱区分度提升，实测音频距离稳定过 0.15。
        return ("asetrate=44100*0.85,aresample=44100,"
                "equalizer=f=2000:t=q:w=0.8:g=4,equalizer=f=200:t=q:w=0.8:g=-2")
    if m == "pitch_up":
        # 升调对称加深（1.12 → 1.18，与降调 0.85 互为镜像），同样叠轻 EQ 拉开频谱指纹。
        return ("asetrate=44100*1.18,aresample=44100,"
                "equalizer=f=2000:t=q:w=0.8:g=4,equalizer=f=200:t=q:w=0.8:g=-2")
    if m == "bandpass":
        return "highpass=f=150,lowpass=f=8000"
    if m == "bass_boost":
        return ("equalizer=f=120:t=q:w=0.8:g=8,equalizer=f=5000:t=q:w=0.8:g=-4")
    if m == "vocal_boost":
        return ("highpass=f=350,lowpass=f=9000,equalizer=f=1800:t=q:w=0.7:g=7,"
                "equalizer=f=6000:t=q:w=0.7:g=-4")
    return ""


def build_dedupe_watermark(wm: dict, width: int = 0, height: int = 0) -> str:
    """构造去重贴纸水印 filter（drawtext，半透明静态/缓慢漂移标识）。

    与动态文字水印（build_watermark_filter）区别：贴纸水印作为去重手段，
    默认静态固定在角落（避免遮挡内容），可配置透明度/字号/位置；
    仅叠加文字标识，无背景图（如需图片贴纸走 --badges 角标通道）。
    """
    if not isinstance(wm, dict):
        return ""
    text = wm.get("text") or "Clip"
    font_size = int(wm.get("font_size") or 28)
    opacity = float(wm.get("opacity") or 0.25)
    position = (wm.get("position") or "bottom-right").lower()
    drift = bool(wm.get("drift", False))  # 是否缓慢漂移（默认静态）

    opacity = max(0.05, min(0.9, opacity))
    font_size = max(12, min(120, font_size))
    font_opt = _resolve_drawtext_font()

    # 位置 -> x/y 坐标表达式（带 10px 外边距）
    pos_map = {
        "top-left": ("20", "30"),
        "top-right": ("w-tw-20", "30"),
        "top-center": ("(w-tw)/2", "30"),
        "bottom-left": ("20", "h-th-40"),
        "bottom-right": ("w-tw-20", "h-th-40"),
        "bottom-center": ("(w-tw)/2", "h-th-40"),
        "center": ("(w-tw)/2", "(h-th)/2"),
    }
    if position not in pos_map:
        position = "bottom-right"
    x_expr, y_expr = pos_map[position]

    if drift:
        # 缓慢漂移（8px/s），增强时序差异化
        x_expr = f"({x_expr})+mod({10}*t\,{40})-{20}"

    text_esc = text.replace("\\", "\\\\").replace(";", "\\;")
    return (
        f"drawtext={font_opt}:text='{text_esc}':fontcolor=white@{opacity:.2f}"
        f":fontsize={font_size}:x='{x_expr}':y='{y_expr}'"
    )


def cpu_threads_for_percent(percent: int) -> int:
    """根据 CPU 分配比例计算 ffmpeg 使用的线程数（至少 1，最多为 CPU 核心数）。

    算法：threads = max(1, round(cores * percent / 100))，
    例如 8 核 + 50%% => 4 线程，8 核 + 100%% => 8 线程。
    """
    if percent <= 0:
        percent = DEFAULT_CPU_PERCENT
    if percent > 100:
        percent = 100
    try:
        cores = os.cpu_count() or 1
    except Exception:
        cores = 1
    n = int(round(cores * percent / 100.0))
    if n < 1:
        n = 1
    if n > cores:
        n = cores
    return n


def parse_time(s: str) -> float:
    parts = s.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def read_cutlist(path: str):
    cuts = []
    if not path or not os.path.isfile(path):
        return cuts
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                cuts.append((parse_time(parts[0]), parse_time(parts[1]), parts[2]))
            except ValueError:
                continue
    return cuts


def read_intervals(path: str):
    intervals = []
    if not path or not os.path.isfile(path):
        return intervals
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                intervals.append((parse_time(parts[0]), parse_time(parts[1])))
            except ValueError:
                continue
    return intervals


def subtract_intervals(cuts, intervals):
    """Remove interval overlaps from each cut.

    Returns segments as (start, end, name, cut_index).
    """
    segments = []
    for idx, (s, e, name) in enumerate(cuts):
        segs = [(s, e)]
        for is_, ie in intervals:
            if is_ >= e or ie <= s:
                continue
            new = []
            for a, b in segs:
                if is_ <= a and ie >= b:
                    continue
                if is_ > a:
                    new.append((a, min(is_, b)))
                if ie < b:
                    new.append((max(ie, a), b))
            segs = new
        for a, b in segs:
            segments.append((a, b, name, idx))
    return segments


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


def ffprobe_resolution(path: str) -> tuple[int, int]:
    """探测视频分辨率 (width, height)，失败返回 (0, 0)。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        parts = out.stdout.split()
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 0, 0


def ffprobe_framerate(path: str) -> str:
    """探测源视频帧率（返回 ffmpeg fps 参数形式，如 '30000/1001'），失败返回 ''。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        fr = (out.stdout or "").strip()
        if "/" in fr:
            num, den = fr.split("/", 1)
            try:
                n, d = float(num), float(den)
                if n > 0 and d > 0:
                    return fr
            except ValueError:
                pass
        try:
            val = float(fr)
        except ValueError:
            return ""
        if val <= 0:
            return ""
        return f"{val:.6f}"
    except Exception:
        return ""


def ffprobe_size(path: str) -> tuple[int, int]:
    """读取视频分辨率 (width, height)，失败返回 (0, 0)。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        line = (out.stdout or "").strip().splitlines()
        if line:
            parts = line[0].split(",")
            if len(parts) >= 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                return int(parts[0].strip()), int(parts[1].strip())
    except Exception:
        pass
    return 0, 0


def _fallback_libx264_args(args, threads):
    """把命令中的硬件编码器（videotoolbox/nvenc）替换为完整的软件 libx264 编码参数。

    不采用"只替换编码器名 + 跳过硬件专属质量参数"的做法——因为：
    - 跳过的 opt+value 里可能残留硬件专属参数（-preset p5 / -cq 23），libx264 不识别会报
      -22 Invalid argument（163 无 GPU 回退后仍失败即源于此）；
    - 只留 `-c:v libx264` 会让 libx264 缺 -preset，参数不完整。

    因此这里重建一组完整的 libx264 参数（-preset veryfast -crf 23），保证回退稳定。

    返回替换后的命令列表；若命令中没有可识别的硬件编码器则返回 None。
    """
    try:
        i = args.index("-c:v")
    except ValueError:
        return None
    enc = args[i + 1]
    hw = ("h264_videotoolbox", "hevc_videotoolbox", "h264_nvenc", "hevc_nvenc")
    if enc not in hw:
        return None
    # 跳过 -c:v <enc> 之后的硬件专属质量参数（opt+value 对），直到遇到下一个独立选项
    #（如 -c:a / -vf / -af）或输出文件。硬件质量选项均带一个值，逐对跳过即可。
    VALUE_OPTS = {"-q:v", "-preset", "-cq", "-crf", "-b:v", "-maxrate", "-bufsize"}
    j = i + 2
    while j < len(args):
        tok = args[j]
        if tok.startswith("-"):
            if tok in VALUE_OPTS:
                j += 2  # 跳过 opt + value
                continue
            break  # 遇到非质量选项（如 -c:a），停止
        j += 1
    # 重建完整的软件 libx264 编码参数（含 -preset），替换整段硬件编码块 [-c:v enc <opts>]，
    # 避免硬件专属参数（-preset p5 / -cq 23）残留或缺 -preset 导致 libx264 报 -22。
    libx264_block = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
    return list(args)[:i] + libx264_block + list(args)[j:]


def run_ffmpeg(args, timeout=3600, threads=1):
    # 若未显式设置 -threads，则追加（避免并发切片抢占过多 CPU）。
    # 注意：args 以 "ffmpeg" 可执行文件开头，插入必须放在可执行文件之后，
    # 否则 args[0] 变成 "-threads" 会被 subprocess 当作可执行文件
    # （FileNotFoundError: No such file or directory: '-threads'）。
    if "-threads" not in args:
        if args and args[0] == "ffmpeg":
            args = [args[0], "-threads", str(threads)] + list(args[1:])
        else:
            args = ["-threads", str(threads)] + list(args)
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode != 0:
        stderr_txt = proc.stderr.decode(errors="replace")
        # 硬件编码器（videotoolbox/nvenc）探测时可得，但运行时可能不可用
        # （设备忙/不支持，报 -12908 等），自动回退软件 libx264 重试一次，
        # 避免字幕打码等滤镜重编码步骤在 Mac 上静默失败（与 burn_subtitle 一致）。
        sw_args = _fallback_libx264_args(args, threads)
        if sw_args is not None:
            print("[FFMPEG] 硬件编码器运行失败，回退软件 libx264 重试", file=sys.stderr)
            proc2 = subprocess.run(sw_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            if proc2.returncode == 0:
                return proc2
            # 回退也失败：合并硬件原命令与回退命令两侧的 stderr，报错信息更清晰
            sw_stderr = proc2.stderr.decode(errors="replace")
            raise RuntimeError(
                "ffmpeg failed (硬件编码器与 libx264 回退均失败)\n"
                f"原命令 stderr: {stderr_txt[-1200:]}\n"
                f"回退命令 stderr: {sw_stderr[-1200:]}"
            )
        raise RuntimeError("ffmpeg failed: " + stderr_txt[-2000:])
    return proc


def _encoder_runtime_ok(enc: str) -> bool:
    """运行时验证编码器是否真的可用：实际编码 1 帧测试帧。

    仅查 `ffmpeg -encoders` 静态列表不可靠：无 NVIDIA GPU/驱动时 nvenc 仍会被列出，
    但运行时必然失败（-22 Invalid argument）。软件 libx264 无驱动依赖，直接放行。
    """
    if not enc or enc == "libx264":
        return True
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1:r=1",
        "-frames:v", "1", "-c:v", enc,
        "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def detect_best_encoder(preferred: str | None = None) -> str:
    """探测可用的最佳编码器。

    三期 GPU 加速编码：优先使用硬件编码器（nvenc/hevc_videotoolbox），不可用则回退
    到软件 libx264。

    三重保障，避免无 GPU 机器（163）上 nvenc 探测通过但运行时必失败：
    1. SLICE_ENCODER 环境变量可**强制**指定编码器（如 libx264），部署在无 GPU 机器时直接覆盖探测；
    2. 硬件编码器探测后额外做**运行时编码测试**（实际编码 1 帧），失败即跳过该编码器；
    3. 最终兜底软件 libx264。
    """
    # 1) 配置强制覆盖：SLICE_ENCODER 显式指定时优先采用（需静态存在）
    try:
        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15,
        )
        encoders = probe.stdout or ""
    except Exception:
        encoders = ""
    force = os.environ.get("SLICE_ENCODER", "").strip()
    if force:
        if force in encoders and _encoder_runtime_ok(force):
            return force
        print(f"[slice.py] SLICE_ENCODER={force} 不可用（未安装或无 GPU/驱动），忽略，继续自动探测", file=sys.stderr)

    # 2) 运行时验证 + 自动探测
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates += ["hevc_videotoolbox", "h264_videotoolbox", "h264_nvenc", "hevc_nvenc", "libx264"]
    seen = set()
    for enc in candidates:
        if enc in seen:
            continue
        seen.add(enc)
        if enc not in encoders:
            continue
        # 软件编码直接采用；硬件编码需通过运行时编码测试（无 GPU 时跳过，避免运行时必失败）
        if enc == "libx264" or _encoder_runtime_ok(enc):
            return enc
        print(f"[slice.py] 编码器 {enc} 运行时不可用（无 GPU/驱动），跳过", file=sys.stderr)
    return "libx264"


def build_encoder_args(encoder: str, threads: int) -> list[str]:
    """根据编码器构造 ffmpeg 编码参数."""
    if encoder in ("h264_nvenc", "hevc_nvenc"):
        return ["-c:v", encoder, "-preset", "p5", "-cq", "23"]
    if encoder in ("h264_videotoolbox", "hevc_videotoolbox"):
        return ["-c:v", encoder, "-q:v", "65"]
    # 软件编码回退
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", str(threads)]


def slice_segment(src, start, end, out, vf=None, af=None, threads=1, encoder="libx264", copy_if_possible=True):
    # fast 模式且无滤镜时走流拷贝（-c copy），只切不重编码，速度 10×+；
    # 需要滤镜（去重/水印/竖转横）或显式关闭时回退到重编码分支。
    copy_mode = bool(copy_if_possible and not vf and not af)
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(threads),
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src,
    ]
    if copy_mode:
        cmd += ["-c", "copy", "-movflags", "+faststart"]
    else:
        cmd += build_encoder_args(encoder, threads)
        cmd += ["-c:a", "aac", "-b:a", "128k"]
        if vf:
            cmd += ["-vf", vf]
        if af:
            cmd += ["-af", af]
    cmd.append(out)
    run_ffmpeg(cmd, timeout=3600, threads=threads)


def concat_segments(parts, out, threads=1, encoder="libx264", copy_if_possible=True):
    if len(parts) == 1:
        # 单段时无需重新编码（水印已在 slice_segment 阶段叠加）
        shutil.move(parts[0], out)
        return
    # 多段：若各段均为 copy 产出（同编码/分辨率/时基），用 concat demuxer 免重编码拼接
    if copy_if_possible and all(_is_copy_segment(p) for p in parts):
        _concat_demuxer(parts, out)
        return
    filter_complex = "".join(
        f"[{i}:v][{i}:a]" for i in range(len(parts))
    ) + f"concat=n={len(parts)}:v=1:a=1[v][a]"
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(threads),
    ]
    for part in parts:
        cmd += ["-i", part]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
    ]
    cmd += build_encoder_args(encoder, threads)
    cmd += ["-c:a", "aac", "-b:a", "128k", out]
    run_ffmpeg(cmd, threads=threads)


def _is_copy_segment(path: str) -> bool:
    """粗略判断片段是否为流拷贝产出（封装格式 mp4 即可；copy 片段编码/时基一致）。"""
    try:
        return os.path.getsize(path) > 0 and path.lower().endswith(".mp4")
    except OSError:
        return False


def _concat_demuxer(parts, out):
    """用 ffmpeg concat demuxer + -c copy 免重编码拼接多段。"""
    list_file = out + ".concat.txt"
    with open(list_file, "w") as f:
        for p in parts:
            # ffmpeg concat demuxer：单引号内用 '\'' 转义内嵌单引号，路径含引号也能安全解析
            escaped = p.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    try:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", "-movflags", "+faststart", out]
        run_ffmpeg(cmd, timeout=3600)
    finally:
        try:
            os.unlink(list_file)
        except OSError:
            pass


def safe_name(name: str) -> str:
    name = os.path.basename(name)
    if not name.endswith(".mp4"):
        name += ".mp4"
    return name


# 角标位置到 overlay x/y 坐标表达式的映射
# 位置以视频宽高为基准（W/H），角标宽高以 scale 后的 overlay 图为准（w/h）
# {O} 为角标到视频边缘的偏移量占位符，运行时会替换为具体像素值（默认 10）
BADGE_POSITIONS = {
    # 左上 / 中上 / 右上 / 最左侧(中左) / 左下 / 中下 / 右下
    "top-left":      ("{O}", "{O}"),
    "top-center":    ("(W-w)/2", "{O}"),
    "top-right":     ("W-w-{O}", "{O}"),
    "left":          ("{O}", "(H-h)/2"),
    "bottom-left":   ("{O}", "H-h-{O}"),
    "bottom-center": ("(W-w)/2", "H-h-{O}"),
    "bottom-right":  ("W-w-{O}", "H-h-{O}"),
}

# 角标默认偏移量（px，未指定时使用）
BADGE_DEFAULT_OFFSET = 10
# 角标默认宽度（px，未指定且未设置宽度时使用；0 表示保持原图尺寸）
BADGE_DEFAULT_WIDTH = 0
# 角标默认透明度（0~1，未指定时使用）
BADGE_DEFAULT_OPACITY = 1.0


def _badge_scale_and_opacity(badge: dict, default_width: int) -> str:
    """构造单个角标的 scale + 透明度 filter 链。

    默认尺寸：优先使用角标自身 width；否则回退到调用方传入的 default_width；
    再否则保持原图尺寸。透明度通过 colorchannelmixer 的 aa（alpha）通道实现。
    """
    try:
        width = int(badge.get("width") or 0)
    except (TypeError, ValueError):
        width = 0
    if width <= 0:
        width = int(default_width or 0)
    scale = f"scale={width}:-1" if width > 0 else "null"

    try:
        opacity = float(badge.get("opacity") or BADGE_DEFAULT_OPACITY)
    except (TypeError, ValueError):
        opacity = BADGE_DEFAULT_OPACITY
    opacity = min(1.0, max(0.0, opacity))

    chain = scale
    if opacity < 1.0:
        # rgba 保证有 alpha 通道后再调节透明度
        chain += f",format=rgba,colorchannelmixer=aa={opacity:.3f}"
    else:
        chain += ",format=rgba"
    return chain


def build_badges_overlay_args(
    badges: list,
    threads: int,
    encoder: str,
    default_width: int = BADGE_DEFAULT_WIDTH,
) -> list[str]:
    """构造在成品视频上叠加多角标的 ffmpeg 命令参数（-filter_complex 多输入）。

    返回完整的 ffmpeg 参数（含 -y、主视频输入、各角标 -i、filter_complex、
    overlay 叠加、编码输出到 -o）。调用方只需追加输出路径。
    角标全程叠加在视频指定位置上（不随时间消失），支持多角标。

    每个角标支持：position（六角位置）、width（宽度，px）、offset（到边缘偏移，px）、
    opacity（透明度 0~1）。default_width 为所有角标的默认宽度（角标未单独设 width 时生效）。
    """
    # 校验角标图片存在
    valid = []
    for badge in badges:
        path = badge.get("path") or ""
        if path and os.path.isfile(path):
            valid.append(badge)
    if not valid:
        return []

    # 构造 filter_complex
    parts = []
    num = len(valid)
    for i, badge in enumerate(valid):
        position = (badge.get("position") or "top-left").lower()
        if position not in BADGE_POSITIONS:
            position = "top-left"
        chain = _badge_scale_and_opacity(badge, default_width)
        parts.append(f"[{i + 1}:v]{chain}[badge{i}]")

    current = "[0:v]"
    for i in range(num):
        position = (valid[i].get("position") or "top-left").lower()
        if position not in BADGE_POSITIONS:
            position = "top-left"
        x_template, y_template = BADGE_POSITIONS[position]
        try:
            offset = int(valid[i].get("offset") or BADGE_DEFAULT_OFFSET)
        except (TypeError, ValueError):
            offset = BADGE_DEFAULT_OFFSET
        offset = max(0, offset)
        x_expr = x_template.replace("{O}", str(offset))
        y_expr = y_template.replace("{O}", str(offset))
        out_label = f"[vout{i}]" if i < num - 1 else "[vout]"
        current = f"{current}[badge{i}]overlay=x={x_expr}:y={y_expr}:shortest=0{out_label}"
    parts.append(current)
    filter_complex = ";".join(parts)

    # 返回 ["-i", badge1, "-i", badge2, ..., "-filter_complex", fc, "-map", "[vout]", 编码参数]
    # 调用方在开头追加 -i <主视频>
    args = []
    for badge in valid:
        args += ["-i", badge["path"]]
    args += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a?",
        "-c:a", "aac", "-b:a", "128k",
    ]
    args += build_encoder_args(encoder, threads)
    return args


def apply_badges(src, out, badges, threads=1, encoder="libx264", default_width: int = BADGE_DEFAULT_WIDTH):
    """对成品视频执行一次角标 overlay 叠加，产出新文件。"""
    badge_args = build_badges_overlay_args(badges, threads, encoder, default_width=default_width)
    if not badge_args:
        # 无有效角标，直接复制
        shutil.copy(src, out)
        return
    cmd = ["ffmpeg", "-y", "-threads", str(threads), "-i", src] + badge_args + [out]
    run_ffmpeg(cmd, timeout=3600, threads=threads)


# ──────────────────────────────────────────────
# 固定文字叠加（角标文字版：最左侧 / 左下角 / 右上角）
# ──────────────────────────────────────────────

# 固定文字位置到 drawtext x/y 坐标表达式的映射。
# 坐标以输出视频宽高为基准（w/h 为视频宽高，tw/th 为文本块宽高）。
# {O} 为文字到视频边缘的偏移量占位符，运行时会替换为具体像素值（默认 10）。
# "left" 为最左侧（画面左侧垂直居中，竖排文字）。
TEXT_OVERLAY_POSITIONS = {
    "top-left":     ("{O}", "{O}"),
    "top-center":   ("(w-tw)/2", "{O}"),
    "top-right":    ("w-tw-{O}", "{O}"),
    "left":         ("{O}", "(h-th)/2"),
    "bottom-left":  ("{O}", "h-th-{O}"),
    "bottom-center":("(w-tw)/2", "h-th-{O}"),
    "bottom-right": ("w-tw-{O}", "h-th-{O}"),
}

# 固定文字默认偏移量（px）
TEXT_OVERLAY_DEFAULT_OFFSET = 10
# 固定文字默认字号（px）
TEXT_OVERLAY_DEFAULT_FONT_SIZE = 36
# 固定文字默认颜色（CSS 十六进制，白字）
TEXT_OVERLAY_DEFAULT_COLOR = "#FFFFFF"
# 固定文字默认描边颜色（深色描边，保证任意背景下清晰）
TEXT_OVERLAY_DEFAULT_BORDER_COLOR = "#000000"


# 中文字体候选（容器内通常装有 font-noto-cjk / wqy 等）
# 注意：这里只放单字体文件（.ttf/.otf）。Noto CJK / wqy-zenhei 的 .ttc 是字体集合，drawtext
# 用 fontfile 引用时会默认加载集合里第一个子字体（往往是 JP 日文字形），导致简体字（如"门"）
# 渲染成日式/异常字形，因此 .ttc 一律不放进来、统一走下方 fontconfig 的 font= 精确匹配。
_TEXT_SINGLE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttf",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
# 仅当没有任何单字体文件时才考虑 ttc 集合（配合 fontconfig FontName 精确匹配简体中文）
_TEXT_TTC_CANDIDATES = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
]

# 用 fc-match 动态解析 Noto Sans CJK SC 真实路径，避免依赖写死的发行版路径（Debian/Alpine 布局不同）。
_FCMATCH_CMD = "fc-match"
# 提取出的 SC 单字体缓存（避免每次调用都重复解析/提取）
_SC_FONTFILE_CACHE = {"path": None}


# 只有当 fc-match 解析到的 family 命中这些 CJK 简体中文字体时才可信。
# 关键：fc-match 找不到目标字体时不会报错/返回空，而是回退到“最接近”的字体
# （如 DejaVu / Droid），此时返回的 file 路径虽存在但**不是**简体中文字体——
# 直接用它 fontfile= 会导致“门”等简体字渲染成异常/缺字字形。
# 所以必须同时校验 family 名称，命中 CJK SC 才信任其 file 路径。
_SC_FAMILY_HINTS = (
    "noto sans cjk sc",
    "noto sans cjk",          # 含 SC 子字体的大集合
    "source han sans sc",
    "source han serif sc",
    "wenquanyi",               # 文泉驿（含简中）
    "wqy",
    "cjk",
    # 注意：不带 Droid Sans Fallback——实测其“门”(U+95E8) 为异常/次选字形，
    # 不可信任，避免再次把“门”渲染错。
)


def _fc_match_sc_font() -> str:
    """用 fontconfig 的 fc-match 动态解析 "Noto Sans CJK SC" 的真实字体路径。

    自适应 Debian/Alpine 等不同发行版，返回匹配字体的绝对路径；无 fc-match、
    匹配失败、或解析到的 family **不是 CJK 简体中文字体**时返回空串。
    通过缓存避免重复调用外部进程。

    核心防护：fc-match 找不到目标字体时会回退到任意“最接近”字体（如 DejaVu），
    其 file 路径存在但渲染不了简体中文，直接使用会导致“门”字异常。因此这里
    额外校验 family 名称，只信任命中 CJK 简体中文字体的结果。
    """
    if _SC_FONTFILE_CACHE["path"] is not None:
        return _SC_FONTFILE_CACHE["path"]
    try:
        # 一次拿回 file 与 family，family 用于校验是否真的是简体中文字体
        proc = subprocess.run(
            [_FCMATCH_CMD, "-f", "%{file}\t%{family}\n", "Noto Sans CJK SC"],
            capture_output=True, text=True, timeout=5,
        )
        line = (proc.stdout or "").strip().splitlines()
        if not line:
            _SC_FONTFILE_CACHE["path"] = ""
            return ""
        parts = line[0].split("\t")
        file_path = parts[0].strip() if parts else ""
        family = (parts[1] if len(parts) > 1 else "").lower()
        if file_path and os.path.isfile(file_path) and any(h in family for h in _SC_FAMILY_HINTS):
            _SC_FONTFILE_CACHE["path"] = file_path
            return file_path
    except (OSError, subprocess.SubprocessError):
        pass
    _SC_FONTFILE_CACHE["path"] = ""
    return ""


def _extract_sc_face(ttc_path: str) -> str:
    """把 Noto CJK .ttc 集合里的 SC 简体中文字面提取成独立单字体 .ttf。

    drawtext 用 fontfile 引用 .ttc 时会默认加载第一个子字体（往往是 JP 日文字形），
    导致简体字"门"等渲染成日式/异常字形。方案 C：用 fontTools 把 SC face 单独提取成
    单字体 .ttf，彻底绕开 fontconfig 的 face 选择歧义。提取产物缓存在系统临时目录，
    一次提取后续复用。依赖 fonttools（backend/slice-worker 镜像均已安装）。
    """
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        return ""
    cache_key = os.path.join(tempfile.gettempdir(),
                             "NotoSansCJKsc-Regular-" + str(abs(hash(ttc_path))) + ".ttf")
    if os.path.isfile(cache_key):
        return cache_key
    try:
        # 遍历 .ttc 集合里所有 face，挑出包含 "SC"/"Simplified" 的简体中文字面
        sc_index = None
        num_fonts = TTFont(ttc_path, fontNumber=0, lazy=True).reader.numFonts
        for i in range(num_fonts):
            try:
                f2 = TTFont(ttc_path, fontNumber=i, lazy=True)
                nm = f2["name"]
                combined = "".join(
                    (nm.getDebugName(n) or "").lower()
                    for n in (1, 4, 6) if nm.getDebugName(n)
                )
                # 精确匹配 "cjk sc" / "cjksc"（PostScript 名 notosanscjksc-Regular）。
                # 旧逻辑用 "sc" in combined 会误命中所有 face——因为 "cjk" 包含子串 "sc"
                # （c**sc**jk），导致永远选到第一个 face[0]=JP 而非真正的 SC face。
                if ("cjk sc" in combined or "cjksc" in combined
                        or "simplified chinese" in combined
                        or "simplified" in combined):
                    sc_index = i
                    break
            except Exception:
                continue
        if sc_index is None:
            return ""
        sc_font = TTFont(ttc_path, fontNumber=sc_index, lazy=True)
        sc_font.save(cache_key)
        return cache_key if os.path.isfile(cache_key) else ""
    except Exception:
        try:
            if os.path.isfile(cache_key):
                os.unlink(cache_key)
        except OSError:
            pass
        return ""


def _fontconfig_has_cjk_sc() -> bool:
    """判断 fontconfig 是否真的能解析到 CJK 简体中文字体（用于 font= 兜底）。

    仅检查 family 是否存在可用字体，不关心具体 file 路径；避免依赖写死的
    ttc 路径。命中则说明 ffmpeg 的 drawtext font= 可用 fontconfig 精确匹配。
    """
    try:
        proc = subprocess.run(
            [_FCMATCH_CMD, "-f", "%{family}\n", "Noto Sans CJK SC"],
            capture_output=True, text=True, timeout=5,
        )
        fam = ((proc.stdout or "").strip().splitlines() or [""])
        fam = fam[0].lower() if fam else ""
        return any(h in fam for h in _SC_FAMILY_HINTS)
    except (OSError, subprocess.SubprocessError):
        return False


def _resolve_drawtext_font() -> str:
    """返回 drawtext 的字体参数片段。

    B+C 结合方案：
      B) 优先用 fc-match 动态解析 "Noto Sans CJK SC" 真实字体路径（自适应 Debian/Alpine），
         命中即用 fontfile= 精确加载该字体（含正确的"门"字形）。
      C) fc-match 解析到的若是 .ttc 集合，则用 fontTools 提取 SC face 为单字体 .ttf
         再加载，彻底绕开 ttc 默认加载日文子字体、避免"门"渲染成日式/异常字形。
    兜底：单字体候选 / fontconfig font=Noto Sans CJK SC。
    """
    # ① B：fc-match 动态解析 Noto Sans CJK SC 真实路径
    sc_path = _fc_match_sc_font()
    if sc_path and os.path.isfile(sc_path):
        # ② C：若命中 .ttc 集合，提取 SC face 为单字体再加载（绕开 face 选择歧义）
        if sc_path.lower().endswith(".ttc"):
            single = _extract_sc_face(sc_path)
            if single:
                return f":fontfile={single}"
            # 提取失败（镜像未装 fontTools 等）：不能回退 fontfile=.ttc——
            # drawtext 加载 .ttc 默认取第一个子字体（JP 日文字形），"门"等简体字
            # 会渲染成日式/异常字形。改走 fontconfig font= 精确匹配 SC face。
            return ":font=Noto Sans CJK SC"
        return f":fontfile={sc_path}"
    # ③ 兜底 A：有 Noto CJK 集合时用 fontconfig font= 精确匹配简体中文
    if _fontconfig_has_cjk_sc() or any(os.path.isfile(f) for f in _TEXT_TTC_CANDIDATES):
        return ":font=Noto Sans CJK SC"
    # ④ 兜底 B：单字体文件
    _text_fontfile = next((f for f in _TEXT_SINGLE_FONT_CANDIDATES if os.path.isfile(f)), "")
    if _text_fontfile:
        return f":fontfile={_text_fontfile}"
    return ""


def _build_text_overlays_filter(text_overlays: list) -> str:
    """构造固定文字的 drawtext filter 链（叠加在视频上）。

    每个元素支持：
      - text: 文字内容（必填）
      - position: 位置（left 最左侧 / bottom-left 左下角 / top-right 右上角 等七位）
      - font_size: 字号（px，可选，默认 36）
      - color: 字体颜色（CSS #RRGGBB，可选，默认白）
      - border_color: 描边颜色（CSS #RRGGBB，可选，默认黑）
      - vertical: 是否竖排（仅 left 位置常用，可选，默认 False）
      - offset: 到边缘偏移（px，可选，默认 10）
    返回 drawtext filter 段（多个用逗号连接），空列表返回空串。
    """
    filters = []
    for ov in text_overlays:
        if not ov:
            continue
        text = ov.get("text") or ""
        if not text:
            continue
        position = (ov.get("position") or "bottom-left").lower()
        if position not in TEXT_OVERLAY_POSITIONS:
            position = "bottom-left"
        try:
            font_size = int(ov.get("font_size") or TEXT_OVERLAY_DEFAULT_FONT_SIZE)
        except (TypeError, ValueError):
            font_size = TEXT_OVERLAY_DEFAULT_FONT_SIZE
        font_size = max(12, min(200, font_size))
        try:
            offset = int(ov.get("offset") or TEXT_OVERLAY_DEFAULT_OFFSET)
        except (TypeError, ValueError):
            offset = TEXT_OVERLAY_DEFAULT_OFFSET
        offset = max(0, offset)
        vertical = bool(ov.get("vertical"))

        font_opt = _resolve_drawtext_font()
        # drawtext 的 fontcolor/border 用 0xRRGGBB 十六进制，最可靠。
        # 把 CSS 色值（#RRGGBB / #RGB）统一转为 0xRRGGBB。
        c_hex = _css_to_drawtext(ov.get("color") or TEXT_OVERLAY_DEFAULT_COLOR)
        b_hex = _css_to_drawtext(ov.get("border_color") or TEXT_OVERLAY_DEFAULT_BORDER_COLOR)

        x_tpl, y_tpl = TEXT_OVERLAY_POSITIONS[position]
        x_expr = x_tpl.replace("{O}", str(offset))
        y_expr = y_tpl.replace("{O}", str(offset))

        # 转义 drawtext 特殊字符（冒号/反斜杠/分号/单引号）
        esc = text.replace("\\", "\\\\").replace(":", "\\:").replace(";", "\\;").replace("'", "\\\\'")

        if vertical:
            # 竖排文字：把文字逐字符叠加（drawtext 无原生竖排，用多个 drawtext 逐字下排）
            chars = list(text)
            n = len(chars)
            sub_filters = []
            # 竖排整块高度 = 字符数 × 字号，需按整块高度垂直居中，
            # 否则 (h-th)/2 只居中了第一个字符，整列文字会整体偏上、无法居中。
            for k, ch in enumerate(chars):
                ch_esc = ch.replace("\\", "\\\\").replace(":", "\\:").replace(";", "\\;").replace("'", "\\\\'")
                sub_filters.append(
                    f"drawtext={font_opt}:text='{ch_esc}':fontcolor={c_hex}"
                    f":bordercolor={b_hex}:borderw=2:fontsize={font_size}"
                    f":x={x_expr}:y='(h-{n}*{font_size})/2+{k}*{font_size}'"
                )
            filters.append(",".join(sub_filters))
        else:
            filters.append(
                f"drawtext={font_opt}:text='{esc}':fontcolor={c_hex}"
                f":bordercolor={b_hex}:borderw=2:fontsize={font_size}"
                f":x={x_expr}:y={y_expr}"
            )
    return ",".join(filters)


def apply_text_overlays(src, out, text_overlays, threads=1, encoder="libx264"):
    """对成品视频执行一次固定文字叠加，产出新文件。

    text_overlays 为空或全无效时直接复制源文件，不做重编码。
    """
    valid = [o for o in (text_overlays or []) if o and (o.get("text") or "").strip()]
    if not valid:
        shutil.copy(src, out)
        return
    vf = _build_text_overlays_filter(valid)
    cmd = [
        "ffmpeg", "-y", "-threads", str(threads), "-i", src,
        "-vf", vf,
        "-map", "0:v:0", "-map", "0:a:0?",
    ]
    cmd += build_encoder_args(encoder, threads)
    cmd += ["-c:a", "aac", "-b:a", "128k", out]
    run_ffmpeg(cmd, timeout=3600, threads=threads)


def build_watermark_filter(wm: dict) -> str:
    """构造 ffmpeg 动态文字水印 filter（drawtext）。

    支持多种“形态/运动样式”（style），每种形态决定水印在画面中的
    位置 + 运动轨迹 + 可选特效，未指定或非法时回退到默认横滚 scroll。

    可用表达式变量：t（秒）、w/h（画面宽高）、tw/th（文本宽高）。

    形态一览：
      - scroll 横滚（默认）：底部/顶部水平匀速横滚 + 透明度呼吸（原效果）
      - float  斜漂：横向滚动 + 纵向缓慢上下漂移，动态更丰富、避开主体
      - wave   波浪：水平滚动 + 正弦上下浮动，更有节奏感
      - bounce 折返：左右往返折返游走，适合高频发布防查重
      - breath 呼吸：固定居中，透明度明暗脉动，低调常驻不干扰画面
      - blink  闪现：固定位置定时闪现（每 4s 亮 0.7s），定时提醒式水印
    """
    text = wm.get("text") or "Clip Workflow"
    font_size = int(wm.get("font_size") or 28)
    opacity = float(wm.get("opacity") or 0.5)
    position = (wm.get("position") or "bottom").lower()
    style = (wm.get("style") or "scroll").lower()
    if position not in ("top", "bottom"):
        position = "bottom"

    opacity = max(0.05, min(1.0, opacity))
    font_size = max(12, min(120, font_size))

    # 字体：与固定文字共用同一套解析逻辑（优先单字体 .ttf/.otf；无单字体时用
    # fontconfig 的 font=Noto Sans CJK SC 精确匹配简体中文，避免 .ttc 集合默认加载
    # 第一个日文子字体，导致"门"等简体字渲染成日式/异常字形）。
    font_opt = _resolve_drawtext_font()

    # 转义 filter 特殊字符：后端已转义过冒号/逗号，这里再处理反斜杠与分号
    text = text.replace("\\", "\\\\").replace(";", "\\;")

    # 位置基准：横滚/斜漂/波浪/折返在顶部或底部游走；呼吸/闪现固定位置。
    base_y = "40" if position == "top" else "h-th-40"

    # 按形态生成 x/y/alpha 表达式
    x_expr, y_expr, alpha_expr = _watermark_style_exprs(style, base_y)

    return (
        f"drawtext={font_opt}:text='{text}':fontcolor=white@{opacity:.2f}"
        f":fontsize={font_size}:x='{x_expr}':y='{y_expr}':alpha='{alpha_expr}'"
    )


def _watermark_style_exprs(style: str, base_y: str) -> tuple[str, str, str]:
    """按形态生成 drawtext 的 (x, y, alpha) 表达式（内部 helper）。

    style 非法时回退到 scroll。
    """
    s = (style or "scroll").lower()
    if s == "float":
        # 横向匀速横滚 + 纵向缓慢上下漂移（正弦，幅度约 40px，周期 12s）
        return (
            "mod(2*t\\,w+tw)-tw",
            f"{base_y}+40*sin(PI*t/6)",
            "0.4+0.3*sin(2*PI*t)",
        )
    if s == "wave":
        # 水平滚动 + 正弦上下浮动（幅度约 30px，周期 5s）
        return (
            "mod(2*t\\,w+tw)-tw",
            f"{base_y}+30*sin(2*PI*t/5)",
            "0.4+0.3*sin(2*PI*t)",
        )
    if s == "bounce":
        # 左右往返折返游走（三角波，周期 8s）
        return (
            "abs(mod(2*t/8\\,2)-1)*(w-tw)",
            base_y,
            "0.4+0.3*sin(2*PI*t)",
        )
    if s == "breath":
        # 固定居中，透明度明暗脉动（呼吸感，周期 3s）
        return (
            "(w-tw)/2",
            "(h-th)/2",
            "0.35+0.35*sin(2*PI*t/3)",
        )
    if s == "blink":
        # 固定位置，定时闪现：每 4s 亮 0.7s（用阶跃函数逼近“亮/暗”）
        return (
            "(w-tw)/2",
            base_y,
            "if(lt(mod(t\\,4)\\,0.7)\\,1\\,0.1)",
        )
    # 默认 scroll：底部/顶部水平匀速横滚 + 透明度呼吸（原效果）
    return (
        "mod(2*t\\,w+tw)-tw",
        base_y,
        "0.4+0.3*sin(2*PI*t)",
    )


# ──────────────────────────────────────────────
# 字幕烧录（ASR 识别后叠加到成品视频）
# ──────────────────────────────────────────────

# 字幕字号（相对输出高度比例，横屏基准）
# 默认 0.06→FontSize 约 6%（横屏 1280x720→43px、1920x1080→65px）；用户实测 0.055 仍偏小，再提一档。
# 竖屏视频因显式设置 PlayResY 抵消了 libass 默认的放大，ASR 字幕会偏小，
# 故对竖屏按下方 PORTRAIT_SUBTITLE_HEIGHT_RATIO 补偿（见 burn_subtitle）。
# 用户可通过配置调大或调小。
SUBTITLE_FONT_RATIO = 0.06
# 竖屏字幕目标字号占画面高度比例：0.05→1080x1920 时 FontSize≈96px、720x1280 时≈64px，
# 竖屏手机全屏观看字幕需更醒目，约 5% 画面高度清晰可读且不挡脸。仅作用于走默认字号的竖屏视频。
PORTRAIT_SUBTITLE_HEIGHT_RATIO = 0.05
# 字幕字间距（ASS Spacing，单位像素）。默认 -2 为字体原生字距基础上的轻微收紧；
# 用户实测字距偏宽，已将半角标点归一化、更负 Spacing 等间距实验复原，保留字体原生全角标点字距。
SUBTITLE_SPACING = -2
# 字幕距底边距离（相对输出高度比例，越小越贴近画面底部；用户反馈原 0.08 偏高，调低到 0.05 更贴底）
SUBTITLE_BOTTOM_RATIO = 0.05

# 字幕样式：默认（白字黑边 + 半透明黑底）与自定义（可选字体/边框色，无底色）
SUBTITLE_STYLE_DEFAULT = "default"
SUBTITLE_STYLE_CUSTOM = "custom"
# 字幕字体粗细：默认不加粗（Bold=0）；用户可设 -1 或 1 加粗，让字幕文字更醒目
SUBTITLE_BOLD_DEFAULT = 0


def css_hex_to_ass(color: Optional[str]) -> str:
    """把 CSS 十六进制颜色（#RRGGBB）转为 libass 使用的 &HBBGGRR 格式。

    例如 #FFFFFF → &H00FFFFFF，#FF0000 → &H000000FF。
    解析失败或为空时返回 None，由调用方回退到默认值。
    """
    if not color:
        return ""
    c = str(color).strip().lstrip("#")
    if len(c) == 3:  # 简写 #RGB
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return ""
    try:
        r = int(c[0:2], 16)
        g = int(c[2:4], 16)
        b = int(c[4:6], 16)
    except ValueError:
        return ""
    # libass 颜色为 &HAABBGGRR（高位 alpha，后续依次 BGR）
    return f"&H00{b:02X}{g:02X}{r:02X}"


def _css_to_drawtext(color: Optional[str]) -> str:
    """把 CSS 十六进制颜色（#RRGGBB / #RGB）转为 drawtext 使用的 0xRRGGBB 格式。

    例如 #EDD736 → 0xEDD736，#fff → 0xFFFFFF。解析失败返回白色。
    """
    if not color:
        return "0xFFFFFF"
    c = str(color).strip().lstrip("#")
    if len(c) == 3:  # 简写 #RGB
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return "0xFFFFFF"
    try:
        int(c, 16)
    except ValueError:
        return "0xFFFFFF"
    return f"0x{c.upper()}"


def _parse_srt_timestamp(ts: str) -> float:
    """解析 SRT 时间戳 "HH:MM:SS,mmm" 为秒。"""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _format_srt_timestamp(seconds: float) -> str:
    """把秒格式化为 SRT 时间戳 "HH:MM:SS,mmm"。"""
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000.0))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def read_srt(path: str) -> list[dict]:
    """解析 SRT 文件为有序字幕记录列表 [{start, end, text}]。

    兼容两种格式：
      - 标准 SRT：记录块之间有空行（split("\\n\\n")）。
      - 紧凑 SRT（无空行分隔）：按"序号行 + 时间行"模式退化解析，
        避免仅解析出第 1 条导致打码时间轴严重缺失。
    """
    records = []
    if not path or not os.path.isfile(path):
        return records
    try:
        with open(path, encoding="utf-8-sig") as f:
            content = f.read()
    except OSError:
        return records
    content = content.replace("\r\n", "\n")
    # 按空行分块
    blocks = [b for b in content.split("\n\n") if b.strip()]
    if len(blocks) <= 1 and "-->" in content and len(content.splitlines()) >= 4:
        # 紧凑格式：整份内容可能只有一块，退化为按行切分：
        # 每条记录 = [可选序号行] + 时间行 + 文本行...
        compact_records = []
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        i = 0
        while i < len(lines):
            # 跳过纯数字序号行
            if lines[i].isdigit():
                i += 1
            if i >= len(lines):
                break
            if "-->" not in lines[i]:
                i += 1
                continue
            time_line = lines[i]
            i += 1
            text_parts = []
            while i < len(lines) and not lines[i].isdigit() and "-->" not in lines[i]:
                text_parts.append(lines[i])
                i += 1
            try:
                left, right = time_line.split("-->", 1)
                start = _parse_srt_timestamp(left)
                end = _parse_srt_timestamp(right)
                if end <= start:
                    end = start + 1.0
                compact_records.append({
                    "start": start, "end": end,
                    "text": " ".join(text_parts),
                })
            except ValueError:
                continue
        if compact_records:
            return compact_records
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # 找到时间行（含 -->）
        time_idx = None
        for i, ln in enumerate(lines):
            if "-->" in ln:
                time_idx = i
                break
        if time_idx is None:
            continue
        time_line = lines[time_idx]
        try:
            left, right = time_line.split("-->", 1)
        except ValueError:
            continue
        start = _parse_srt_timestamp(left)
        end = _parse_srt_timestamp(right)
        text = " ".join(lines[time_idx + 1:])
        if end <= start:
            end = start + 1.0
        records.append({"start": start, "end": end, "text": text})
    return records


# 语音检测参数：判断"是否有人在说话"的静音阈值与最短静音长度。
# 小于该音量的区间视为静音（无人说话），字幕将不在静音期间显示。
# 阈值 -38dB、最短静音 0.5s（比原 -35dB/0.6s 更灵敏），能识别更多低音量停顿，
# 避免字幕"提早出现/延后消失"。
SILENCE_THRESHOLD_DB = -38.0
# 最短静音时长（秒）：小于该长度的短暂停顿不切断字幕，避免台词因句中换气被频繁闪断。
MIN_SILENCE_SECONDS = 0.5
# 语音窗口边界收缩（秒）：每条字幕在语音窗口基础上前后各收一点，
# 让字幕只贴着说话瞬间显示，不早现不晚退。
SPEECH_EDGE_PADDING = 0.15


def detect_speech_windows(video_path: str,
                         silence_threshold: float = SILENCE_THRESHOLD_DB,
                         min_silence: float = MIN_SILENCE_SECONDS) -> list[tuple]:
    """用 ffmpeg silencedetect 检测源视频的语音（非静音）区间。

    返回有序的 (start, end) 秒级区间列表，仅覆盖有人说话的时间段；
    失败或无法检测时返回 []（调用方回退为不限，即整段都视为说话）。
    """
    if not video_path or not os.path.isfile(video_path):
        return []
    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", (f"silencedetect=noise={silence_threshold}dB:"
                f"d={min_silence}"),
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=3600)
    except Exception:
        return []
    out = proc.stderr.decode(errors="replace")
    if proc.returncode != 0:
        return []

    silence_starts: list[float] = []
    silence_ends: list[float] = []
    for line in out.splitlines():
        if "silence_start:" in line:
            try:
                silence_starts.append(float(line.split("silence_start:")[1].strip()))
            except ValueError:
                pass
        elif "silence_end:" in line:
            try:
                silence_ends.append(float(line.split("silence_end:")[1].strip().split()[0]))
            except ValueError:
                pass
    if not silence_starts:
        # 没有检测到静音，说明全程都在说话 → 返回 None 表示"不裁剪"
        return []

    try:
        duration = ffprobe_duration(video_path)
    except Exception:
        duration = 0.0

    # 把静音区间取并集（ffmpeg 可能会输出相邻/重叠的静音段）
    silences = []
    for s, e in zip(silence_starts, silence_ends):
        silences.append((s, e))
    if len(silence_starts) > len(silence_ends):
        # 结尾静音一直持续到文件结束
        silences.append((silence_starts[-1], duration or silence_starts[-1] + 1.0))
    silences.sort()
    merged_sil = []
    for s, e in silences:
        if merged_sil and s <= merged_sil[-1][1]:
            merged_sil[-1] = (merged_sil[-1][0], max(merged_sil[-1][1], e))
        else:
            merged_sil.append([s, e])

    # 非静音区间 = 相邻静音之间的空隙
    speech = []
    cursor = 0.0
    for s, e in merged_sil:
        if s > cursor + 0.05:
            speech.append((cursor, s))
        cursor = max(cursor, e)
    if duration > 0 and cursor < duration - 0.05:
        speech.append((cursor, duration))
    return speech


def _trim_to_speech(start: float, end: float, speech_windows: list[tuple]) -> list[tuple]:
    """把一段 [start, end]（源时间）裁剪为与说话区间重叠的若干子区间。

    speech_windows 为空表示不裁剪（整段视为说话）。
    每条字幕在语音窗口基础上前后各收缩 SPEECH_EDGE_PADDING 秒，
    让字幕只贴着说话瞬间显示，避免提早出现/延后消失。
    """
    if not speech_windows:
        return [(start, end)]
    pad = SPEECH_EDGE_PADDING
    trimmed = []
    for ws, we in speech_windows:
        s = max(start, ws + pad)
        e = min(end, we - pad)
        if e - s >= 0.05:
            trimmed.append((s, e))
    return trimmed


def _filter_and_align_srt(records: list[dict], seg_start: float, seg_end: float,
                          offset: float, out: list[dict],
                          speech_windows: list[tuple] | None = None,
                          scale: float = 1.0) -> None:
    """从源字幕中截取 [seg_start, seg_end] 区间，时间轴减去 seg_start 再叠加 offset，
    写入 out（用于多子段拼接时的连续时间轴对齐）。

    speech_windows: 可选，源时间坐标下的说话区间；传入后字幕仅在说话期间显示，
    跨越静音的字幕会被切分成多段，静音期间不再残留上一句字幕。

    scale: 输出时间轴缩放因子（>1 表示切片时对视频做了变速压缩，如去重 mode 的
        setpts 变速；源时间 t 对应输出画面时间 t/scale）。默认 1 不缩放（普通/快速模式）。
    """
    speech_windows = speech_windows or []
    for r in records:
        # 与片段有交集的字幕才保留；重叠部分做裁剪
        s = max(r["start"], seg_start)
        e = min(r["end"], seg_end)
        if e <= s:
            continue
        # 按说话区间裁剪：静音期间不显示字幕，避免字幕"一直挂在屏幕上"
        for ts, te in _trim_to_speech(s, e, speech_windows):
            if te - ts < 0.05:
                continue
            out.append({
                "start": (ts - seg_start) / scale + offset,
                "end": (te - seg_start) / scale + offset,
                "text": r["text"],
            })


def build_clip_subtitle(src_srt: str, segments: list[tuple], out_srt: str,
                        speech_windows: list[tuple] | None = None,
                        scale: float = 1.0) -> str:
    """根据一个切片的源时间段列表，从源 SRT 截取并拼接出该切片对应的字幕文件。

    segments: 按拼接顺序排列的源时间段 [(start, end), ...]。
    生成的字幕时间轴从 0 开始（与成品视频一致）。返回 out_srt 路径。

    speech_windows: 可选，源时间坐标下的说话区间；传入后字幕仅在说话期间显示，
    静音/停顿期间字幕自动隐藏（不再"一直出现"）。

    scale: 输出时间轴缩放因子（>1 表示切片时对视频做了变速压缩，如去重 mode 的
        setpts 变速；源时间 t 对应输出画面时间 t/scale）。默认 1 不缩放（普通/快速模式）。
    """
    records = read_srt(src_srt)
    merged = []
    offset = 0.0
    for start, end in segments:
        _filter_and_align_srt(records, start, end, offset, merged, speech_windows, scale)
        offset += max(0.0, (end - start) / scale)
    # 排序并重新编号
    merged.sort(key=lambda r: r["start"])
    # 安全兜底：若语音窗裁剪把切片区间内全部字幕裁掉（语音检测不可靠 / 静音误判 /
    # 或语音窗与字幕时间轴轻微错位），但源 SRT 在本切片区间确有内容，则回退为
    # 「忽略语音窗、直接保留区间内字幕」，避免用户开启 ASR 字幕后整段无字幕
    # （burn_subtitle 会因此跳过烧录，成品完全没字幕）。仅在正常裁剪结果为空时回退，
    # 正常有内容时保持原行为（字幕仅在说话时显示）。
    if not merged and records and segments:
        merged = []
        offset = 0.0
        for start, end in segments:
            _filter_and_align_srt(records, start, end, offset, merged, None, scale)
            offset += max(0.0, (end - start) / scale)
        merged.sort(key=lambda r: r["start"])
    lines = []
    for i, r in enumerate(merged, start=1):
        lines.append(f"{i}\n{_format_srt_timestamp(r['start'])} --> {_format_srt_timestamp(r['end'])}\n{r['text']}\n")
    with open(out_srt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_srt




def burn_subtitle(video_in: str, subtitle_srt: str, video_out: str,
                  threads: int = 1, encoder: str = "libx264",
                  font_ratio: Optional[float] = None,
                  spacing: Optional[int] = None,
                  style: Optional[str] = None,
                  font_color: Optional[str] = None,
                  border_color: Optional[str] = None,
                  margin_v: Optional[int] = None,
                  bold: Optional[int] = None) -> None:
    """用 ffmpeg subtitles filter 把字幕烧录到成品视频。

    带字体、样式与描边，保证中文字幕清晰可读；输出为重新编码的视频。
    font_ratio: 字幕字号（相对输出视频高度的比例，不传用默认值 SUBTITLE_FONT_RATIO）。
    spacing: 字幕字间距（ASS Spacing 像素，不传用默认值 SUBTITLE_SPACING）。
    bold: 字幕字体粗细（ASS Bold，0=不加粗，-1/1=加粗）。不传用默认值 SUBTITLE_BOLD_DEFAULT。
    margin_v: 字幕距底边距离（像素）。不传用默认值 SUBTITLE_BOTTOM_RATIO；
        开启源字幕对齐时传入检测到的打码区域底边到视频底部的像素距离，
        使 ASR 字幕位置与源字幕打码区域重合。
    style: 字幕样式（SUBTITLE_STYLE_DEFAULT=白字黑边+半透明黑底 / SUBTITLE_STYLE_CUSTOM=可
        自定义字体色与边框色，且无底色）。不传用默认样式。
    font_color / border_color: 自定义样式的字体色/边框色（CSS 十六进制 #RRGGBB）。
    注意：字幕烧录涉及逐帧重编码 + subtitles filter，与硬件编码器（nvenc/videotoolbox）
    组合在某些环境会报 "Error while opening encoder"，故这里强制使用 libx264 软件编码，
    保证烧录稳定可靠（烧录通常单次、数据量不大，速度可接受）。
    """
    # 字幕烧录强制用 libx264 软件编码，避免硬件编码器 + subtitles filter 兼容问题
    encoder = "libx264"
    if not os.path.isfile(subtitle_srt) or os.path.getsize(subtitle_srt) == 0:
        # 无字幕内容时直接复制，避免无谓重编码
        shutil.copy(video_in, video_out)
        return
    # 成品分辨率：libass 未指定 PlayResX/PlayResY 时用默认脚本分辨率，会把
    # force_style 里的 MarginV/FontSize 放大（竖屏 1080x1920 约 6.67 倍），导致
    # 对齐到检测打码区域时 margin_v 较大（≥300）字幕被推出屏幕外不可见
    # （"ASR 字幕没有生效"的根因）。这里显式设为实际视频分辨率，让 MarginV 按
    # 1:1 像素坐标生效。
    vw, vh = ffprobe_size(video_in)
    if vw <= 0 or vh <= 0:
        shutil.copy(video_in, video_out)
        return

    # 字幕字号：未指定时用默认值；竖屏视频显式设 PlayResY 后字幕偏小，
    # 按画面高度补偿到 PORTRAIT_SUBTITLE_HEIGHT_RATIO（默认与用户自定义字号均补偿）
    font_ratio = font_ratio if font_ratio is not None else SUBTITLE_FONT_RATIO
    if vh > vw:  # 竖屏：显式 PlayResY 抵消 libass 放大，按画面高度补偿字幕字号
        font_ratio = (vh * PORTRAIT_SUBTITLE_HEIGHT_RATIO) / 100.0
    else:  # 横屏：同样按画面高度占比计算，保证不同分辨率下字幕视觉大小一致
        font_ratio = (vh * SUBTITLE_FONT_RATIO) / 100.0
    # 字幕字间距：未指定时用默认值（默认 0 更紧凑），用户可通过切片配置调节
    spacing = spacing if spacing is not None else SUBTITLE_SPACING
    # 字幕字体粗细：未指定时用默认值（默认不加粗），用户可通过配置调节
    bold = bold if bold is not None else SUBTITLE_BOLD_DEFAULT
    # 字幕距底边距离（像素）：未指定时用默认比例 SUBTITLE_BOTTOM_RATIO（与原实现一致，
    # 按 1000 基准换算成固定像素值）。开启源字幕对齐时由调用方传入打码区域底边到
    # 视频底部的像素距离，使 ASR 字幕默认位置与源字幕打码区域重合。
    if margin_v is None:
        margin_v = int(SUBTITLE_BOTTOM_RATIO * 1000)

    # subtitles filter 需要能定位到字幕文件；路径含特殊字符时需转义冒号/逗号/引号
    srt_esc = (subtitle_srt.replace("\\", "\\\\")
               .replace(":", "\\:").replace(",", "\\,").replace("'", "\\\\'"))
    # 规范写法：subtitles=filename='<path>':force_style='...'
    # 不传 fontfile（不同 ffmpeg 版本对 subtitles filter 的 fontfile 选项支持不一），
    # 改用 libass 的 FontName + 系统 fontconfig（Worker 镜像装有 font-noto-cjk）匹配中文字体。
    # 默认样式：白字 + 黑色粗描边 + 半透明黑底（底色），字号按输出高度比例。
    style = style or SUBTITLE_STYLE_DEFAULT
    if style == SUBTITLE_STYLE_CUSTOM:
        # 自定义模式：可自由选择字体色与边框色，无底色（不使用 BorderStyle=3 的实底方框），
        # 以纯描边（BorderStyle=1）呈现，保证任何背景上字幕都清晰且不遮挡画面。
        primary_colour = css_hex_to_ass(font_color) or "&H00FFFFFF"
        outline_colour = css_hex_to_ass(border_color) or "&H00000000"
        back_colour = "&H00000000"  # 透明，去掉底色
        sub_style = (f"PrimaryColour={primary_colour},OutlineColour={outline_colour}"
                     f",BackColour={back_colour},BorderStyle=1,Outline=2,Shadow=0")
    else:
        primary_colour = "&H00FFFFFF"
        outline_colour = "&H00101010"
        back_colour = "&H80000000"
        sub_style = (f"PrimaryColour={primary_colour},OutlineColour={outline_colour}"
                     f",BackColour={back_colour},BorderStyle=3,Outline=2,Shadow=0")
    sub_filter = (
        f"subtitles=filename='{srt_esc}'"
        f":force_style='PlayResX={vw},PlayResY={vh}"
        f",FontName=Noto Sans CJK SC,FontSize={font_ratio * 100:.0f}"
        f",{sub_style},MarginV={int(margin_v)}"
        f",Spacing={int(spacing)},Bold={int(bold)}'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-threads", str(threads),
        "-i", video_in,
        "-vf", sub_filter,
        "-map", "0:v:0", "-map", "0:a:0?",
    ]
    cmd += build_encoder_args(encoder, threads)
    cmd += ["-c:a", "aac", "-b:a", "128k", video_out]
    run_ffmpeg(cmd, timeout=3600, threads=threads)


# ──────────────────────────────────────────────
# 源视频字幕打码（去片源自带字幕）
# ──────────────────────────────────────────────

# 默认打码区域（相对输出视频宽/高比例）。字幕通常位于画面底部一条横带，
# 无需逐帧检测；固定区域 + SRT 时间轴驱动即可，仅在字幕出现时段生效。
# 注意：实际字幕位置可能不在底部（如居中偏下），开启时引擎会优先用 OpenCV 自动
# 检测字幕真实位置，检测失败才回退到下方默认比例。
SUBTITLE_MASK_WIDTH_RATIO = 0.9
SUBTITLE_MASK_HEIGHT_RATIO = 0.12
SUBTITLE_MASK_BOTTOM_RATIO = 0.02
# 默认打码样式
SUBTITLE_MASK_STYLE_DEFAULT = "delogo"
# 打码样式集合
SUBTITLE_MASK_STYLES = ("delogo", "mosaic", "blur", "gblur", "fill")
# 马赛克缩放后的块大小（px），越大马赛克颗粒越粗
SUBTITLE_MASK_BLOCK = 8
# 模糊滤镜核大小（px）
SUBTITLE_MASK_BLUR_RADIUS = 10  # boxblur 的 chroma_param(radius:1) 上限为 11，12 会越界导致 blur 样式转码失败
# 高斯模糊 sigma（gblur 样式）：sigma 越大越柔和、越能盖住字幕文字。相比 boxblur
# 均匀模糊，gblur 的高斯核更自然、视觉更柔，适合对密集多行对话字幕打码（盖死且
# 不突兀，比马赛克/纯色块自然）。
SUBTITLE_MASK_GBLUR_SIGMA = 20
# 自动检测字幕区域时最多采样的帧数（越多越稳，但越慢）。
# 短剧字幕常出现在多个纵向位置（旁白/对话/偶尔更高处），采样过少会漏掉只在
# 部分时段出现、位置又偏的副字幕带。此处取 24，兼顾稳定性与速度。
SUBTITLE_MASK_DETECT_MAX_FRAMES = 24
# 区域检测的"间歇性"打分参数：对话字幕是间歇出现（说话时才在屏），而固定水印/角标
# 几乎每一帧都在。检测时用"出现频率"区分二者，优先挑间歇出现的字幕带，避免被
# 恒定水印误导而打偏。出现频率越接近 PRESENCE_IDEAL 越加分，越接近 0（无内容）
# 或 1（恒定水印）越减分。
SUBTITLE_MASK_PRESENCE_IDEAL = 0.6
SUBTITLE_MASK_PRESENCE_SLOPE = 2.5
SUBTITLE_MASK_PRESENCE_MIN = 0.3
SUBTITLE_MASK_PRESENCE_MAX = 2.0
# 多横带检测：保留文字簇强度达到最强带该比例的候选横带（0~1，越小能捕获越多
# 副字幕带，但也越容易把背景/角标误检为字幕）。此处取 0.5，覆盖"旁白+对话+
# 高位副字幕"等多条字幕带；上方画面噪声由引擎侧"下半区 sanity 过滤"剔除。
SUBTITLE_MASK_MULTI_RELATIVE = 0.5


def _mask_text_clusters(mask):
    """向量化统计每行的"文字簇"数量（横向连续非零段）。

    字幕文字带区别于人物/背景的关键：一行内会分布多个相互分离的文字笔画簇
    （每个汉字一个簇，簇间有空隙），而人物服装/大块色块往往只有少数连续簇。
    mask: (H, W) 布尔掩码。返回长度为 H 的数组，值为每行文字簇个数。
    """
    import numpy as np
    starts = np.hstack([mask[:, :1], (mask[:, 1:] & ~mask[:, :-1])])
    return starts.sum(axis=1)


def _split_tall_band(y0: int, y1: int, smooth, height: int, max_band_h: int):
    """把过高的字幕横带拆分为多个紧凑子横带，避免"打码区域盖住半屏"。

    单个字幕带高度本应在 1~3 行文字范围内（通常 < 6% 屏高）。但当对话字幕在
    不同时间帧处于不同纵向位置时，cluster_peak 跨帧取最大值会把整段纵向浮动范围
    压成一条很宽的横带（如 y≈1028-1300、h≈272），叠加余量与相邻旁白带合并后
    可覆盖近半屏——这正是用户反馈的"打码区域太大"根因。

    这里按 band 内 smooth（文字簇强度）剖面的局部峰值把宽带拆成多个紧凑子带：
    相邻峰值间的低谷作为切分点。这样每个子带都紧贴一处字幕文字位置，未出现字幕
    的纵向间隙不再被打码，区域总面积大幅下降，且不遗漏任何出现字幕的位置。

    y0, y1: 待拆分的原始横带上下边界。
    smooth: 长度为 height 的文字簇强度剖面。
    height: 画面高度。
    max_band_h: 子带高度上限（超过则不再细分，直接按当前范围作为一段，避免无限递归）。

    返回拆分后的子带 [(y0, y1), ...]，每个子带高度 <= max_band_h（或无法再拆）。
    """
    if y1 - y0 + 1 <= max_band_h:
        return [(y0, y1)]
    band = smooth[y0:y1 + 1]
    peak = float(band.max())
    if peak <= 0:
        return [(y0, y1)]
    # 找带内所有局部峰值（比左右相邻行都强），并记录它们之间的低谷。
    n = len(band)
    peaks = []
    for i in range(1, n - 1):
        if band[i] >= band[i - 1] and band[i] >= band[i + 1] and band[i] > peak * 0.25:
            peaks.append(i)
    if not peaks:
        return [(y0, y1)]
    # 局部峰值聚类：相近的峰值（间距 < 8px）归为同一字幕行。
    groups = []
    cur = [peaks[0]]
    for p in peaks[1:]:
        if p - cur[-1] <= 8:
            cur.append(p)
        else:
            groups.append(cur)
            cur = [p]
    groups.append(cur)
    # 每个峰值簇对应一条字幕文字行，取其代表行（簇内最强）。
    rep = []
    for g in groups:
        gi = max(g, key=lambda i: float(band[i]))
        rep.append(gi)
    rep.sort()
    # 若只有一个字幕行且带过宽，说明是单条粗大文字被平滑扩散，取最强核心裁剪。
    if len(rep) == 1:
        mid = rep[0]
        half = max_band_h // 2
        a2 = max(0, mid - half)
        b2 = min(n - 1, a2 + max_band_h - 1)
        return [(y0 + a2, y0 + b2)]
    # 多字幕行：每行取"实际文字纵向范围 + 小余量"的紧凑子带，而不是固定 max_band_h。
    # 旧实现给每行一个 max_band_h（可达屏高 9%）高的子带，多行相邻时这些大子带互相
    # 重叠、合并回一整条宽带（"打码区域盖住半屏"根因之一），且把低密度旁白字幕与
    # 高密度对话字幕压成同一区域，导致旁白密度被稀释到阈值以下而漏打。这里改为按
    # 局部文字簇剖面峰值的谷值截断，得到紧贴该行文字的子带。
    max_row_h = max(18, int(height * 0.045))
    out = []
    for mi in rep:
        base = float(band[mi])
        if base <= 0:
            continue
        thr = base * 0.30
        a = mi
        while a > 0 and band[a] >= thr:
            a -= 1
        b = mi
        while b < n - 1 and band[b] >= thr:
            b += 1
        # 保证最小高度（容纳单行文字+描边），同时限制最大高度防止无限扩散。
        if b - a + 1 < 26:
            half = 13
            a = max(0, mi - half)
            b = min(n - 1, mi + half)
        if b - a + 1 > max_row_h:
            half = max_row_h // 2
            a = max(0, mi - half)
            b = min(n - 1, mi + half)
        out.append((y0 + a, y0 + b))
    # 合并重叠或极接近（间距 < 10px）的子带，避免同一条字幕被切成两段。
    out.sort()
    merged = []
    cur = list(out[0])
    for (a, b) in out[1:]:
        if a <= cur[1] + 10:
            cur[1] = max(cur[1], b)
        else:
            merged.append((cur[0], cur[1]))
            cur = [a, b]
    merged.append((cur[0], cur[1]))
    return merged


def detect_subtitle_region(video: str, srt: str = "") -> Optional[list[tuple[int, int, int, int]]]:
    """用 OpenCV 从源视频采样帧自动检测字幕文字区域（支持多横带）。

    返回多个区域 [(x, y, w, h), ...]，每个区域已按视频宽高裁剪到边界内；检测失败
    或 OpenCV 不可用时返回 None（由调用方回退到固定比例区域）。

    短剧片源常见"旁白字幕 + 对话字幕 + 上/下固定水印"并存、且分别落在不同纵向
    横带上（旁白在居中偏上、对话在居中偏下、水印贴顶/贴底）。因此这里返回**所有**
    通过打分阈值的横带区域（按强度降序），而不是只挑最强的一条——否则漏掉其余
    位置的对话/旁白字幕导致打码不完整。

    采样时机：有 SRT 时取 SRT 出现的时刻（字幕在场），无 SRT 时均匀采样全程。

    检测原理（文字簇投票，针对金色/黄色等彩色字幕更可靠）：
      旧实现按 Canny 边缘密度找"最高密度横带"，在人物画面里容易被服装/背景的
      密集边缘误导而打偏（尤其金色/黄色字幕在复杂画面上边缘梯度弱）。
      本实现改用"颜色 + 文字簇"判别：
        - 颜色通道：金色/黄色 + 白色/浅色字幕（字幕最常见的两种配色）
        - 文字簇特征：一行内横向分布的独立文字笔画簇数量——字幕文字带总是
          有多个文字簇（每个字一个簇），而人物/装饰大块区域簇数很少。
        - 跨帧累积投票 + 位置偏下优先，对「底部/居中偏下/顶部」任意位置自适应。
    """
    width, height = ffprobe_size(video)
    if width <= 0 or height <= 0:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    # 确定采样时刻
    # 注意：不能用「只取前 N 条 SRT cue」——短剧字幕纵向位置会随时间变化（前期旁白在
    # 居中偏上、后期对话在更低处）。若只采样前 24 条 cue（约前几十秒），后期下移的
    # 字幕带不会被纳入检测，导致"后半段字幕没打码"（用户反馈的核心问题之一）。
    # 因此有 SRT 时在**整份 SRT 的 cue 上均匀采样**（最多 MAX_FRAMES 条，跨全片），
    # 无 SRT 时均匀采样全程，确保各时间段的字幕位置都被覆盖。
    times = []
    records = read_srt(srt) if srt and os.path.isfile(srt) else []
    if records:
        n = len(records)
        n_sample = min(SUBTITLE_MASK_DETECT_MAX_FRAMES, n)
        # 均匀抽取覆盖全片的 cue：从第一条到最后一条线性取 n_sample 个下标
        idxs = [int(round(i * (n - 1) / max(1, n_sample - 1))) for i in range(n_sample)]
        # 去重保序（极端情况下几条 cue 时间相同）
        seen = set()
        chosen = []
        for i in idxs:
            if i not in seen:
                seen.add(i)
                chosen.append(i)
        times = [max(0.0, (float(records[i]["start"]) + float(records[i]["end"])) / 2.0)
                 for i in sorted(chosen)]
    else:
        dur = ffprobe_duration(video)
        if not dur or dur <= 0:
            return None
        n = min(SUBTITLE_MASK_DETECT_MAX_FRAMES, max(6, int(dur)))
        times = [dur * (i + 0.5) / n for i in range(n)]

    cap = None
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        cluster_peak = np.zeros(height, dtype=np.float64)
        dens = np.zeros(height, dtype=np.float64)
        presence = np.zeros(height, dtype=np.float64)
        color_acc = np.zeros((height, width), dtype=np.float64)
        color_peak = np.zeros((height, width), dtype=np.float64)
        frames = 0
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            b = frame[:, :, 0].astype(np.int16)
            g = frame[:, :, 1].astype(np.int16)
            r = frame[:, :, 2].astype(np.int16)
            # 金色/黄色字幕（R 高、G 高、B 低，R/G 接近）
            gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & (g - b > 40) & (abs(r - g) < 110)
            # 白色/浅色字幕
            white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & (abs(g - b) < 45) & (abs(r - b) < 45)
            mask = gold | white
            dens += mask.sum(axis=1)
            cl = _mask_text_clusters(mask)
            # 逐帧最大值：即使字幕只在部分采样帧出现（间歇性对话字幕），其峰值也能被捕捉
            cluster_peak = np.maximum(cluster_peak, cl)
            # 该行在当前帧是否有文字簇内容（用于统计"出现频率"，区分间歇字幕/恒定水印）
            presence += (cl > 3).astype(np.float64)
            color_acc += mask.astype(np.float64)
            color_peak = np.maximum(color_peak, mask.astype(np.float64))
            frames += 1
        if frames == 0:
            return None
        dens /= float(frames)
        presence /= float(frames)

        # 无实际内容的位置不计入文字簇（避免噪声）。
        # 用"峰值文字簇"而非均值做主信号：均值会被恒定水印/角标拉高（几乎每帧都在），
        # 而对话字幕是间歇的；峰值能捕捉到字幕真实出现时的密度。
        combo = cluster_peak.copy()
        combo[dens < 0.5] = 0.0
        k = np.ones(7, dtype=np.float64) / 7.0
        smooth = np.convolve(combo, k, mode="same")
        peak = float(smooth.max())
        if peak < 1.0:
            return None

        # 按文字簇强度找候选横带
        thr = peak * 0.12
        ys = np.where(smooth > thr)[0]
        if ys.size == 0:
            return None
        bands = []
        s = int(ys[0]); p = int(ys[0])
        for y in ys[1:]:
            if int(y) - p > 5:
                bands.append((s, p)); s = int(y)
            p = int(y)
        bands.append((s, p))

        # 打分：文字簇峰值 × 高度紧凑度 × 间歇性（出现频率） × 位置偏下优先
        candidates = []
        for y0, y1 in bands:
            h = y1 - y0 + 1
            val = float(smooth[y0:y1 + 1].max())
            compact = 1.0 if 15 <= h <= 130 else (0.4 if h < 15 else 0.15)
            # 恒定性硬过滤：字幕的本质是间歇性出现；presence 接近 1 的横带几乎
            # 肯定是固定元素（水印/角标/版权声明/标题），直接排除，避免 delogo
            # 打在"每帧都在"的固定小字上而漏掉真正间歇出现的台词字幕。
            band_pr = float(presence[y0:y1 + 1].mean())
            # 注意：不能用 presence 排除"恒定横带"——持续显示的字幕（如全程歌词/
            # 旁白字幕）presence≈1.0，按恒定性过滤会误杀真字幕。字幕与版权字/水印的
            # 区分交给"顶部/底部边缘排除 + 偏下 boost + 间歇性加分"共同完成：
            #   - 最顶部 5%：标题/角标等固定元素，排除
            #   - 最底部 5%：版权声明/水印等固定小字，排除
            if y1 < height * 0.05:
                continue
            if y0 > height * 0.95:
                continue
            # 出现频率越接近理想值（约 0.6，间歇性对话字幕）越加分，越接近 0（无内容）
            # 或 1（恒定水印/角标）越减分，从而把"对话字幕"从"固定水印"中区分出来。
            # 对"接近恒定（pr 很高）"做**二次方重罚**：恒定水印几乎每帧在场，其 pr≈1，
            # 若用线性惩罚不足以抵消其更高的文字簇强度，会导致区域被误选到水印上。
            pr = band_pr
            err = pr - SUBTITLE_MASK_PRESENCE_IDEAL
            # pr 越接近 1（恒定水印）惩罚越剧烈，越接近理想值（间歇字幕）越加分。
            if pr >= 0.85:
                dynamism = SUBTITLE_MASK_PRESENCE_MIN * 0.5   # 几乎恒定的水印：强烈减分
            elif pr <= 0.15:
                dynamism = SUBTITLE_MASK_PRESENCE_MIN * 0.5   # 几乎不出现：无意义
            else:
                dynamism = SUBTITLE_MASK_PRESENCE_MAX - \
                    err * err * SUBTITLE_MASK_PRESENCE_SLOPE * 3.0
            dynamism = max(SUBTITLE_MASK_PRESENCE_MIN * 0.5,
                           min(SUBTITLE_MASK_PRESENCE_MAX, dynamism))
            score = val * compact * dynamism
            if y0 > height * 0.3:
                score *= 1.3
            candidates.append((score, val, y0, y1, h, pr, dynamism))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        best_score = candidates[0][0]
        best_val = candidates[0][1]
        # 保留所有"文字簇强度达到最强带一定比例"的横带（按强度降序），覆盖
        # "旁白 + 对话 + 更高处副字幕"等多个纵向位置的字幕带，避免只打最强一条
        # 而漏掉其余位置的字幕。
        # 用 val（文字簇强度）而非 score（含出现频率加权）作阈值：低频但确实存在的
        # 副字幕带（如只在视频后半段出现的高位对话字幕）score 会因"出现频率低"被
        # 重罚而偏低，直接用 score 阈值会漏掉它。上方画面场景噪声由引擎侧的
        # "下半区 sanity 过滤"剔除，这里只按文字簇强度保底，兼顾不漏打与不过度误检。
        # 单个字幕带高度上限：超过该值视为"对话字幕在不同时间纵向浮动/多条字幕带
        # 被 cluster_peak 跨帧取最大而压成宽带"，按 smooth 剖面峰值拆分为多个紧凑
        # 子带，避免打码区域盖住半屏（用户反馈的核心问题）。
        # 主字幕带参考中心：在偏下(y0>0.3H)且出现频率达一定水平(ppr>=0.3)的候选里，
        # 选 presence 最接近理想值(0.6, 间歇对话字幕)的横带中心。用途：仅当存在明确
        # 的间歇性主字幕带时，才把"更靠下且全程恒定的固定文字/水印字条"从字幕候选中
        # 剔除——既避免它被当成字幕打码(盖住固定文字)，也避免 ASR 字幕对齐到最底部
        # 固定文字位置(用户反馈)。全程字幕(pr≈1 但与主字幕带位置一致)不会因此被排除。
        main_cy = None
        best_pr_err = 1e9
        main_y0 = None
        for (_sc, _vv, _yy0, _yy1, _hh, _ppr, _dyn) in candidates:
            if _yy0 > height * 0.3 and _ppr >= 0.3:
                _err = abs(_ppr - SUBTITLE_MASK_PRESENCE_IDEAL)
                # 平局(出现频率相同)时选更靠上的候选为主字幕带：真字幕通常比
                # 固定文字/水印更靠上，避免 main_cy 误选到更靠下的固定文字带。
                if _err < best_pr_err or (_err == best_pr_err and (_yy0 < main_y0 if main_y0 is not None else True)):
                    best_pr_err = _err
                    main_cy = (_yy0 + _yy1) / 2.0
                    main_y0 = _yy0
        max_band_h = max(18, int(height * 0.09))
        regions = []
        seen_bands = []
        for score, val, y0, y1, h, pr, dynamism in candidates:
            # 用 continue 而非 break：候选已按 score 降序，但这里按 val（文字簇强度）
            # 筛选副字幕带；若用 break，会在第一个"score 高但 val 低"的噪声带处提前
            # 退出，漏掉后面 val 更高但 score 低的副字幕带。
            if val < best_val * SUBTITLE_MASK_MULTI_RELATIVE:
                continue
            # 恒定且明显低于主字幕带的固定文字/水印字条：非间歇真字幕，剔除候选
            # （不打码、不参与 ASR 对齐；若真有全程底部字幕则与 main_cy 位置一致不命中）。
            # 阈值取 0.75：真实间歇对话字幕 pr≈0.6 远在其下不会被误杀，而全程恒定的
            # 固定文字/水印(pr≈0.8~1.0)会被排除；阈值不能太高(如 0.85)，否则合成/实测
            # 中偏低出现的恒定带(pr≈0.8)会漏过、仍被打码并拖累 ASR 对齐基准。
            if main_cy is not None and pr >= 0.75:
                cy = (y0 + y1) / 2.0
                if cy > main_cy + max(40, int(height * 0.08)):
                    continue
            # 过高横带：先按文字簇峰值剖面拆分出多个紧凑子带（贴合每处字幕位置），
            # 每个子带再独立计算横向范围与余量，区域总面积大幅下降且不漏字幕。
            if h > max_band_h:
                sub_bands = _split_tall_band(y0, y1, smooth, height, max_band_h)
            else:
                sub_bands = [(y0, y1)]
            # 子带级恒定排除：当"字幕 + 固定文字"被 cluster_peak 跨帧取最大压成同一条
            # 高候选带、_split_tall_band 才拆成多个子带时，上面的候选级排除够不着。
            # 这里对拆出的子带再过滤——恒定(pr 显著更高)且明显低于最上方子带的，判为
            # 固定文字/水印剔除（不打码、不参与 ASR 对齐）。真实间歇字幕与其浮动产生的
            # 子带 pr 相近(相差 <0.1)，不会被误杀；单子带(常规字幕)不触发本过滤。
            if len(sub_bands) > 1:
                _sb = [((s0 + s1) / 2.0, float(presence[s0:s1 + 1].mean()))
                       for (s0, s1) in sub_bands]
                _ref_cy = min(c for c, p in _sb)
                _ref_pr = min(p for c, p in _sb)
                sub_bands = [
                    (s0, s1) for (s0, s1) in sub_bands
                    if not (float(presence[s0:s1 + 1].mean()) >= 0.75
                            and float(presence[s0:s1 + 1].mean()) > _ref_pr + 0.1
                            and ((s0 + s1) / 2.0) > _ref_cy + max(40, int(height * 0.08)))
                ]
            for (sy0, sy1) in sub_bands:
                sh = sy1 - sy0 + 1
                # 与已选区域纵向重叠的横带合并（同一字幕带可能被切成多段）
                overlap = False
                for (ry0, ry1) in seen_bands:
                    if sy0 <= ry1 and ry0 <= sy1:
                        overlap = True
                        break
                if overlap:
                    continue

                # 上下扩展余量（向下略多，覆盖描边/换行/下延），确保 delogo 完整补平。
                # 子带已紧贴字幕文字，余量仅需覆盖描边/换行，不宜过大，否则区域被
                # 撑高 1.7~2.2 倍（"打码区域太大、盖住半屏"的根因之一），故收窄到 ~30%。
                up = min(36, max(10, int(sh * 0.25)))
                down = min(42, max(14, int(sh * 0.3)))
                ey0 = max(0, sy0 - up)
                ey1 = min(height - 1, sy1 + down)

                # 横向范围
                col = color_peak[ey0:ey1 + 1, :].sum(axis=0)
                col_peak = float(col.max())
                if col_peak <= 1:
                    rx0, rw = 0, width
                else:
                    cols = np.where(col > col_peak * 0.1)[0]
                    if cols.size == 0:
                        rx0, rw = 0, width
                    else:
                        cx0 = max(0, int(cols.min()) - 10)
                        cx1 = min(width - 1, int(cols.max()) + 10)
                        rx0, rw = cx0, (cx1 - cx0)
                regions.append((rx0, ey0, rw, (ey1 - ey0)))
                seen_bands.append((sy0, sy1))
        if not regions:
            return None
        return regions
    finally:
        if cap is not None:
            cap.release()


# 帧级（精细化）检测参数：判断"字幕/水印是否实际出现在区域内"的阈值与采样密度。
# 相比固定区域全程打码，开启 temporal 后只在内容出现的时段打码，画面其余时间零改动。
# 处理速度会变慢（需按时间采样判断内容在场与否），但更精细、画面更干净。
# 判断"在场"改用以字幕专属的"金色/黄色 + 白色/浅色"文字像素密度为信号（与区域/空间
# 检测一致），而非 Canny 边缘密度——因为复杂/繁忙画面在字幕横带内常年有高密度边缘，
# 用边缘会把"无字幕时段"也误判为在场，导致精细化失效（整段都被打码）。
# 字幕文字像素占区域比例超过该绝对下限视为"在场"（避免全黑/全白噪声帧）。
SUBTITLE_MASK_TEMPORAL_COLOR_RATIO = 0.003
# 捕获短句字幕的"噪声地板 → 峰值"相对下限（0~1，越小越能捕获低密度短句）。
SUBTITLE_MASK_TEMPORAL_LOW_FRAC = 0.25
# 阈值不低于噪声地板的该倍数，避免把背景噪声帧误判为在场。
SUBTITLE_MASK_TEMPORAL_NOISE_MULT = 2.0
# 帧级检测采样步长（秒）。越小定位越准，但越慢。
SUBTITLE_MASK_TEMPORAL_STEP = 0.5
# 相邻"在场"采样点合并成时间窗口的最小间距（秒）：小于该间距的相邻窗口合并。
SUBTITLE_MASK_TEMPORAL_MERGE_GAP = 0.6
# 打码窗口前后各扩展的余量（秒），避免字幕开头/结尾裁切不干净。
SUBTITLE_MASK_TEMPORAL_PAD = 0.25


def _low_percentile(values: list[float], p: float) -> float:
    """返回有序列表的低分位（如 25%）作为"背景噪声地板"的稳健估计。

    用线性插值在相邻元素间取分位；空列表返回 0。
    """
    if not values:
        return 0.0
    srt = sorted(values)
    n = len(srt)
    pos = p * (n - 1)
    lo = int(pos)
    hi = min(n - 1, lo + 1)
    frac = pos - lo
    return srt[lo] + (srt[hi] - srt[lo]) * frac


def _bimodal_threshold(values: list[float]) -> float:
    """Otsu 式双峰阈值：把密度值分成"背景"与"字幕"两簇，返回使簇内方差最小的分割点。

    若所有值几乎相等（单峰/无分割），回退到峰值的一小比例。
    """
    if not values:
        return 0.0
    lo, hi = min(values), max(values)
    if hi - lo < 1e-6:
        return hi
    # 归一化到 [0,1] 并分桶统计直方图
    nbins = min(256, max(16, len(values)))
    hist = [0] * nbins
    for v in values:
        idx = int((v - lo) / (hi - lo) * (nbins - 1) + 0.5)
        idx = max(0, min(nbins - 1, idx))
        hist[idx] += 1
    total = float(sum(hist))
    if total <= 0:
        return lo + (hi - lo) * 0.5
    # 前缀和/加权和
    sum_all = sum(v * hist[i] for i, v in enumerate((lo + (hi - lo) * i / (nbins - 1) for i in range(nbins))))
    w_b = 0.0
    s_b = 0.0
    best_var = -1.0
    best_t = lo
    for i in range(nbins):
        w_b += hist[i]
        if w_b <= 0:
            continue
        w_f = total - w_b
        if w_f <= 0:
            continue
        v = lo + (hi - lo) * i / (nbins - 1)
        s_b += v * hist[i]
        m_b = s_b / w_b
        m_f = (sum_all - s_b) / w_f
        var = w_b * w_f * (m_b - m_f) * (m_b - m_f)
        if var > best_var:
            best_var = var
            best_t = v
    return best_t


def detect_watermark_region(video: str, max_frames: int = 12) -> Optional[list[tuple[int, int, int, int]]]:
    """用 OpenCV 从源视频采样帧自动检测恒定水印/角标区域（支持多个：顶部+底部）。

    与 detect_subtitle_region 相反：字幕是间歇出现的（presence 接近 0.6），
    而水印/角标几乎每帧都在（presence 接近 1.0）。这里以"出现频率"为主信号，
    越接近恒定（pr→1）越加分，间歇出现的对话字幕会被排除。

    片源常在**顶部和底部各有一个固定水印**，因此这里返回**所有**通过恒定阈值的
    横带区域（按强度降序），而不是只挑最强一条——否则会漏掉另一个位置的水印。

    返回多个区域 [(x, y, w, h), ...]；检测失败或 OpenCV 不可用时返回 None（由
    调用方回退到固定比例区域：默认底部水印带）。
    """
    width, height = ffprobe_size(video)
    if width <= 0 or height <= 0:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    dur = ffprobe_duration(video)
    if not dur or dur <= 0:
        return None
    n = min(max_frames, max(6, int(dur)))
    times = [dur * (i + 0.5) / n for i in range(n)]

    cap = None
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        dens = np.zeros(height, dtype=np.float64)
        presence = np.zeros(height, dtype=np.float64)
        color_acc = np.zeros((height, width), dtype=np.float64)
        frames = 0
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            b = frame[:, :, 0].astype(np.int16)
            g = frame[:, :, 1].astype(np.int16)
            r = frame[:, :, 2].astype(np.int16)
            # 金色/黄色 + 白色/浅色（水印/角标最常见配色，与字幕检测一致）
            gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & (g - b > 40) & (abs(r - g) < 110)
            white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & (abs(g - b) < 45) & (abs(r - b) < 45)
            mask = gold | white
            dens += mask.sum(axis=1)
            cl = _mask_text_clusters(mask)
            presence += (cl > 3).astype(np.float64)
            color_acc += mask.astype(np.float64)
            frames += 1
        if frames == 0:
            return None
        dens /= float(frames)
        presence /= float(frames)

        # 主信号 = 出现频率（恒定水印 pr→1 加分；间歇字幕 pr≈0.6 减分）
        # 同时要求有实际内容（dens 均值 > 0）
        combo = presence.copy()
        combo[dens < 0.5] = 0.0
        k = np.ones(7, dtype=np.float64) / 7.0
        smooth = np.convolve(combo, k, mode="same")
        peak = float(smooth.max())
        if peak < 0.5:
            return None

        thr = peak * 0.7
        ys = np.where(smooth > thr)[0]
        if ys.size == 0:
            return None
        bands = []
        s = int(ys[0]); p = int(ys[0])
        for y in ys[1:]:
            if int(y) - p > 5:
                bands.append((s, p)); s = int(y)
            p = int(y)
        bands.append((s, p))

        # 打分：出现频率（恒定优先） × 文字簇密度 × 高度紧凑度
        candidates = []
        for y0, y1 in bands:
            h = y1 - y0 + 1
            val = float(dens[y0:y1 + 1].max())
            pr = float(presence[y0:y1 + 1].mean())
            # 恒定出现（pr 高）加分；间歇出现（pr 低）减分
            constancy = min(1.0, max(0.0, (pr - 0.4) / 0.6))
            compact = 1.0 if 15 <= h <= 120 else (0.4 if h < 15 else 0.2)
            score = val * constancy * compact
            candidates.append((score, val, y0, y1, h, pr))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        best_score = candidates[0][0]
        # 收集所有通过恒定阈值的横带（顶部水印 + 底部水印等多个固定元素），
        # 避免只打最强一条而漏掉另一个位置的水印/角标。
        regions = []
        seen_bands = []
        for score, val, y0, y1, h, pr in candidates:
            if score < best_score * SUBTITLE_MASK_MULTI_RELATIVE:
                break
            overlap = False
            for (ry0, ry1) in seen_bands:
                if y0 <= ry1 and ry0 <= y1:
                    overlap = True
                    break
            if overlap:
                continue
            # 上下扩展余量
            up = max(8, int(h * 0.25))
            down = max(12, int(h * 0.4))
            ey0 = max(0, y0 - up)
            ey1 = min(height - 1, y1 + down)
            # 横向范围
            col = color_acc[ey0:ey1 + 1, :].sum(axis=0)
            col_peak = float(col.max())
            if col_peak <= 1:
                rx0, rw = 0, width
            else:
                cols = np.where(col > col_peak * 0.1)[0]
                if cols.size == 0:
                    rx0, rw = 0, width
                else:
                    cx0 = max(0, int(cols.min()) - 10)
                    cx1 = min(width - 1, int(cols.max()) + 10)
                    rx0, rw = cx0, (cx1 - cx0)
            regions.append((rx0, ey0, rw, (ey1 - ey0)))
            seen_bands.append((y0, y1))
        if not regions:
            return None
        return regions
    finally:
        if cap is not None:
            cap.release()


def detect_subtitle_temporal_windows(video: str, region: tuple[int, int, int, int],
                                     max_frames: int = 600) -> Optional[list[tuple]]:
    """帧级检测：判断字幕/水印在区域内实际出现的时间窗口列表。

    在指定 region (x, y, w, h) 内，按 SUBTITLE_MASK_TEMPORAL_STEP 步长扫描整段视频，
    对每个采样点判断区域内是否有文字/水印内容（区域内"金色/黄色 + 白色/浅色"字幕文字
    像素密度超过阈值即视为在场）。将连续的"在场"点合并为时间窗口，并前后各扩一点余量后返回。

    返回 [(start, end), ...] 秒级时间窗口（局部时间轴，从 0 开始）；
    检测失败或无字幕/水印时返回 None（由调用方回退为全程打码）。
    该方式不依赖 SRT，适用于任何片源字幕/水印的精细化打码。
    """
    x, y, w, h = region
    if w <= 0 or h <= 0:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    duration = ffprobe_duration(video)
    if not duration or duration <= 0:
        return None
    vw, vh = ffprobe_size(video)
    if vw <= 0 or vh <= 0:
        return None
    # 采样点数量封顶，防止超长视频采样过密导致过慢。
    step = SUBTITLE_MASK_TEMPORAL_STEP
    n = int(duration / step) + 1
    if n > max_frames:
        # 保持封顶采样数，等比例加大步长。
        step = duration / max_frames
        n = max_frames
    x0, x1 = max(0, x), min(x + w - 1, vw - 1)
    y0, y1 = max(0, y), min(y + h - 1, vh - 1)
    box_w = max(1, x1 - x0 + 1)
    box_h = max(1, y1 - y0 + 1)

    cap = None
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        # 逐点采集：记录每个采样点区域内"金色/黄色 + 白色/浅色"字幕文字像素占比。
        # 字幕文字多为金色/黄色/白字，而画面背景/人物即便很杂也很少大片纯金/纯白像素，
        # 用该信号判断字幕是否在场远比 Canny 边缘可靠（边缘会被繁忙背景常年拉高）。
        present = []  # (t, score)
        for i in range(n):
            t = min(duration - 0.01, i * step)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            b = frame[y0:y1 + 1, x0:x1 + 1, 0].astype(np.int16)
            g = frame[y0:y1 + 1, x0:x1 + 1, 1].astype(np.int16)
            r = frame[y0:y1 + 1, x0:x1 + 1, 2].astype(np.int16)
            # 金色/黄色字幕（R 高、G 高、B 低，R/G 接近）
            gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & \
                   (g - b > 40) & (abs(r - g) < 110)
            # 白色/浅色字幕
            white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & \
                    (abs(g - b) < 45) & (abs(r - b) < 45)
            mask = gold | white
            density = float(mask.sum()) / float(box_w * box_h)
            present.append((t, density))
        if not present:
            return None
        scores = [s for _, s in present]
        peak = max(scores)
        if peak <= 1e-6:
            return None
        # 在场阈值：用"双峰(背景/字幕)分割"自适应确定，鲁棒地应对不同画面。
        # 密度值大致形成两个簇：背景帧(密度≈噪声地板，较低) 与 字幕帧(密度较高)。
        # 用 Otsu 式穷举找到使两类簇内方差最小的分割点，比固定倍率更稳：
        #   - 背景很杂时（噪声地板高），阈值自动抬高，避免把整段误判为在场；
        #   - 字幕较长/密度较高时，阈值自动落到字幕/背景的分界。
        thr = _bimodal_threshold(scores)
        # Otsu 只看两簇，当画面同时存在"长句字幕(高密度)"与"短句字幕(较低密度)"时，
        # 阈值会被高密度簇拉高，导致短句被漏检。额外用"背景噪声地板 + 峰值小比例"给出
        # 一个更低的下限，取两者较小值，从而也能捕获短句字幕；再保证不低于噪声地板
        # 的固定倍数，避免把背景噪声帧误判为在场。
        # 噪声地板用低分位（10%分位）估计，避免被"字幕在场帧"和"短句字幕"污染。
        noise_floor = _low_percentile(scores, 0.10)
        low_thr = noise_floor + (peak - noise_floor) * SUBTITLE_MASK_TEMPORAL_LOW_FRAC
        thr = min(thr, low_thr)
        thr = max(thr, noise_floor * SUBTITLE_MASK_TEMPORAL_NOISE_MULT)
        # 双峰分割可能偏低，额外保证不低于绝对下限（避免纯噪声帧被误判）。
        thr = max(thr, SUBTITLE_MASK_TEMPORAL_COLOR_RATIO)
        # 连续在场点 → 时间窗口（窗口内若个别点低于阈值但间距小，予以补齐）。
        in_on = False
        cur_start = 0.0
        last_on_t = -1e9
        windows = []
        for t, s in present:
            on = s >= thr
            if on:
                if not in_on:
                    cur_start = t
                    in_on = True
                last_on_t = t
            else:
                # 短暂掉线（间距小于 merge_gap）视为仍在场，保持窗口。
                if in_on and (t - last_on_t) <= SUBTITLE_MASK_TEMPORAL_MERGE_GAP:
                    continue
                if in_on:
                    windows.append((cur_start, last_on_t))
                    in_on = False
        if in_on:
            windows.append((cur_start, last_on_t))
        if not windows:
            return None
        # 合并间距过小的相邻窗口，并扩展余量、裁剪到时长内。
        merged = []
        for s, e in windows:
            if merged and s - merged[-1][1] <= SUBTITLE_MASK_TEMPORAL_MERGE_GAP:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append([s, e])
        result = []
        for s, e in merged:
            result.append((max(0.0, s - SUBTITLE_MASK_TEMPORAL_PAD),
                           min(duration, e + SUBTITLE_MASK_TEMPORAL_PAD)))
        return result
    finally:
        if cap is not None:
            cap.release()


# 空间精细化（仅字幕显示区域）检测参数：
# 在 temporal 已定位的每个时间窗口内，进一步找出该窗口字幕文字实际占用的
# 横向范围，只对这些小块区域打码，而不把整条横带都盖住。
# 单窗口内采样帧数上限（越多越稳，但越慢）。
SUBTITLE_MASK_SPATIAL_MAX_FRAMES = 5
# 子区域横向检测阈值（相对该窗口最大列内容得分的比例）。
SUBTITLE_MASK_SPATIAL_CONTRAST_RATIO = 0.12


def detect_subtitle_spatial_regions(video: str, region: tuple[int, int, int, int],
                                    temporal_windows: list[tuple]) -> Optional[list[tuple]]:
    """对每个时间窗口，在横带区域内进一步检测字幕文字实际占用的横向范围。

    region: 整体横带区域 (x, y, w, h)（源分辨率，temporal 检测所用同一区域）。
    temporal_windows: [(start, end), ...] 源时间窗口（秒）。

    返回 [(start, end, x, w), ...]：每个窗口对应的文字子区域 (x, w) 为该窗口
    字幕文字实际占用的横向范围（x 为绝对列坐标，w 为宽度，均源分辨率）。
    检测失败或无内容返回 None（由调用方回退为整条横带打码）。
    """
    x, y, w, h = region
    if w <= 0 or h <= 0 or not temporal_windows:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    vw, vh = ffprobe_size(video)
    if vw <= 0 or vh <= 0:
        return None
    x0, x1 = max(0, x), min(x + w - 1, vw - 1)
    y0, y1 = max(0, y), min(y + h - 1, vh - 1)
    band_w = max(1, x1 - x0 + 1)
    cap = None
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        result = []
        for (s, e) in temporal_windows:
            # 时间窗口本身已含前后 PAD 余量（余量处可能无字幕），空间检测需在窗口
            # **内部**采样，避免采到无字幕的余量端点。收敛到窗口中心的核心区间。
            inner_s = s + SUBTITLE_MASK_TEMPORAL_PAD
            inner_e = e - SUBTITLE_MASK_TEMPORAL_PAD
            if inner_e <= inner_s:
                inner_s, inner_e = s, e
            mid = (inner_s + inner_e) / 2.0
            dur = max(0.05, inner_e - inner_s)
            # 采样帧数取上限（不因 dur 取整而缩水），保证能覆盖文字横向全貌。
            n = min(SUBTITLE_MASK_SPATIAL_MAX_FRAMES,
                    max(2, int(round(dur / 0.5)) + 1))
            times = [max(0.0, mid + (i - (n - 1) / 2.0) * (dur / max(1, n - 1)))
                     for i in range(n)]
            col_acc = np.zeros(band_w, dtype=np.float64)
            any_color = False
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                b = frame[y0:y1 + 1, x0:x1 + 1, 0].astype(np.int16)
                g = frame[y0:y1 + 1, x0:x1 + 1, 1].astype(np.int16)
                r = frame[y0:y1 + 1, x0:x1 + 1, 2].astype(np.int16)
                gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & \
                       (g - b > 40) & (abs(r - g) < 110)
                white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & \
                        (abs(g - b) < 45) & (abs(r - b) < 45)
                mask = gold | white
                if bool(mask.any()):
                    any_color = True
                col_acc += mask.sum(axis=0)
            if not any_color:
                # 该窗口未检出彩色字幕，用灰度边缘兜底定位文字横向范围。
                for t in times:
                    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        continue
                    gray = cv2.cvtColor(frame[y0:y1 + 1, x0:x1 + 1],
                                        cv2.COLOR_BGR2GRAY)
                    edges = cv2.Canny(gray, 60, 160)
                    col_acc += edges.sum(axis=0)
            peak = float(col_acc.max())
            if peak <= 1e-6:
                continue
            cols = np.where(col_acc > peak * SUBTITLE_MASK_SPATIAL_CONTRAST_RATIO)[0]
            if cols.size == 0:
                continue
            pad = max(8, int(w * 0.02))
            sx = max(0, x0 + int(cols.min()) - pad)
            ex = min(vw - 1, x0 + int(cols.max()) + pad)
            result.append((s, e, sx, ex - sx + 1))
        return result if result else None
    finally:
        if cap is not None:
            cap.release()


# SRT 时间轴驱动的动态字幕区域检测参数：
# 每个 SRT 字幕窗口内抽帧数（越多越稳，但越慢）。SRT 时间点已经标注了
# "字幕/对话/旁白"出现的时刻，只需在这些时刻抽帧定位字幕文字的实际紧凑位置，
# 无需对整段视频逐帧扫描，检测成本远低于 temporal 的全程采样。
SUBTITLE_MASK_DYNAMIC_FRAMES = 3
# 动态抽帧时在窗口内取样的相对位置（避开首尾过渡帧）。
SUBTITLE_MASK_DYNAMIC_FRAC = (0.35, 0.5, 0.65)
# 动态检测的纵向搜索带：字幕/对话/旁白几乎都在画面下半区，这里限定在下半区
# 内搜索，避免把顶部标题/角标误检为字幕，也减少无关区域的处理量。
SUBTITLE_MASK_DYNAMIC_SEARCH_BOTTOM_RATIO = 0.45


def detect_subtitle_dynamic_regions(video: str, srt: str) -> Optional[list[tuple]]:
    """SRT 时间轴驱动的动态字幕区域检测（每窗口紧凑区域）。

    相比"静态单区域 + 全程打码"与"全时间轴逐帧 temporal 检测"，本方案：
      - 只在 SRT 标注的字幕/对话/旁白出现的时刻抽帧定位，避免逐帧全视频扫描
        （高效，成本远低于 temporal 的 0.5s 步长全程采样）；
      - 每个字幕窗口用自己在该时刻检测到的紧凑文字外接框 (x, y, w, h)，字幕在
        不同时间位于不同纵向位置（旁白 vs 对话）时各自准确覆盖，不会把多个位置
        合并成一条宽大横带（解决"打码区域太大、盖住半屏"）；
      - 无字幕的时间（SRT 无记录）不打码，避免"没字幕也打码"；
      - 用字幕专属的"金色/黄色 + 白色/浅色"文字色做掩码，对金色/黄色短剧字幕可靠。

    srt: 源视频 SRT（ASR 选点阶段已产出，标注对话/旁白出现时刻）。
    返回 [(src_s, src_e, x, y, w, h), ...]：每个 SRT 窗口对应的紧凑字幕区域
    （源时间轴 + 源分辨率绝对坐标）；检测失败或无 SRT 返回 None。
    """
    records = read_srt(srt) if srt and os.path.isfile(srt) else []
    if not records:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    vw, vh = ffprobe_size(video)
    if vw <= 0 or vh <= 0:
        return None
    # 纵向搜索带：画面下半区（字幕常驻区），并适当向上留余量。
    y_top = int(vh * (1.0 - SUBTITLE_MASK_DYNAMIC_SEARCH_BOTTOM_RATIO)) - 20
    y_top = max(0, y_top)

    cap = None
    result = []
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        for rec in records:
            s = float(rec["start"])
            e = float(rec["end"])
            if e <= s:
                continue
            # 窗口内抽样时刻（相对位置，避开首尾过渡帧）。
            times = [s + (e - s) * f for f in SUBTITLE_MASK_DYNAMIC_FRAC]
            times = times[:SUBTITLE_MASK_DYNAMIC_FRAMES]
            mask_acc = None
            any_text = False
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                sub = frame[y_top:vh, :, :]
                b = sub[:, :, 0].astype(np.int16)
                g = sub[:, :, 1].astype(np.int16)
                r = sub[:, :, 2].astype(np.int16)
                # 金色/黄色字幕（R 高、G 高、B 低，R/G 接近）
                gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & \
                       (g - b > 40) & (abs(r - g) < 110)
                # 白色/浅色字幕
                white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & \
                        (abs(g - b) < 45) & (abs(r - b) < 45)
                m = gold | white
                if not bool(m.any()):
                    continue
                any_text = True
                if mask_acc is None:
                    mask_acc = m.astype(np.float64)
                else:
                    mask_acc += m.astype(np.float64)
            if not any_text or mask_acc is None:
                continue
            # 纵向：用「文字簇强度」而非原始像素投影作主信号。字幕文字带每一行总有
            # 多个横向分离的文字笔画簇（每个字一个簇），而画面中大块浅色/暖色背景
            # （人物、家具、灯光）虽能命中颜色掩码，但一行内文字簇数量很少。若用
            # 像素投影，整段被误判为文字的背景行都会被圈进来，导致区域高度膨胀到
            # 占屏高 40%~55%（“打码区域太大、盖住半屏”的根因）。
            mask_bool = (mask_acc > 0).astype(bool)
            cl_rows = _mask_text_clusters(mask_bool).astype(np.float64)
            rpeak = float(cl_rows.max())
            if rpeak <= 0:
                continue
            # 聚类阈值用文字簇相对峰值（30%），聚焦文字主带，排除只命中一两个簇的
            # 稀疏误判行（背景/装饰）。同时按 6px 间隙把离散簇行聚成子带，避免跨帧
            # 取 min/max 把字幕在不同帧的纵向浮动范围整体压成一条宽带。
            thr = rpeak * 0.30
            ys = np.where(cl_rows >= thr)[0]
            if ys.size == 0:
                continue
            bands = []
            bs = int(ys[0]); bp = int(ys[0])
            for y in ys[1:]:
                if int(y) - bp > 6:
                    bands.append((bs, bp)); bs = int(y)
                bp = int(y)
            bands.append((bs, bp))
            # 单条子带高度上限约屏高 9%，超出按文字簇剖面峰值拆分，避免半屏宽带。
            max_band_h = max(18, int(vh * 0.09))
            sub_regions = []
            for (sy0, sy1) in bands:
                sy0 = int(sy0); sy1 = int(sy1)
                bh = sy1 - sy0 + 1
                if bh > max_band_h:
                    sub = _split_tall_band(sy0, sy1, cl_rows, cl_rows.shape[0], max_band_h)
                else:
                    sub = [(sy0, sy1)]
                for (b0, b1) in sub:
                    b0 = int(b0); b1 = int(b1)
                    yy0 = y_top + b0
                    yy1 = y_top + b1
                    # 横向：按行投影取文字列范围。
                    cols = mask_acc[b0:b1 + 1, :].sum(axis=0)
                    cpeak = float(cols.max())
                    if cpeak <= 0:
                        continue
                    cs = np.where(cols > cpeak * 0.12)[0]
                    if cs.size == 0:
                        continue
                    # 文字外接框加小余量（覆盖描边/换行），并裁剪到画面内。
                    pad = max(6, int((yy1 - yy0) * 0.15))
                    y0 = max(0, yy0 - pad)
                    y1 = min(vh - 1, yy1 + pad)
                    x0 = max(0, int(cs.min()) - pad)
                    x1 = min(vw - 1, int(cs.max()) + pad)
                    hh = y1 - y0 + 1
                    ww = x1 - x0 + 1
                    if hh <= 0 or ww <= 0:
                        continue
                    sub_regions.append((s, e, x0, y0, ww, hh))
            if not sub_regions:
                continue
            # 同一窗口内若出现多个子带（旁白/对话分处不同高度），取文字区域最大的
            # 主字幕带作为该窗口的紧凑区域，避免一个窗口塞入多个重叠大框。
            best = max(sub_regions, key=lambda it: it[4] * it[5])
            x0, y0, ww, hh = best[2], best[3], best[4], best[5]
            # 去重相邻窗口的同一位置区域（纵向重叠则合并时间窗，避免重复打码）。
            if result and result[-1][2] == x0 and result[-1][3] == y0 \
                    and result[-1][4] == ww and result[-1][5] == hh \
                    and s <= result[-1][1] + 0.5:
                result[-1] = (result[-1][0], max(result[-1][1], e), x0, y0, ww, hh)
            else:
                result.append((s, e, x0, y0, ww, hh))
        return result if result else None
    finally:
        if cap is not None:
            cap.release()


def _parse_subtitle_mask_config(raw: str | None) -> dict | None:
    """解析 --subtitle-mask 参数（JSON），未启用返回 None。"""
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    return cfg


def _source_intervals_to_local_intervals(src_intervals: list[tuple], seg_times: list[tuple],
                                         scale: float = 1.0) -> list[tuple]:
    """把源时间轴区间列表转换为切片局部时间轴（从 0 开始）的区间列表。

    与 _source_intervals_to_local_enable 逻辑一致，但返回 [(start, end), ...] 列表
    而非 enable 表达式，便于逐区域构建各自的时间窗口。
    """
    if not src_intervals:
        return []
    intervals = []
    offset = 0.0
    for start, end in seg_times:
        for s0, e0 in src_intervals:
            s = max(s0, start)
            e = min(e0, end)
            if e > s:
                intervals.append(((s - start) / scale + offset, (e - start) / scale + offset))
        offset += max(0.0, (end - start) / scale)
    if not intervals:
        return []
    intervals.sort()
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1] + 0.4:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append([s, e])
    return [(s, e) for (s, e) in merged]


def _scale_region(region: tuple, cfg: dict, width: int, height: int) -> tuple:
    """把单个检测分辨率下的区域等比缩放到当前切片分辨率。

    region: (x, y, w, h) 基于 __detect_w/__detect_h 检测分辨率。
    cfg: 含 __detect_w/__detect_h；若未记录或与当前分辨率一致，直接返回原坐标。
    """
    x, y, w, h = region
    dw = int(cfg.get("__detect_w") or 0)
    dh = int(cfg.get("__detect_h") or 0)
    if dw > 0 and dh > 0 and (dw != width or dh != height):
        nx = int(round(x * width / dw))
        ny = int(round(y * height / dh))
        nw = int(round(w * width / dw))
        nh = int(round(h * height / dh))
        return (nx, ny, nw, nh)
    return (x, y, w, h)


def _mask_enable_expr(intervals: list[tuple]) -> str:
    """把区间列表合并为 enable 表达式。"""
    terms = [f"between(t,{s:.3f},{e:.3f})" for s, e in intervals]
    return "+".join(terms)


def _source_intervals_to_local_enable(src_intervals: list[tuple], seg_times: list[tuple],
                                      scale: float = 1.0) -> str:
    """把源时间轴上的区间列表转换为切片局部时间轴（从 0 开始）的 enable 表达式。

    src_intervals: 源时间轴上的 [(start, end), ...]，如 SRT 字幕时段或帧级检测到的
        字幕/水印在场时段。
    seg_times: 按拼接顺序排列的源时间段 [(start, end), ...]，与 build_clip_subtitle 一致。
    scale: 输出时间轴缩放因子（>1 表示切片时对视频做了变速压缩，如去重 mode 的
        setpts 变速；源时间 t 对应输出画面时间 t/scale）。默认 1 不缩放（普通/快速模式）。
    返回局部 enable 表达式；该切片内无内容则返回 ""。
    """
    if not src_intervals:
        return ""
    intervals = []
    offset = 0.0
    for start, end in seg_times:
        for s0, e0 in src_intervals:
            s = max(s0, start)
            e = min(e0, end)
            if e > s:
                intervals.append(((s - start) / scale + offset, (e - start) / scale + offset))
        offset += max(0.0, (end - start) / scale)
    if not intervals:
        return ""
    intervals.sort()
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1] + 0.4:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append([s, e])
    return _mask_enable_expr(merged)


def _spatial_windows_to_local(src_windows: list[tuple], seg_times: list[tuple],
                              cfg: dict, width: int, scale: float = 1.0) -> list[tuple]:
    """把空间精细化窗口（源时间轴 + 源分辨率子区域）转换为切片局部坐标。

    src_windows: [(源_start, 源_end, 源_x, 源_w), ...]，源_x 为绝对列坐标（源分辨率）。
    seg_times: 切片源时间段 [(start, end), ...]。
    cfg: 打码配置（含 __detect_w/__detect_h 用于把源分辨率子区域等比缩放到切片分辨率）。
    width: 切片分辨率宽度。

    返回 [(局部_start, 局部_end, 局部_x, 局部_w), ...]，供 build_subtitle_mask_filter_multi 使用。
    """
    dw = int(cfg.get("__detect_w", 0))
    # 去重 hflip 镜像：子区域 x 需按画面宽度镜像（与整条横带打码的镜像处理一致）。
    hflip = bool(cfg.get("__hflip"))
    out = []
    for (s0, e0, sx, sw) in src_windows:
        if dw > 0 and dw != width:
            ax = int(round(sx * width / dw))
            aw = max(1, int(round(sw * width / dw)))
        else:
            ax = sx
            aw = sw
        if hflip:
            ax = max(0, width - ax - aw)
        if ax >= width or ax + aw <= 0:
            continue
        offset = 0.0
        for start, end in seg_times:
            ls = max(s0, start)
            le = min(e0, end)
            if le > ls:
                out.append(((ls - start) / scale + offset, (le - start) / scale + offset, ax, aw))
            offset += max(0.0, (end - start) / scale)
    # 去重/合并相邻（同子区域）局部区间
    out.sort()
    result = []
    for s, e, x, w in out:
        if result and abs(result[-1][0] - s) < 0.01 and result[-1][2] == x and result[-1][3] == w:
            result[-1] = (result[-1][0], max(result[-1][1], e), x, w)
        else:
            result.append((s, e, x, w))
    return result


def _dynamic_windows_to_local(src_windows: list[tuple], seg_times: list[tuple],
                                   cfg: dict, width: int, height: int,
                                   scale: float = 1.0) -> list[tuple]:
    """把 SRT 驱动的动态字幕窗口（源时间轴 + 源分辨率紧凑区域）转换为切片局部坐标。

    src_windows: [(源_s, 源_e, 源_x, 源_y, 源_w, 源_h), ...]，每个窗口有自己的
        紧凑文字外接框（源分辨率绝对坐标）。
    seg_times: 切片源时间段 [(start, end), ...]。
    cfg: 打码配置（含 __detect_w/__detect_h 用于把源分辨率区域等比缩放到切片分辨率）。
    width/height: 切片分辨率尺寸。
    scale: 去重变速因子（>1 表示变速压缩）。

    返回 [(局部_s, 局部_e, 局部_x, 局部_y, 局部_w, 局部_h), ...]。
    """
    dw = int(cfg.get("__detect_w", 0))
    dh = int(cfg.get("__detect_h", 0))
    hflip = bool(cfg.get("__hflip"))
    out = []
    for (s0, e0, sx, sy, sw, sh) in src_windows:
        if dw > 0 and dh > 0 and (dw != width or dh != height):
            ax = int(round(sx * width / dw))
            ay = int(round(sy * height / dh))
            aw = max(1, int(round(sw * width / dw)))
            ah = max(1, int(round(sh * height / dh)))
        else:
            ax, ay, aw, ah = sx, sy, sw, sh
        if hflip:
            ax = max(0, width - ax - aw)
        if ax >= width or ax + aw <= 0 or ay >= height or ay + ah <= 0:
            continue
        offset = 0.0
        for start, end in seg_times:
            ls = max(s0, start)
            le = min(e0, end)
            if le > ls:
                out.append(((ls - start) / scale + offset, (le - start) / scale + offset,
                            ax, ay, aw, ah))
            offset += max(0.0, (end - start) / scale)
    # 去重/合并相邻（同区域）局部区间
    out.sort()
    result = []
    for s, e, x, y, w, h in out:
        if result and abs(result[-1][0] - s) < 0.01 and result[-1][2] == x \
                and result[-1][3] == y and result[-1][4] == w and result[-1][5] == h:
            result[-1] = (result[-1][0], max(result[-1][1], e), x, y, w, h)
        else:
            result.append((s, e, x, y, w, h))
    return result


def build_subtitle_mask_enable(src_srt: str, seg_times: list[tuple], offset: float = 0.0,
                               scale: float = 1.0) -> str:
    """根据切片源时间段，从源 SRT 生成打码区间（局部时间轴，从 0 开始）。

    seg_times: 按拼接顺序排列的源时间段 [(start, end), ...]，与 build_clip_subtitle 一致。
    生成的区间时间轴与切片成品一致（从 0 开始），可直接用于 overlay/crop 的 enable。
    返回 "" 表示该切片内无字幕（无需打码）。

    offset: 字幕时间轴整体偏移（秒）。用于校正 ASR 字幕时间与画面实际字幕的偏差：
      画面字幕比 SRT 晚出现（字幕滞后）时传正值延后打码；早出现时传负值提前打码。
      默认 0 不偏移。
    """
    records = read_srt(src_srt)
    if not records:
        return ""
    if offset:
        return _source_intervals_to_local_enable(
            [(float(r["start"]) + offset, float(r["end"]) + offset) for r in records], seg_times, scale)
    return _source_intervals_to_local_enable(
        [(float(r["start"]), float(r["end"])) for r in records], seg_times, scale)


def _subtitle_mask_area(cfg: dict, width: int, height: int) -> tuple[int, int, int, int]:
    """根据配置计算打码区域 (x, y, w, h)，均为整数像素。

    支持两种定位方式：
      - 默认比例定位：底部横带，width_ratio / height_ratio / bottom_ratio 相对视频宽高。
      - 绝对定位：显式提供 x / y / width / height 时直接使用（可覆盖任意位置）。
    返回的区域会被裁剪回视频边界内。
    """
    if width <= 0 or height <= 0:
        return 0, 0, 0, 0

    def _f(key, default):
        try:
            v = cfg.get(key)
            if v is None or v == "":
                return default
            return float(v)
        except (TypeError, ValueError):
            return default

    if "x" in cfg and "y" in cfg and ("width" in cfg or "w" in cfg) and ("height" in cfg or "h" in cfg):
        x = int(_f("x", 0))
        y = int(_f("y", 0))
        w = int(_f("width", _f("w", 0)))
        h = int(_f("height", _f("h", 0)))
        # 若区域是按某个检测分辨率得到的，而当前切片分辨率不同（如去重/转场裁切），
        # 按比例等比缩放到当前分辨率，避免打码区域错位。
        dw = int(_f("__detect_w", 0))
        dh = int(_f("__detect_h", 0))
        if dw > 0 and dh > 0 and (dw != width or dh != height):
            x = int(round(x * width / dw))
            y = int(round(y * height / dh))
            w = int(round(w * width / dw))
            h = int(round(h * height / dh))
    else:
        w = int(width * _f("width_ratio", SUBTITLE_MASK_WIDTH_RATIO))
        h = int(height * _f("height_ratio", SUBTITLE_MASK_HEIGHT_RATIO))
        x = int((width - w) / 2)
        y = int(height - h - height * _f("bottom_ratio", SUBTITLE_MASK_BOTTOM_RATIO))

    # 边界裁剪
    if w <= 0 or h <= 0:
        return 0, 0, 0, 0
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = min(w, width - x)
    h = min(h, height - y)
    return x, y, w, h


def subtitle_mask_bottom_margin(cfg: dict, width: int, height: int) -> int:
    """计算源字幕打码区域底边到视频底部的像素距离，供 ASR 字幕对齐到打码区域使用。

    开启源字幕对齐时，把 ASR 字幕的 MarginV 设为该值，使新烧录字幕默认落在
    源字幕打码区域内、与被打掉的源字幕位置重合。若区域计算失败返回 -1（调用方
    回退到默认底边距）。

    对齐基准优先取**实际用于打码的字幕区域**的底边，而非固定比例区域：
    - 有 SRT 动态窗口（__dynamic_windows）时，取覆盖时长最长的“主字幕带”底边
      （源字幕最常出现的纵向位置），否则字幕会落到与被打掉源字幕完全不同的
      高度（“ASR 字幕没盖住源字幕/位置错位”的根因）。
    - 其次取多区域（__regions）中最底部字幕带的底边。
    - 均无时回退到 _subtitle_mask_area 的固定区域。
    """
    if width <= 0 or height <= 0:
        return -1

    # ① SRT 动态窗口：把源分辨率窗口换算到当前分辨率，取覆盖时长最长的主字幕带底边。
    dyn = cfg.get("__dynamic_windows")
    if dyn:
        dw = int(cfg.get("__detect_w", 0))
        dh = int(cfg.get("__detect_h", 0))
        cand = []
        for (s0, e0, _sx, sy, _sw, sh) in dyn:
            if dw > 0 and dh > 0 and (dw != width or dh != height):
                ay = int(round(sy * height / dh))
                ah = max(1, int(round(sh * height / dh)))
            else:
                ay, ah = int(sy), int(sh)
            if ay >= height or ay + ah <= 0:
                continue
            cand.append(((ay + ah) * (e0 - s0), ay + ah))
        if cand:
            # 覆盖时长最长的窗口 = 源字幕主带；取其次数加权后的平均底边更稳。
            total = sum(c for c, _ in cand)
            if total > 0:
                bottom = int(round(sum(b * c for c, b in cand) / total))
                return max(0, height - bottom)

    # ② 多区域打码：取最底部区域（通常为主对话字幕带）的底边。
    regions = cfg.get("__regions")
    if regions:
        dw = int(cfg.get("__detect_w", 0))
        dh = int(cfg.get("__detect_h", 0))
        bottoms = []
        for (sx, sy, sw, sh) in regions:
            if dw > 0 and dh > 0 and (dw != width or dh != height):
                ay = int(round(sy * height / dh))
                ah = max(1, int(round(sh * height / dh)))
            else:
                ay, ah = int(sy), int(sh)
            if ay < height and ay + ah > 0:
                bottoms.append(ay + ah)
        if bottoms:
            return max(0, height - max(bottoms))

    # ③ 回退到固定比例/绝对区域。
    x, y, w, h = _subtitle_mask_area(cfg, width, height)
    if w <= 0 or h <= 0:
        return -1
    return max(0, height - (y + h))


def _merge_regions(regions: list[tuple], gap: int = 30) -> list[tuple]:
    """把纵向重叠或相邻（间距 <= gap px）的区域合并为一个。

    多横带检测对相邻很近的字幕带分别扩展上下余量后，区域可能互相重叠（如"旁白"
    与"对话"带只隔几十像素）。重叠区域会被重复打码，虽不影响正确性但浪费且可能
    产生叠加痕迹。这里按纵向合并重叠/相邻区域，横向取并集。
    regions: [(x, y, w, h), ...]。返回合并后的区域列表。
    """
    if not regions:
        return []
    # 按 y 排序
    rs = sorted([(int(r[1]), int(r[0]), int(r[2]), int(r[3])) for r in regions])  # (y, x, w, h)
    merged = [list(rs[0])]
    for (y, x, w, h) in rs[1:]:
        last = merged[-1]
        last_y, last_x, last_w, last_h = last
        # 重叠或相邻
        if y <= last_y + last_h + gap:
            new_y0 = min(last_y, y)
            new_y1 = max(last_y + last_h, y + h)
            new_x0 = min(last_x, x)
            new_x1 = max(last_x + last_w, x + w)
            merged[-1] = [new_y0, new_x0, new_x1 - new_x0, new_y1 - new_y0]
        else:
            merged.append([y, x, w, h])
    # 转回 (x, y, w, h)
    return [(r[1], r[0], r[2], r[3]) for r in merged]


def _scale_regions(regions: list[tuple], cfg: dict, width: int, height: int) -> list[tuple]:
    """把检测分辨率下得到的多区域坐标等比缩放到当前切片分辨率。

    regions: [(x, y, w, h), ...]，基于 __detect_w/__detect_h 检测分辨率。
    若未记录检测分辨率或与当前分辨率一致，直接返回原坐标。
    """
    dw = int(cfg.get("__detect_w") or 0)
    dh = int(cfg.get("__detect_h") or 0)
    if dw > 0 and dh > 0 and (dw != width or dh != height):
        out = []
        for (x, y, w, h) in regions:
            nx = int(round(x * width / dw))
            ny = int(round(y * height / dh))
            nw = int(round(w * width / dw))
            nh = int(round(h * height / dh))
            out.append((nx, ny, nw, nh))
        return out
    return list(regions)


def build_subtitle_mask_filter(cfg: dict, enable: str) -> str:
    """构造源字幕打码 filter_complex 片段（基于 [0:v] 输入，输出标签 [masked]）。

    打码样式：delogo（去字幕/去水印，智能插值，默认）/ mosaic（马赛克）/
    blur（模糊）/ fill（纯色块）。
    enable 非空时仅在字幕时段生效；为空表示全程打码。
    """
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT
    # 区域坐标在调用方预先按实际分辨率计算好，避免 filter 里写表达式
    x = int(cfg.get("__x", 0))
    y = int(cfg.get("__y", 0))
    w = int(cfg.get("__w", 0))
    h = int(cfg.get("__h", 0))
    if w <= 0 or h <= 0:
        return ""
    en = f":enable='{enable}'" if enable else ""

    if style == "delogo":
        # delogo 智能插值：用区域周围像素补平字幕，接近"去水印/去字幕"效果，视觉最自然。
        # 注：部分 ffmpeg 构建（如 Alpine 5.1）的 delogo 未编译 band 选项，这里只传 x/y/w/h。
        return f"[0:v]delogo=x={x}:y={y}:w={w}:h={h}{en}[vout]"
    if style == "mosaic":
        block = int(cfg.get("block") or SUBTITLE_MASK_BLOCK)
        block = max(2, min(64, block))
        bw = max(1, w // block)
        bh = max(1, h // block)
        return (
            f"[0:v]split[src][sub];"
            f"[sub]crop={w}:{h}:{x}:{y},scale={bw}:{bh},scale={w}:{h}"
            f":flags=neighbor[masked];"
            f"[src][masked]overlay={x}:{y}{en}[vout]"
        )
    if style == "blur":
        radius = int(cfg.get("blur_radius") or SUBTITLE_MASK_BLUR_RADIUS)
        radius = max(2, min(11, radius))  # boxblur chroma_param 上限 11
        return (
            f"[0:v]split[src][sub];"
            f"[sub]crop={w}:{h}:{x}:{y},boxblur={radius}:1[masked];"
            f"[src][masked]overlay={x}:{y}{en}[vout]"
        )
    if style == "gblur":
        # 高斯模糊：比 boxblur 更柔和、视觉更自然，且能盖死密集多行字幕。
        sigma = int(cfg.get("blur_sigma") or SUBTITLE_MASK_GBLUR_SIGMA)
        sigma = max(2, min(32, sigma))
        return (
            f"[0:v]split[src][sub];"
            f"[sub]crop={w}:{h}:{x}:{y},gblur=sigma={sigma}[masked];"
            f"[src][masked]overlay={x}:{y}{en}[vout]"
        )
    # fill：纯色块直接盖住
    color = str(cfg.get("color") or "black")
    return f"[0:v]drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill{en}[vout]"


def build_subtitle_mask_filter_multi(cfg: dict, windows: list[tuple],
                                     y: int, h: int, width: int) -> str:
    """构造「仅字幕显示区域」多窗口打码 filter_complex（基于 [0:v]，输出 [vout]）。

    windows: [(local_s, local_e, x, w), ...]，局部时间轴（从 0 开始）与切片分辨率
        坐标；每个窗口只在各自时间段、各自横向子区域打码，而不是整条横带都盖住。
        x 为切片分辨率下的绝对列坐标。
    y/h: 横带区域在切片分辨率的纵向位置与高度（各窗口纵向一致，字幕单行高度固定）。
    width: 视频宽度（用于边界裁剪）。

    各样式实现：
      delogo 直接串联多个 delogo（各带 enable）；
      mosaic/blur 用多路 split+crop+overlay 分支链式叠加；
      fill 串联多个 drawbox（各带 enable）。
    """
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT

    def _clip(x, w, width):
        x = max(0, x)
        w = max(1, min(w, width - x))
        return x, w

    items = []
    for (s, e, x, w) in windows:
        x, w = _clip(x, w, width)
        if w <= 0:
            continue
        items.append((max(0.0, s), max(0.0, e), x, w))
    if not items:
        return ""

    # delogo 要求区域不贴边（需留至少 1px 边界用于周围像素插值），否则会报
    # "Logo area is outside of the frame" 导致转码失败；对 delogo 子区域做边界钳制。
    if style == "delogo":
        for i, (s, e, x, w) in enumerate(items):
            if x < 1:
                w = max(1, w - (1 - x))
                x = 1
            if x + w > width - 1:
                w = max(1, (width - 1) - x)
            items[i] = (s, e, x, w)
        chain = []
        for s, e, x, w in items:
            en = f"between(t,{s:.3f},{e:.3f})"
            chain.append(f"delogo=x={x}:y={y}:w={w}:h={h}:enable='{en}'")
        return "[0:v]" + ",".join(chain) + "[vout]"
    if style == "fill":
        color = str(cfg.get("color") or "black")
        chain = []
        for s, e, x, w in items:
            en = f"between(t,{s:.3f},{e:.3f})"
            chain.append(
                f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill:enable='{en}'")
        return "[0:v]" + ",".join(chain) + "[vout]"
    # mosaic / blur：多路 split + 逐窗口 crop/scale + 链式 overlay
    block = int(cfg.get("block") or SUBTITLE_MASK_BLOCK)
    block = max(2, min(64, block))
    radius = int(cfg.get("blur_radius") or SUBTITLE_MASK_BLUR_RADIUS)
    radius = max(2, min(11, radius))  # boxblur chroma_param 上限 11
    n = len(items)
    split = f"[0:v]split={n + 1}[base]" + "".join(f"[w{i}]" for i in range(n)) + ";"
    parts = []
    for i, (s, e, x, w) in enumerate(items):
        if style == "mosaic":
            bw = max(1, w // block)
            bh = max(1, h // block)
            op = f"scale={bw}:{bh},scale={w}:{h}:flags=neighbor"
        elif style == "gblur":
            sigma = max(2, min(32, int(cfg.get("blur_sigma") or SUBTITLE_MASK_GBLUR_SIGMA)))
            op = f"gblur=sigma={sigma}"
        else:
            op = f"boxblur={radius}:1"
        parts.append(f"[w{i}]crop={w}:{h}:{x}:{y},{op}[m{i}];")
    prev = "[base]"
    for i, (s, e, x, w) in enumerate(items):
        en = f"between(t,{s:.3f},{e:.3f})"
        if i < n - 1:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}:enable='{en}'[v{i + 1}];")
            prev = f"[v{i + 1}]"
        else:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}:enable='{en}'[vout]")
    return split + "".join(parts)


def build_subtitle_mask_filter_multi_region(cfg: dict, regions: list[tuple],
                                        enable: str = "",
                                        width: int = 0, height: int = 0) -> str:
    """构造「多区域打码」filter_complex（基于 [0:v]，输出 [vout]）。

    片源常见"旁白字幕 + 对话字幕 + 顶部/底部水印"等多个文字元素分别落在不同
    纵向横带上，此函数对每个区域各执行一次打码样式，从而把多处文字一并盖掉。

    regions: [(x, y, w, h), ...]，每个区域在切片分辨率下的绝对坐标。
    enable: 打码时间轴表达式；空字符串表示全程打码（所有区域同时生效）。
    width/height: 视频尺寸（用于 delogo 边界钳制）。

    delogo 直接串联多个 delogo；mosaic/blur 用多路 split+crop+overlay 链式叠加；
    fill 串联多个 drawbox。
    """
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT
    en = f":enable='{enable}'" if enable else ""

    def _clip(x, y, w, h):
        if w <= 0 or h <= 0:
            return None
        x = max(0, x); y = max(0, y)
        w = min(w, width - x); h = min(h, height - y)
        if w <= 0 or h <= 0:
            return None
        return x, y, w, h

    items = []
    for (x, y, w, h) in regions:
        r = _clip(x, y, w, h)
        if r is None:
            continue
        items.append(r)
    if not items:
        return ""

    if style == "delogo":
        # delogo 不贴边钳制
        clipped = []
        for (x, y, w, h) in items:
            if x < 1:
                w = max(1, w - (1 - x)); x = 1
            if y < 1:
                h = max(1, h - (1 - y)); y = 1
            if x + w > width - 1:
                w = max(1, (width - 1) - x)
            if y + h > height - 1:
                h = max(1, (height - 1) - y)
            clipped.append((x, y, w, h))
        chain = [f"delogo=x={x}:y={y}:w={w}:h={h}{en}" for (x, y, w, h) in clipped]
        return "[0:v]" + ",".join(chain) + "[vout]"
    if style == "fill":
        color = str(cfg.get("color") or "black")
        chain = [f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill{en}"
                 for (x, y, w, h) in items]
        return "[0:v]" + ",".join(chain) + "[vout]"
    # mosaic / blur：多路 split + 逐区域 crop/scale + 链式 overlay
    block = int(cfg.get("block") or SUBTITLE_MASK_BLOCK)
    block = max(2, min(64, block))
    radius = int(cfg.get("blur_radius") or SUBTITLE_MASK_BLUR_RADIUS)
    radius = max(2, min(11, radius))  # boxblur chroma_param 上限 11
    n = len(items)
    split = f"[0:v]split={n + 1}[base]" + "".join(f"[w{i}]" for i in range(n)) + ";"
    parts = []
    for i, (x, y, w, h) in enumerate(items):
        if style == "mosaic":
            bw = max(1, w // block)
            bh = max(1, h // block)
            op = f"scale={bw}:{bh},scale={w}:{h}:flags=neighbor"
        elif style == "gblur":
            sigma = max(2, min(32, int(cfg.get("blur_sigma") or SUBTITLE_MASK_GBLUR_SIGMA)))
            op = f"gblur=sigma={sigma}"
        else:
            op = f"boxblur={radius}:1"
        parts.append(f"[w{i}]crop={w}:{h}:{x}:{y},{op}[m{i}];")
    prev = "[base]"
    for i, (x, y, w, h) in enumerate(items):
        if i < n - 1:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}{en}[v{i + 1}];")
            prev = f"[v{i + 1}]"
        else:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}{en}[vout]")
    return split + "".join(parts)


def build_subtitle_mask_filter_multi_region_windows(cfg: dict, region_windows: list,
                                                  width: int = 0, height: int = 0) -> str:
    """构造「多区域 × 各自时间窗口」打码 filter_complex（基于 [0:v]，输出 [vout]）。

    片源常含"旁白 + 对话"等多个纵向字幕横带，且各带文字密度/出现时段不同。
    此函数对每个区域 (x, y, w, h) 只在它自己的时间窗口列表内打码，各区域用各自的
    enable 表达式，从而把不同纵向位置、不同时段、不同密度的多带字幕一并盖掉。

    region_windows: [(region, [(src_s, src_e), ...]), ...]，region 为 (x,y,w,h)
        切片分辨率绝对坐标，windows 为局部时间轴（从 0 开始）的出现时段。
    width/height: 视频尺寸（用于 delogo 边界钳制）。
    """
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT

    def _enable(windows: list) -> str:
        if not windows:
            return ""
        terms = [f"between(t,{s:.3f},{e:.3f})" for (s, e) in windows]
        return "+".join(terms)

    # 收集所有 (region, enable) 项
    items = []
    for (x, y, w, h), windows in region_windows:
        if w <= 0 or h <= 0:
            continue
        x = max(0, x); y = max(0, y)
        w = min(w, width - x); h = min(h, height - y)
        if w <= 0 or h <= 0:
            continue
        en = _enable(windows)
        items.append((x, y, w, h, en))
    if not items:
        return ""

    if style == "delogo":
        clipped = []
        for (x, y, w, h, en) in items:
            if x < 1:
                w = max(1, w - (1 - x)); x = 1
            if y < 1:
                h = max(1, h - (1 - y)); y = 1
            if x + w > width - 1:
                w = max(1, (width - 1) - x)
            if y + h > height - 1:
                h = max(1, (height - 1) - y)
            clipped.append((x, y, w, h, en))
        chain = []
        for (x, y, w, h, en) in clipped:
            suffix = f":enable='{en}'" if en else ""
            chain.append(f"delogo=x={x}:y={y}:w={w}:h={h}{suffix}")
        return "[0:v]" + ",".join(chain) + "[vout]"
    if style == "fill":
        color = str(cfg.get("color") or "black")
        chain = []
        for (x, y, w, h, en) in items:
            suffix = f":enable='{en}'" if en else ""
            chain.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill{suffix}")
        return "[0:v]" + ",".join(chain) + "[vout]"
    # mosaic / blur：多路 split + 逐区域 crop/scale + 链式 overlay
    block = int(cfg.get("block") or SUBTITLE_MASK_BLOCK)
    block = max(2, min(64, block))
    radius = int(cfg.get("blur_radius") or SUBTITLE_MASK_BLUR_RADIUS)
    radius = max(2, min(11, radius))
    n = len(items)
    split = f"[0:v]split={n + 1}[base]" + "".join(f"[w{i}]" for i in range(n)) + ";"
    parts = []
    for i, (x, y, w, h, en) in enumerate(items):
        if style == "mosaic":
            bw = max(1, w // block); bh = max(1, h // block)
            op = f"scale={bw}:{bh},scale={w}:{h}:flags=neighbor"
        elif style == "gblur":
            sigma = max(2, min(32, int(cfg.get("blur_sigma") or SUBTITLE_MASK_GBLUR_SIGMA)))
            op = f"gblur=sigma={sigma}"
        else:
            op = f"boxblur={radius}:1"
        parts.append(f"[w{i}]crop={w}:{h}:{x}:{y},{op}[m{i}];")
    prev = "[base]"
    for i, (x, y, w, h, en) in enumerate(items):
        en_suffix = f":enable='{en}'" if en else ""
        if i < n - 1:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}{en_suffix}[v{i + 1}];")
            prev = f"[v{i + 1}]"
        else:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}{en_suffix}[vout]")
    return split + "".join(parts)


def build_subtitle_mask_filter_dynamic(cfg: dict, windows: list, width: int = 0,
                                       height: int = 0) -> str:
    """构造「SRT 驱动动态字幕区域」打码 filter_complex（基于 [0:v]，输出 [vout]）。

    每个窗口有自己的时间区间与紧凑文字外接框 (x, y, w, h)，只在该窗口的时间段、
    该窗口的位置打码。相比固定单区域或空间精细化（y 固定），它能精确覆盖字幕在
    不同时间位于不同纵向/横向位置的情形（旁白 vs 对话），且不会把多个位置合并成
    宽大横带（解决"打码区域太大、盖住半屏"）。

    windows: [(局部_s, 局部_e, 局部_x, 局部_y, 局部_w, 局部_h), ...]，
        局部时间轴（从 0 开始）与切片分辨率绝对坐标。
    width/height: 视频尺寸（用于 delogo 边界钳制）。
    """
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT

    items = []
    for (s, e, x, y, w, h) in windows:
        if w <= 0 or h <= 0 or e <= s:
            continue
        x = max(0, x); y = max(0, y)
        w = min(w, width - x); h = min(h, height - y)
        if w <= 0 or h <= 0:
            continue
        items.append((max(0.0, s), max(0.0, e), x, y, w, h))
    if not items:
        return ""

    if style == "delogo":
        clipped = []
        for (s, e, x, y, w, h) in items:
            if x < 1:
                w = max(1, w - (1 - x)); x = 1
            if y < 1:
                h = max(1, h - (1 - y)); y = 1
            if x + w > width - 1:
                w = max(1, (width - 1) - x)
            if y + h > height - 1:
                h = max(1, (height - 1) - y)
            clipped.append((s, e, x, y, w, h))
        chain = []
        for (s, e, x, y, w, h) in clipped:
            en = f"between(t,{s:.3f},{e:.3f})"
            chain.append(f"delogo=x={x}:y={y}:w={w}:h={h}:enable='{en}'")
        return "[0:v]" + ",".join(chain) + "[vout]"
    if style == "fill":
        color = str(cfg.get("color") or "black")
        chain = []
        for (s, e, x, y, w, h) in items:
            en = f"between(t,{s:.3f},{e:.3f})"
            chain.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill:enable='{en}'")
        return "[0:v]" + ",".join(chain) + "[vout]"
    # mosaic / blur：多路 split + 逐窗口 crop/scale + 链式 overlay
    block = int(cfg.get("block") or SUBTITLE_MASK_BLOCK)
    block = max(2, min(64, block))
    radius = int(cfg.get("blur_radius") or SUBTITLE_MASK_BLUR_RADIUS)
    radius = max(2, min(11, radius))
    n = len(items)
    split = f"[0:v]split={n + 1}[base]" + "".join(f"[w{i}]" for i in range(n)) + ";"
    parts = []
    for i, (s, e, x, y, w, h) in enumerate(items):
        if style == "mosaic":
            bw = max(1, w // block); bh = max(1, h // block)
            op = f"scale={bw}:{bh},scale={w}:{h}:flags=neighbor"
        elif style == "gblur":
            sigma = max(2, min(32, int(cfg.get("blur_sigma") or SUBTITLE_MASK_GBLUR_SIGMA)))
            op = f"gblur=sigma={sigma}"
        else:
            op = f"boxblur={radius}:1"
        parts.append(f"[w{i}]crop={w}:{h}:{x}:{y},{op}[m{i}];")
    prev = "[base]"
    for i, (s, e, x, y, w, h) in enumerate(items):
        en = f"between(t,{s:.3f},{e:.3f})"
        if i < n - 1:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}:enable='{en}'[v{i + 1}];")
            prev = f"[v{i + 1}]"
        else:
            parts.append(f"{prev}[m{i}]overlay={x}:{y}:enable='{en}'[vout]")
    return split + "".join(parts)


def apply_subtitle_mask(video_in: str, video_out: str, cfg: dict,
                        enable: str = "",
                        spatial_windows: Optional[list[tuple]] = None,
                        dynamic_windows: Optional[list[tuple]] = None,
                        seg_times: Optional[list[tuple]] = None,
                        threads: int = 1, encoder: str = "libx264") -> None:
    """对成品视频执行一次源字幕打码（固定区域 + 时间轴驱动）。

    cfg: 打码配置 dict，至少含 enabled 与 style；区域定位字段（比例或绝对坐标）。
    enable: 打码时间轴表达式（局部时间坐标）。空字符串表示全程打码；
        由调用方根据切片源时间段从源 SRT 计算好传入（build_subtitle_mask_enable）。
    spatial_windows: 空间精细化（仅字幕显示区域打码）窗口列表，元素为
        (源_start, 源_end, 源_x, 源_w)。每个窗口只在各自时间段、各自字幕文字实际
        占用的横向子区域打码，而不是整条横带都盖住。提供了则以它为准（忽略 enable）。
    dynamic_windows: SRT 驱动的动态字幕窗口列表，元素为 (源_s, 源_e, 源_x, 源_y,
        源_w, 源_h)。每个窗口有自己的紧凑文字外接框（含纵向），字幕在不同时间位于
        不同位置时各自精确覆盖，且只在 SRT 标注的字幕时段打码。提供了则优先于
        spatial_windows/多区域/全程打码（最精确）。
    seg_times: 切片源时间段 [(start, end), ...]，用于把 spatial_windows/
        dynamic_windows 的源时间轴转换为切片局部时间轴。
    """
    width, height = ffprobe_size(video_in)
    if width <= 0 or height <= 0:
        # 拿不到分辨率时直接复制，避免生成非法 filter
        shutil.copy(video_in, video_out)
        return
    x, y, w, h = _subtitle_mask_area(cfg, width, height)
    if w <= 0 or h <= 0:
        shutil.copy(video_in, video_out)
        return
    # 去重模式若开启了 hflip（水平镜像），画面字幕会被镜像到另一侧，而打码区域
    # 是基于源坐标（未镜像）检测的，这里需把区域 x 同步镜像，否则打码会打到原
    # 字幕已不存在的另一侧（"去重后字幕打码不起作用"的根因之一）。
    if cfg.get("__hflip"):
        x = max(0, width - x - w)
    # delogo 滤镜要求区域完全在画面内且不贴边（需留至少 1px 边界用于周围像素插值）：
    #   x>=1, y>=1, x+w<=width-1, y+h<=height-1。
    # 否则会报 "Logo area is outside of the frame" 导致整次转码失败。
    style = (cfg.get("style") or SUBTITLE_MASK_STYLE_DEFAULT).lower()
    if style not in SUBTITLE_MASK_STYLES:
        style = SUBTITLE_MASK_STYLE_DEFAULT
    if style == "delogo":
        if x < 1:
            w = max(1, w - (1 - x)); x = 1
        if y < 1:
            h = max(1, h - (1 - y)); y = 1
        if x + w > width - 1:
            w = max(1, (width - 1) - x)
        if y + h > height - 1:
            h = max(1, (height - 1) - y)
    cfg["__x"], cfg["__y"], cfg["__w"], cfg["__h"] = x, y, w, h

    # SRT 驱动的动态字幕区域：每个窗口在各自时间段、各自紧凑位置打码，最精确。
    if dynamic_windows:
        scale = float(cfg.get("__scale") or 1.0)
        local = _dynamic_windows_to_local(dynamic_windows, seg_times or [], cfg,
                                          width, height, scale)
        fc = build_subtitle_mask_filter_dynamic(cfg, local, width, height)
    # 空间精细化：仅对字幕文字实际占用的子区域打码。
    elif spatial_windows:
        scale = float(cfg.get("__scale") or 1.0)
        local = _spatial_windows_to_local(spatial_windows, seg_times or [], cfg, width, scale)
        fc = build_subtitle_mask_filter_multi(cfg, local, y, h, width)
    else:
        # 多区域 × 各自时间窗口打码：片源含"旁白+对话字幕"等多个纵向横带，各带
        # 文字密度与出现时段不同（旁白低密度稀出、对话高密度多行）。若只用一个
        # 区域/一个时间轴会漏打（要么旁白被对话的高密度阈值淹没、要么打码 y 只
        # 落在单一高度而漏掉其它高度字幕）。这里对每个区域在其自己的出现时段内
        # 于各自纵向位置打码，从而把不同高度/密度/时段的字幕一并盖掉。
        region_windows = cfg.get("__region_windows")
        if region_windows:
            scale = float(cfg.get("__scale") or 1.0)
            rw_scaled = []
            for (rx, ry, rw, rh), windows in region_windows:
                sx, sy, sw, sh = _scale_region((rx, ry, rw, rh), cfg, width, height)
                if cfg.get("__hflip"):
                    sx = max(0, width - sx - sw)
                # 源时间窗口 → 切片局部时间轴区间（按去重变速 scale 缩放）
                local = _source_intervals_to_local_intervals(windows, seg_times or [], scale)
                rw_scaled.append([(sx, sy, sw, sh), local])
            fc = build_subtitle_mask_filter_multi_region_windows(cfg, rw_scaled, width, height)
        else:
            # 多区域打码：片源含"旁白+对话字幕 + 上下水印"等多个文字横带时，检测出
            # 的 __regions 列表会把所有区域一并打码（覆盖默认单区域，避免漏打其它位置）。
            regions = cfg.get("__regions")
            if regions:
                # 把检测分辨率下的区域等比缩放到当前切片分辨率
                scaled = _scale_regions(regions, cfg, width, height)
                # 去重 hflip 镜像同步（区域 x 镜像到另一侧）
                if cfg.get("__hflip"):
                    scaled = [(max(0, width - rx - rw), ry, rw, rh) for (rx, ry, rw, rh) in scaled]
                fc = build_subtitle_mask_filter_multi_region(cfg, scaled, enable, width, height)
            else:
                fc = build_subtitle_mask_filter(cfg, enable)
    if not fc:
        shutil.copy(video_in, video_out)
        return

    cmd = [
        "ffmpeg", "-y", "-threads", str(threads), "-i", video_in,
        "-filter_complex", fc,
        "-map", "[vout]", "-map", "0:a:0?",
    ]
    cmd += build_encoder_args(encoder, threads)
    cmd += ["-c:a", "aac", "-b:a", "128k", video_out]
    run_ffmpeg(cmd, timeout=3600, threads=threads)


def _video_has_audio(path: str) -> bool:
    """判断视频是否包含音轨，供前置封面片段时决定是否拼接/延迟音频。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return (out.stdout or "").strip() == "audio"
    except Exception:
        return False


def apply_cover_first_frame(video_path: str, cover_path: str, out_path: str,
                         threads: int = 1, encoder: str = "libx264") -> None:
    """在成品开头置入封面图作为视频首帧（单帧封面）。

    封面图等比缩放裁剪填满输出画面，作为成品的**第一帧**（时长 ≈ 1/帧率，
    约 0.04s，肉眼不可感知的瞬间），随后立即进入源内容——满足「首帧是封面图、
    不是整秒被封面占满」的预期。源音频相应延迟封面帧时长以保持音画同步；
    无音轨时仅拼接视频流。
    """
    if not cover_path or not os.path.isfile(cover_path):
        return
    w, h = ffprobe_resolution(video_path)
    if not w or not h:
        w, h = 1280, 720
    fps = ffprobe_framerate(video_path)
    fps_arg = f"fps={fps}" if fps else "fps=25"
    # 首帧封面时长：单帧（1/帧率 秒）。此前实现为 1.5s 前置静止画面，
    # 用户明确要求「首帧而非整秒封面」，改为单帧时长（约 0.04s / 0.033s）。
    # fps 为 ffmpeg 分数形式（如 '30/1' / '30000/1001'），需解析为数值。
    try:
        if fps and "/" in fps:
            _num, _den = fps.split("/", 1)
            _fpsv = float(_num) / float(_den)
        else:
            _fpsv = float(fps) if fps else 25.0
        cover_dur = 1.0 / _fpsv if _fpsv > 0 else 0.04
    except (ValueError, ZeroDivisionError):
        cover_dur = 0.04
    cover_jpg = out_path + ".cover.jpg"
    try:
        # 将封面图等比缩放+裁剪填满输出画面，输出为单张封面帧
        cmd = [
            "ffmpeg", "-y",
            "-i", cover_path,
            "-vf", (
                f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1"
            ),
            "-frames:v", "1",
            cover_jpg,
        ]
        run_ffmpeg(cmd, timeout=3600, threads=threads)
        if not os.path.isfile(cover_jpg):
            return
        # 封面片段：-loop 读封面帧 -> trim 到 cover_dur -> 归一化匹配源视频参数
        cv = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,trim=duration={cover_dur},setpts=PTS-STARTPTS,"
            f"{fps_arg},format=yuv420p[cv]"
        )
        # 源视频也归一化到与封面片段一致（分辨率/帧率/像素格式），保证 concat 可拼接
        # 源视频也归一化到与封面片段一致（分辨率/帧率/像素格式/SAR），保证 concat 可拼接。
        # setsar=1 必须加：源视频 SAR 若为非 1:1（如 2116:2115）会与封面段 SAR 1:1 不匹配，
        # concat 报「Input link parameters do not match」→ -22 Invalid argument（2026-08-20 实测）。
        sv = f"[1:v]{fps_arg},setsar=1,format=yuv420p[sv]"
        if _video_has_audio(video_path):
            # 源音频整体延迟封面时长，使源画面出现时音画同步
            delay_ms = int(cover_dur * 1000)
            fc = (
                f"{cv};{sv};"
                f"[cv][sv]concat=n=2:v=1:a=0[vout];"
                f"[1:a]adelay={delay_ms}|{delay_ms},asetpts=PTS-STARTPTS[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-threads", str(threads),
                "-loop", "1", "-i", cover_jpg,
                "-i", video_path,
                "-filter_complex", fc,
                "-map", "[vout]", "-map", "[aout]",
            ]
        else:
            fc = f"{cv};{sv};[cv][sv]concat=n=2:v=1:a=0[vout]"
            cmd = [
                "ffmpeg", "-y",
                "-threads", str(threads),
                "-loop", "1", "-i", cover_jpg,
                "-i", video_path,
                "-filter_complex", fc,
                "-map", "[vout]",
            ]
        cmd += build_encoder_args(encoder, threads)
        cmd += ["-c:a", "aac", "-b:a", "128k", out_path]
        run_ffmpeg(cmd, timeout=3600, threads=threads)
        print(f"视频封面已作为首帧叠加: {os.path.basename(out_path)}", file=sys.stderr)
    finally:
        try:
            os.unlink(cover_jpg)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("cutlist")
    parser.add_argument("output_dir")
    parser.add_argument("--mode", default="fast", choices=["fast", "dedupe", "scrub"])
    parser.add_argument("--intervals", default=None)
    parser.add_argument(
        "--cpu-percent",
        type=int,
        default=DEFAULT_CPU_PERCENT,
        help=f"CPU 资源分配比例 (%%，默认 {DEFAULT_CPU_PERCENT})，限制 ffmpeg 编码线程数",
    )
    parser.add_argument(
        "--watermark",
        default=None,
        help="动态文字水印配置 JSON（{\"text\":..., \"font_size\":..., \"opacity\":..., \"position\":...}）",
    )
    parser.add_argument(
        "--encoder",
        default=None,
        help="视频编码器（h264_nvenc/hevc_nvenc/h264_videotoolbox/hevc_videotoolbox/libx264），不填自动探测；"
             "可用 SLICE_ENCODER 环境变量强制指定（如 libx264，无 GPU 机器推荐），优先于本参数",
    )
    parser.add_argument(
        "--vert2horiz",
        default=None,
        help="竖屏转横屏预处理配置 JSON（{\"enabled\":true, \"mode\":\"fixed|dynamic\", ...}），切片前把竖屏素材转成横屏",
    )
    parser.add_argument(
        "--badges",
        default=None,
        help="图片角标配置 JSON 数组（[{\"path\":本地图片, \"position\":\"top-left\", \"width\":可选, \"offset\":可选偏移, \"opacity\":可选透明度}]），多角标全程叠加在视频指定位置",
    )
    parser.add_argument(
        "--badge-default-width",
        type=int,
        default=0,
        help="角标默认宽度（px，0=保持原图尺寸）；角标未单独设置 width 时生效",
    )
    parser.add_argument(
        "--text-overlays",
        default=None,
        help="固定文字角标配置 JSON 数组（[{\"text\":文字内容, \"position\":\"left|bottom-left|top-right\", \"font_size\":可选字号, \"color\":可选字体色, \"border_color\":可选描边色, \"vertical\":可选竖排, \"offset\":可选偏移}]），全程叠加在视频指定位置",
    )
    parser.add_argument(
        "--subtitle",
        default=None,
        help="源视频完整 SRT 字幕文件路径（可选）。开启后按每个切片的源时间段截取对应字幕并烧录到成品视频",
    )
    parser.add_argument(
        "--subtitle-font-ratio",
        type=float,
        default=None,
        help="字幕字号（相对输出视频高度的比例，可选，默认 0.20→FontSize 20，约占画面 5pct）。越大字幕越清晰易读",
    )
    parser.add_argument(
        "--subtitle-spacing",
        type=int,
        default=None,
        help="字幕字间距（ASS Spacing 像素，可选，默认 0 更紧凑）。调小/为负可让字幕文字更紧凑，调大则字距变宽",
    )
    parser.add_argument(
        "--subtitle-bold",
        type=int,
        default=None,
        help="字幕字体粗细（ASS Bold：0=不加粗，-1 或 1=加粗，可选，默认 0 不加粗）。加粗让字幕文字更醒目",
    )
    parser.add_argument(
        "--subtitle-align-mask",
        type=lambda v: str(v).lower() not in ("0", "false", "no", "off", ""),
        default=True,
        help="字幕对齐源字幕打码区域（布尔，默认开启）。开启源字幕打码并检测到字幕区域时，"
             "把 ASR 字幕默认位置对齐到打码区域（与被打掉的源字幕位置重合）；关闭则用默认底边距。",
    )
    parser.add_argument(
        "--subtitle-style",
        default=None,
        help="字幕样式（default=白字黑边+半透明黑底；custom=自定义字体色/边框色且无底色，可选，默认 default）",
    )
    parser.add_argument(
        "--subtitle-color",
        default=None,
        help="自定义字幕样式下的字体颜色（CSS 十六进制 #RRGGBB，可选）",
    )
    parser.add_argument(
        "--subtitle-border-color",
        default=None,
        help="自定义字幕样式下的边框颜色（CSS 十六进制 #RRGGBB，可选）",
    )
    parser.add_argument(
        "--dedupe-config",
        default=None,
        help="去重档位配置 JSON（{\"preset\":\"light|standard|heavy|std_retro_scan|std_crop_desat\", \"manual\":{...}}，默认 std_crop_desat）。"
             "preset 选择基础档位；manual 可逐项覆盖四层去重手段参数"
             "（crop/hflip/speed/saturation/gamma/contrast/brightness/colorbalance/"
             "colortemperature/noise/scanline/vignette/roll_band/jitter/sharpen/watermark），"
             "未传 manual 时沿用 preset 预设。未传配置时回退到 preset=std_crop_desat（保守裁切降饱和）。",
    )
    parser.add_argument(
        "--subtitle-mask",
        default=None,
        help="源视频字幕打码配置 JSON（{\"enabled\":true, \"style\":\"delogo|mosaic|blur|gblur|fill\", \"preset\":\"auto|fine|quick\", \"width_ratio\":..., \"height_ratio\":..., \"bottom_ratio\":..., \"srt\":打码时间轴SRT路径}）。默认 delogo（去水印），开启后自动检测字幕位置。preset=打码预设三档：auto=自动（SRT动态窗口优先，兼顾效果与速度，推荐默认）、fine=精细（帧级+空间子区域，最精确更慢）、quick=快速（固定区域全程打码，最快）。也可用旧字段 temporal/spatial 显式开关（向后兼容）。独立开关，仅打掉片源自带字幕",
    )
    parser.add_argument(
        "--watermark-mask",
        default=None,
        help="恒定水印/角标打码配置 JSON（{\"enabled\":true, \"style\":\"delogo|mosaic|blur|gblur|fill\", \"width_ratio\":..., \"height_ratio\":..., \"bottom_ratio\":..., \"top_ratio\":..., \"x\":..., \"y\":..., \"width\":..., \"height\":...}）。开启后自动检测恒定出现的水印/角标区域（区别于间歇对话字幕），无检测结果时回退到指定比例区域（默认底部）。独立开关，仅打掉片源恒定水印",
    )
    parser.add_argument(
        "--cover",
        default=None,
        help="视频封面图片路径（可选）。选择图片作为视频首帧：叠加到成品第一帧（仅首帧显示封面，随即切入源视频内容）",
    )
    args = parser.parse_args()

    threads = cpu_threads_for_percent(args.cpu_percent)
    print(f"CPU 分配: {args.cpu_percent}%% -> ffmpeg 线程数 {threads} (核数 {os.cpu_count() or '?'})", file=sys.stderr)

    encoder = detect_best_encoder(args.encoder)
    print(f"编码器: {encoder}", file=sys.stderr)

    if not os.path.isfile(args.source):
        print(f"Source video not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    # 竖屏转横屏预处理：开启时若素材为竖屏，先转成横屏再切片
    vert2horiz_cfg = parse_vert2horiz_config(args.vert2horiz)
    source_path = args.source
    if vert2horiz_cfg:
        source_path = apply_vert2horiz(source_path, vert2horiz_cfg)

    # 字幕字号：字号本身按输出画面高度比例自适应（约占画面 5%），
    # 横屏/竖屏无需区别对待；用户显式指定 --subtitle-font-ratio 时以用户值为准，
    # 未指定时 burn_subtitle 内部统一用 SUBTITLE_FONT_RATIO。
    subtitle_font_ratio = args.subtitle_font_ratio
    # 字幕字间距：用户显式指定 --subtitle-spacing 时以用户值为准，未指定时用默认值
    subtitle_spacing = args.subtitle_spacing
    # 字幕字体粗细：用户显式指定 --subtitle-bold 时以用户值为准，未指定时用默认值
    subtitle_bold = args.subtitle_bold
    # 字幕对齐源字幕打码区域开关（默认开启）：开启后 ASR 字幕位置对齐到检测到的源字幕打码区域
    subtitle_align_mask = bool(args.subtitle_align_mask)

    os.makedirs(args.output_dir, exist_ok=True)
    cuts = read_cutlist(args.cutlist)
    intervals = read_intervals(args.intervals) if args.mode == "scrub" else []

    # 一键切片整片兜底：候选片段为空时，后端会下发空 cutlist。
    # 非 scrub 模式下这里回退为「整片切片」，保证自动化流程一定出片。
    if not cuts and args.mode != "scrub":
        dur = ffprobe_duration(args.source)
        if dur and dur > 0:
            cuts = [(0.0, dur, "clip_01")]
            print("候选片段为空，一键切片回退为整片切片", file=sys.stderr)

    if args.mode == "scrub":
        segments = subtract_intervals(cuts, intervals)
    else:
        segments = [(s, e, name, idx) for idx, (s, e, name) in enumerate(cuts)]

    if not segments:
        print("PROGRESS:100")
        print("No valid cut segments found", file=sys.stderr)
        # 清理竖屏转横屏临时文件
        if source_path != args.source and os.path.isfile(source_path):
            try:
                os.unlink(source_path)
            except OSError:
                pass
        sys.exit(0)

    vf = None
    af = None
    # 去重模式的时空变换（影响打码/字幕的坐标与时间轴）：
    #   dedupe_speed  - setpts 变速因子（源时间 t 对应输出画面时间 t/speed）
    #   dedupe_hflip  - 是否水平镜像画面（打码区域需按镜像映射，否则打码位置会错）
    # 仅去重模式开启时非默认值，用于对字幕打码区域/时间轴做同步变换，避免"去重后
    # 字幕打码不起作用、ASR 字幕与语音错位"的问题。
    dedupe_speed = 1.0
    dedupe_hflip = False
    if args.mode == "dedupe":
        # 去重模式：默认采用 std_crop_desat 档（保守裁切降饱和，画质几乎无感；
        # 统一不做镜像，明显影响画质的噪点/扫描线/偏色/色温/暗角等降到最低）。
        # --dedupe-config 支持 preset（light/standard/heavy 基础档位）与
        # manual（每项手段手动覆盖），实现"所有去重手段均可手动配置"。
        dedupe_cfg = {}
        if args.dedupe_config:
            try:
                dedupe_cfg = json.loads(args.dedupe_config)
            except (ValueError, TypeError):
                dedupe_cfg = {}
            if not isinstance(dedupe_cfg, dict):
                dedupe_cfg = {}
        preset = str(dedupe_cfg.get("preset") or "std_crop_desat").lower()
        _dedupe_p = _resolve_dedupe_config(dedupe_cfg)
        try:
            dedupe_speed = float(_dedupe_p.get("speed") or 1.0)
        except (TypeError, ValueError):
            dedupe_speed = 1.0
        dedupe_hflip = bool(_dedupe_p.get("hflip", False))
        w, h = ffprobe_resolution(source_path)
        src_fr = ffprobe_framerate(source_path)
        vf, af = build_dedupe_filter(dedupe_cfg, width=w, height=h, framerate=src_fr, source_path=source_path)
        print(f"去重档位: {preset} (speed={dedupe_speed:.3f}, hflip={dedupe_hflip})", file=sys.stderr)

    # 动态文字水印：开启后在去重/普通滤镜基础上叠加 drawtext
    watermark = None
    if args.watermark:
        try:
            watermark = json.loads(args.watermark)
        except (ValueError, TypeError):
            watermark = None
    if watermark:
        wm_filter = build_watermark_filter(watermark)
        vf = f"{vf},{wm_filter}" if vf else wm_filter
        print(f"动态文字水印已开启: {watermark.get('text', '')}", file=sys.stderr)

    # 图片角标：解析并缓存本地图片路径（Worker/后端已下载到本地）
    badges = []
    if args.badges:
        try:
            raw_badges = json.loads(args.badges)
            if isinstance(raw_badges, list):
                badges = raw_badges
        except (ValueError, TypeError):
            badges = []
    if badges:
        valid_paths = [b.get("path") for b in badges if b.get("path") and os.path.isfile(b["path"])]
        print(f"图片角标已开启: {len(valid_paths)} 个", file=sys.stderr)

    # 固定文字角标：解析并准备绘制（最左侧/左下角/右上角等位置）
    text_overlays = []
    if args.text_overlays:
        try:
            raw_texts = json.loads(args.text_overlays)
            if isinstance(raw_texts, list):
                text_overlays = [o for o in raw_texts if isinstance(o, dict)]
        except (ValueError, TypeError):
            text_overlays = []
    if text_overlays:
        print(f"固定文字角标已开启: {len(text_overlays)} 条", file=sys.stderr)

    # 源视频字幕打码：打掉片源自带字幕（独立开关，不依赖 ASR 字幕烧录）。
    # 时间轴优先用 --subtitle-mask 里携带的 srt，其次回退到 args.subtitle。
    subtitle_mask = _parse_subtitle_mask_config(args.subtitle_mask)
    if subtitle_mask:
        if not subtitle_mask.get("srt") and args.subtitle:
            subtitle_mask["srt"] = args.subtitle
        style = subtitle_mask.get("style") or SUBTITLE_MASK_STYLE_DEFAULT
        temporal = bool(subtitle_mask.get("temporal"))
        spatial = bool(subtitle_mask.get("spatial"))
        # 打码预设：把 temporal/spatial 两个独立开关收敛为 自动/精细/快速 三档，降低
        # 配置出错率。未传 preset 时保持旧的 temporal/spatial 显式开关（向后兼容）。
        preset = (subtitle_mask.get("preset") or "").strip().lower()
        if preset in ("auto", "自动", "fine", "精细", "quick", "快速"):
            if preset in ("fine", "精细"):
                # 精细：帧级 + 空间子区域，最精确（更慢）。
                temporal, spatial = True, True
            elif preset in ("quick", "快速"):
                # 快速：固定区域全程打码，最快（不做帧级/时间轴检测）。
                temporal, spatial = False, False
            else:  # auto / 自动
                # 自动：SRT 动态窗口优先，无 SRT 时帧级检测回退；兼顾效果与速度。
                temporal, spatial = True, False
            print(f"源字幕打码已开启: preset={preset}, style={style}, temporal={temporal}, spatial={spatial}", file=sys.stderr)
        else:
            print(f"源字幕打码已开启: style={style}, temporal={temporal}, spatial={spatial}", file=sys.stderr)
        # 去重模式同步标记：apply_subtitle_mask 需按去重的镜像(hflip)与变速(speed)
        # 对打码区域/时间轴做同步变换，否则"去重后字幕打码不起作用"（区域错位+时间错位）。
        if dedupe_hflip:
            subtitle_mask["__hflip"] = True
        if dedupe_speed and dedupe_speed != 1.0:
            subtitle_mask["__scale"] = dedupe_speed
        if not temporal:
            print("提示: temporal=false 会按检测到的字幕区域全程打码（字幕/水印不在的时段也会被马赛克）。"
                  "若字幕只在几帧出现，建议开启 temporal=true 启用帧级检测。", file=sys.stderr)
        # 自动检测字幕真实位置：字幕常在居中偏下而非底部，固定底部横带会打偏。
        # 用 OpenCV 在字幕出现的时刻采样帧，检测文字横带位置；检测成功则覆盖默认区域。
        # 支持多横带（旁白 + 对话字幕可能落在不同纵向位置），返回 list[区域]。
        detect_srt = subtitle_mask.get("srt") or ""
        detected = detect_subtitle_region(source_path, detect_srt)
        detect_w, detect_h = ffprobe_size(source_path)
        if detected:
            # 过滤掉落在画面上半部（<55%）的误检（上部标题/角标/水印），只保留
            # 字幕真实常驻的中下部区域。
            regions = []
            for (dx, dy, dw, dh) in detected:
                if dy + dh < detect_h * 0.55:
                    print(f"源字幕打码自动定位跳过上部误检 ({dx},{dy},{dw},{dh}) @ {detect_w}x{detect_h}",
                          file=sys.stderr)
                    continue
                regions.append((dx, dy, dw, dh))
            if regions:
                # 保留每个独立的字幕子区域（旁白/对话分处不同纵向位置），供"多区域 ×
                # 各自时间窗口"精细化打码逐区域处理，避免合并成大横带后只用一个 y/一个
                # 阈值导致低密度旁白漏打、其它高度字幕漏打。
                subtitle_mask["__regions"] = regions
                # 合并出一个默认区域，用于无 temporal 的兜底与 x/y/width/height 定位。
                merged_regions = _merge_regions(regions)
                subtitle_mask["x"] = merged_regions[0][0]
                subtitle_mask["y"] = merged_regions[0][1]
                subtitle_mask["width"] = merged_regions[0][2]
                subtitle_mask["height"] = merged_regions[0][3]
                subtitle_mask["__detect_w"] = detect_w
                subtitle_mask["__detect_h"] = detect_h
                print(f"源字幕打码自动定位: {len(regions)} 个字幕区域 @ {detect_w}x{detect_h}"
                      + "".join(f" ({dx},{dy},{dw},{dh})" for (dx, dy, dw, dh) in regions), file=sys.stderr)
            else:
                print("源字幕打码自动定位未命中中下部字幕带，回退默认底部横带", file=sys.stderr)
        else:
            print("源字幕打码自动定位失败，回退默认区域（底部横带）", file=sys.stderr)

        # 精细化（temporal）模式：在检测出的区域内按时间采样判断字幕/水印实际
        # 在哪些时段出现，只在出现时打码，其余画面零改动。不依赖 SRT，适用于
        # 任意片源字幕/水印；检测失败时回退到 SRT 时间轴或全程打码。
        if subtitle_mask.get("temporal"):
            # —— 优先走 SRT 时间轴驱动的动态打码（用户的抽帧方案）——
            # 我们已从 ASR 选点拿到源视频的 SRT（标注对话/旁白/字幕出现时刻）。
            # 据此只需在这些时刻抽帧定位字幕文字的紧凑位置，而不是对整段视频逐帧
            # (0.5s 步长) 扫描，检测成本低得多；且每个窗口用自己检测到的紧凑外接框
            # (x,y,w,h)，字幕在不同时间位于不同纵向位置（旁白 vs 对话）时各自精确
            # 覆盖，不会把多个位置合并成宽大横带（解决"打码区域太大"），也只在
            # SRT 标注的字幕时段打码（解决"没字幕也打码"）。
            dynamic_srt = subtitle_mask.get("srt") or ""
            if dynamic_srt and os.path.isfile(dynamic_srt):
                dyn = detect_subtitle_dynamic_regions(source_path, dynamic_srt)
                if dyn:
                    subtitle_mask["__dynamic_windows"] = dyn
                    # 去重变速会把字幕时间轴压缩，这里按 __scale 缩放到成品时间轴。
                    subtitle_mask["__temporal_windows"] = [(s, e) for (s, e, *_ ) in dyn]
                    print(f"源字幕打码 SRT 动态检测: {len(dyn)} 个字幕窗口"
                          + "".join(f" (t={s:.1f}-{e:.1f} @ {x},{y},{w},{h})"
                                    for (s, e, x, y, w, h) in dyn), file=sys.stderr)
            if not subtitle_mask.get("__dynamic_windows"):
                # 无 SRT 或 SRT 驱动检测未命中时，回退到全时间轴逐帧检测。
                region = (int(subtitle_mask.get("x", 0)), int(subtitle_mask.get("y", 0)),
                          int(subtitle_mask.get("width", 0)), int(subtitle_mask.get("height", 0)))
                # 优先用已检测到的实际区域；若区域检测失败，用默认比例区域兜底。
                if region[2] <= 0 or region[3] <= 0:
                    w0, h0 = ffprobe_size(source_path)
                    region = _subtitle_mask_area(subtitle_mask, w0, h0)
                # 多区域帧级检测：片源含旁白+对话字幕等多个纵向横带时，各带文字密度差异
                # 可能很大（旁白单行稀、对话多行密）。若只对合并后的大区域统一取一个
                # temporal 阈值，会被高密度对话带拉高，导致低密度旁白字幕整段漏检
                # （"旁白字幕没有成功识别并打码"根因）。改为对每个子区域分别做 temporal
                # 检测、各用自己的阈值，记录每个区域自己的出现时段；打码时每个区域只在
                # 各自的时段、各自纵向位置打码，避免"用一个 y 覆盖全部导致其他高度字幕漏打"。
                sub_regions = subtitle_mask.get("__regions")
                region_windows = []
                if sub_regions:
                    for sr in sub_regions:
                        sr_tw = detect_subtitle_temporal_windows(source_path, sr)
                        if sr_tw:
                            region_windows.append([sr, [(s, e) for (s, e) in sr_tw]])
                # 无多区域或检测失败时回退到单一整体区域。
                if not region_windows:
                    tw = detect_subtitle_temporal_windows(source_path, region)
                    if tw:
                        region_windows.append([region, [(s, e) for (s, e) in tw]])
                if region_windows:
                    # 汇总总出现时段（用于展示与日志）
                    all_tw = []
                    for _, rw in region_windows:
                        all_tw.extend(rw)
                    all_tw.sort()
                    merged_tw = []
                    for (s, e) in all_tw:
                        if merged_tw and s <= merged_tw[-1][1] + 0.6:
                            merged_tw[-1][1] = max(merged_tw[-1][1], e)
                        else:
                            merged_tw.append([s, e])
                    subtitle_mask["__temporal_windows"] = [(s, e) for (s, e) in merged_tw]
                    subtitle_mask["__region_windows"] = region_windows
                    print(f"源字幕打码帧级检测: {len(region_windows)} 个区域, "
                          f"{sum(len(rw) for _, rw in region_windows)} 个出现时段", file=sys.stderr)
                else:
                    print("源字幕打码帧级检测未命中，回退 SRT 时间轴或全程打码", file=sys.stderr)

    # 恒定水印/角标打码：打掉片源固定水印（独立开关，与字幕打码互不干扰）。
    # 检测原理与字幕相反：水印几乎每帧都在（presence≈1），对话字幕间歇出现（≈0.6）。
    watermark_mask = _parse_subtitle_mask_config(args.watermark_mask)
    if watermark_mask:
        style = watermark_mask.get("style") or SUBTITLE_MASK_STYLE_DEFAULT
        print(f"恒定水印打码已开启: style={style}", file=sys.stderr)
        # 去重 hflip 镜像同步标记（与字幕打码一致）：打码区域基于源坐标检测，
        # 去重镜像后需在 apply_subtitle_mask 内部做 x 镜像，否则水印打码位置会错。
        if dedupe_hflip:
            watermark_mask["__hflip"] = True
        # 自动检测恒定水印区域；显式提供 x/y/width/height 时跳过检测（信任手动配置）。
        if not (watermark_mask.get("x") is not None and watermark_mask.get("y") is not None
                and (watermark_mask.get("width") or watermark_mask.get("w")) is not None
                and (watermark_mask.get("height") or watermark_mask.get("h")) is not None):
            wm_detected = detect_watermark_region(source_path)
            if wm_detected:
                # 支持多个固定水印（顶部 + 底部角标等），全部分别打码。
                # 注意：检测结果先经 _merge_regions 合并重叠/相邻横带，实际打码用
                # 的是合并后的区域（否则同一位置被拆成多个重叠带、日志与实际不一致）。
                wm_merged = _merge_regions(wm_detected)
                watermark_mask["__regions"] = wm_merged
                wx, wy, ww, wh = wm_merged[0]
                watermark_mask["x"] = wx
                watermark_mask["y"] = wy
                watermark_mask["width"] = ww
                watermark_mask["height"] = wh
                detect_w, detect_h = ffprobe_size(source_path)
                watermark_mask["__detect_w"] = detect_w
                watermark_mask["__detect_h"] = detect_h
                print(f"恒定水印打码自动定位: {len(wm_detected)} 个原始带, 合并为 {len(wm_merged)} 个水印区域 @ {detect_w}x{detect_h}"
                      + "".join(f" ({wx},{wy},{ww},{wh})" for (wx, wy, ww, wh) in wm_merged), file=sys.stderr)
            else:
                print("恒定水印打码自动定位失败，回退默认区域（底部水印带）", file=sys.stderr)

    # Group segments by name（而非 idx）：同 name 的多段（如 dedupe 变体拆段）
    # 按顺序拼接为单一输出。scrub 模式下同一 idx 的片段共享同一 name，等效于原行为。
    groups = {}
    for start, end, name, idx in segments:
        groups.setdefault(name, []).append((start, end, name))

    # 字幕开启时，预计算源视频的语音（非静音）区间，用于"只在说话时显示字幕"。
    # 静音/停顿期间字幕自动隐藏，避免字幕一直挂在屏幕上。
    # detect_speech_windows 失败返回 [] 时回退为整段都显示，不影响烧录。
    speech_windows = detect_speech_windows(source_path) if args.subtitle else []

    try:
        outputs = []
        total = len(groups)
        processed = 0
        for name_key in groups:
            group = groups[name_key]
            name = safe_name(name_key)
            out_path = os.path.join(args.output_dir, name)
            parts = []
            with tempfile.TemporaryDirectory() as tmp:
                for i, (start, end, _) in enumerate(group):
                    part = os.path.join(tmp, f"part_{i}.mp4")
                    slice_segment(source_path, start, end, part, vf=vf, af=af, threads=threads, encoder=encoder)
                    parts.append(part)
                concat_segments(parts, out_path, threads=threads, encoder=encoder)
                seg_times = [(s, e) for s, e, _ in group]
                # 源字幕打码：打掉片源自带字幕（在烧录自己的新字幕之前）
                if subtitle_mask:
                    mask_out = out_path + ".masked.mp4"
                    # 精细化（temporal）模式：优先用帧级检测到的"字幕/水印出现时段"，
                    # 把源时间轴窗口转为切片局部时间轴，只在出现时打码。
                    tw = subtitle_mask.get("__temporal_windows") or []
                    # 空间精细化（仅字幕显示区域打码）：在每个出现时段内只对字幕文字
                    # 实际占用的横向子区域打码，而不把整条横带都盖住（需 temporal 开启）。
                    spatial = subtitle_mask.get("__spatial_windows") or []
                    # 多区域 × 各自时间窗口打码：片源含"旁白+对话字幕"等多个纵向横带，
                    # 各带密度/出现时段不同。这里让每个区域在它自己的出现时段、各自
                    # 纵向位置打码，从而把不同高度/密度/时段的字幕一并盖掉（否则漏打
                    # 低密度旁白字幕或只用单一 y 打码导致其它高度字幕漏打）。
                    region_windows = subtitle_mask.get("__region_windows") or []
                    # SRT 驱动的动态字幕区域：每个窗口在各自字幕时段、各自紧凑位置
                    # (x,y,w,h) 打码（最精确）。优先于 region_windows/spatial/全程打码。
                    dynamic_windows = subtitle_mask.get("__dynamic_windows") or []
                    # 普通/快速模式（temporal 与 spatial 均关闭）：在检测出的字幕区域
                    # 全程（至始至终）打码，不再按 SRT 时间轴驱动——否则 SRT 间隙/缺失会
                    # 导致"有时能打有时不能打"，且不符合"区域至始至终盖住"的预期。
                    if dynamic_windows:
                        apply_subtitle_mask(out_path, mask_out, subtitle_mask,
                                            dynamic_windows=dynamic_windows,
                                            seg_times=seg_times,
                                            threads=threads, encoder=encoder)
                        os.replace(mask_out, out_path)
                    elif region_windows:
                        apply_subtitle_mask(out_path, mask_out, subtitle_mask,
                                            seg_times=seg_times,
                                            threads=threads, encoder=encoder)
                        os.replace(mask_out, out_path)
                    elif spatial:
                        apply_subtitle_mask(out_path, mask_out, subtitle_mask,
                                            spatial_windows=spatial,
                                            seg_times=seg_times,
                                            threads=threads, encoder=encoder)
                        os.replace(mask_out, out_path)
                    elif tw:
                        # 去重变速(speed)会压缩画面时间轴，源时间窗口需按 speed 缩放，
                        # 否则 temporal 打码窗口与变速后的画面错位。
                        mask_enable = _source_intervals_to_local_enable(tw, seg_times, dedupe_speed)
                        # 精细化：仅在字幕出现时段打码；该切片内无字幕出现则不打码。
                        if mask_enable:
                            apply_subtitle_mask(out_path, mask_out, subtitle_mask,
                                                enable=mask_enable,
                                                threads=threads, encoder=encoder)
                            os.replace(mask_out, out_path)
                    else:
                        # 普通/快速模式（temporal 与 spatial 均关闭）：
                        # 在自动检测出的字幕区域全程（至始至终）打码，不再按 SRT 时间轴
                        # 驱动——SRT 间隙/缺失会导致"有时能打有时不能打"，且不符合
                        # "定位到字幕区域后至始至终打码"的预期。SRT 时间轴仅用于精细化模式。
                        apply_subtitle_mask(out_path, mask_out, subtitle_mask,
                                            enable="",
                                            threads=threads, encoder=encoder)
                        os.replace(mask_out, out_path)
                # 字幕烧录：开启后按该切片的源时间段从源 SRT 截取并烧录到成品
                if args.subtitle:
                    sub_srt = os.path.join(tmp, "clip_subtitle.srt")
                    # 去重变速(speed)会压缩视频时长，ASR 字幕时间轴需按 speed 缩放，
                    # 否则字幕与语音/画面错位、末尾字幕超出视频时长而显示不全。
                    build_clip_subtitle(args.subtitle, seg_times, sub_srt, speech_windows,
                                        scale=dedupe_speed)
                    sub_out = out_path + ".sub.mp4"
                    # 源字幕对齐：开启对齐开关且有源字幕打码时，把 ASR 字幕默认位置
                    # 对齐到检测到的打码区域（与被打掉的源字幕位置重合）。
                    margin_v = None
                    if subtitle_align_mask and subtitle_mask:
                        cur_w, cur_h = ffprobe_size(out_path)
                        m = subtitle_mask_bottom_margin(subtitle_mask, cur_w, cur_h)
                        if m >= 0:
                            margin_v = m
                    burn_subtitle(out_path, sub_srt, sub_out, threads=threads, encoder=encoder,
                                  font_ratio=subtitle_font_ratio,
                                  spacing=subtitle_spacing,
                                  style=args.subtitle_style,
                                  font_color=args.subtitle_color,
                                  border_color=args.subtitle_border_color,
                                  bold=subtitle_bold,
                                  margin_v=margin_v)
                    os.replace(sub_out, out_path)
            # 恒定水印/角标打码：切片+字幕完成后，打掉片源固定水印（全程打码，
            # 水印是恒定元素无时间轴可言；区域由自动检测或手动 x/y/width/height 指定）。
            if watermark_mask:
                wm_out = out_path + ".wmask.mp4"
                apply_subtitle_mask(out_path, wm_out, watermark_mask,
                                    enable="",
                                    threads=threads, encoder=encoder)
                os.replace(wm_out, out_path)
                print(f"恒定水印打码完成: {os.path.basename(out_path)}", file=sys.stderr)
            # 图片角标：切片完成后在成品上叠加角标（全程覆盖视频指定位置）
            if badges:
                badge_out = out_path + ".badge.mp4"
                apply_badges(
                    out_path, badge_out, badges,
                    threads=threads, encoder=encoder,
                    default_width=args.badge_default_width,
                )
                os.replace(badge_out, out_path)
            # 固定文字角标：在图片角标之后再叠加文字（文字常叠在角标之上层）
            if text_overlays:
                txt_out = out_path + ".textov.mp4"
                apply_text_overlays(
                    out_path, txt_out, text_overlays,
                    threads=threads, encoder=encoder,
                )
                os.replace(txt_out, out_path)
            # 视频封面：将封面叠加到成品第一帧作为视频首帧
            if args.cover:
                cover_out = out_path + ".coverout.mp4"
                apply_cover_first_frame(out_path, args.cover, cover_out, threads=threads, encoder=encoder)
                if os.path.isfile(cover_out):
                    os.replace(cover_out, out_path)
            duration = ffprobe_duration(out_path)
            outputs.append((name, duration))
            processed += 1
            print(f"PROGRESS:{int(processed * 100 / total)}")
            print(f"OUTPUT:{name}:{duration:.3f}")

        print("PROGRESS:100")
    finally:
        # 清理竖屏转横屏临时文件
        if source_path != args.source and os.path.isfile(source_path):
            try:
                os.unlink(source_path)
            except OSError:
                pass


def parse_vert2horiz_config(raw: str) -> dict | None:
    """解析 --vert2horiz 参数（后端下发的 JSON 配置），未启用返回 None。"""
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    return cfg


def apply_vert2horiz(source: str, cfg: dict) -> str:
    """若素材为竖屏，先执行竖屏转横屏预处理，返回转码后的临时文件路径。

    支持 fixed（固定裁切，快速）与 dynamic（动态人脸跟踪）两种模式；
    横屏/方形素材不做处理，直接返回原路径。
    """
    if vert2horiz_crop is None:
        raise RuntimeError(
            "竖屏转横屏已开启，但未安装 OpenCV（vert2horiz_crop 依赖）。"
            "请安装 opencv-python-headless 后重试。"
        )
    src_w, src_h, fps, _total = vert2horiz_crop.get_video_info(source)
    # 仅竖屏素材需要转换（高 > 宽）
    if src_h <= src_w:
        print(f"素材为横屏/方形（{src_w}x{src_h}），跳过竖屏转横屏预处理", file=sys.stderr)
        return source

    mode = (cfg.get("mode") or "fixed").lower()
    if mode not in ("fixed", "dynamic"):
        mode = "fixed"
    ratio = float(cfg.get("ratio") or (9 / 16))
    output_size = cfg.get("output_size") or "1280x720"
    detect_interval = int(cfg.get("detect_interval") or 2)
    smooth_window = int(cfg.get("smooth_window") or 15)
    # 最小移动阈值（源画面像素）：越大越平稳、越小越跟手；默认取引擎侧默认值
    min_step = int(cfg.get("min_step") or vert2horiz_crop.MIN_STEP_DEFAULT)
    # 人脸舒适区边距（占人脸高度的比例）：人脸头像大部分仍在画面内时保持窗口不动，
    # 抑制频繁移动造成的抖动；默认取引擎侧默认值
    face_margin = float(cfg.get("face_margin") or vert2horiz_crop.FACE_MARGIN_DEFAULT)

    # 输出路径加进程唯一后缀：同一任务可能被多个 Worker 并发认领执行（长任务
    # 超过 Redis 认领超时后被重新认领），若多个引擎进程写同一固定路径会互相
    # 覆盖导致文件损坏（moov atom missing）。各进程写各自文件，互不干扰。
    out_path = f"{source}.vert2horiz-{os.getpid()}.mp4"
    print(f"检测到竖屏素材（{src_w}x{src_h}），执行竖屏转横屏预处理（mode={mode}）…", file=sys.stderr)

    # 人脸检测器在 vert2horiz_crop 内部创建（动态/固定共用）
    detector = vert2horiz_crop.FaceDetector()

    if mode == "dynamic":
        faces, _positions = vert2horiz_crop.analyze_faces(
            source,
            detect_interval=detect_interval,
            smooth_window=smooth_window,
            detector=detector,
        )
        crop_params = vert2horiz_crop.generate_dynamic_crop_params(
            faces, src_w, src_h, ratio, min_step=min_step, face_margin=face_margin
        )
        vert2horiz_crop.apply_dynamic_crop(
            source, out_path, crop_params, fps, output_size, min_step=min_step
        )
    else:
        crop_params = vert2horiz_crop.generate_fixed_crop_params(
            detector, source, src_w, src_h, ratio
        )
        vert2horiz_crop.apply_fixed_crop(source, out_path, crop_params, output_size)

    print(f"竖屏转横屏预处理完成: {out_path}（{output_size}）", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    main()
