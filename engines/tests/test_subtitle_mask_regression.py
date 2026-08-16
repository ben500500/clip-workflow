#!/usr/bin/env python3
"""源字幕打码（subtitle-mask）回归测试。

把 PR #148 验证的验收指标固化为自动化脚本，防止「打码区域过大 / ASR字幕错位 /
文字没盖掉」等回归。

覆盖的验收指标：
  A. 动态打码区高度 ≤ 9% 屏高（PR #148：横屏 55%→7~11%、竖屏 40%→5%）。
  B. 源字幕文字密度下降 ≥ 60%（打码后源字幕文字被有效抹掉）。

用 ffmpeg 合成测试视频 + SRT（无需真实片源），并在本地跑 detect_subtitle_dynamic_regions
与 apply 打码滤镜验证。若环境缺 ffmpeg / opencv / numpy，则跳过并提示（不误报失败）。

用法：
  python3 engines/tests/test_subtitle_mask_regression.py
退出码：0=通过 / 1=失败 / 2=跳过（依赖缺失）。
"""
import os
import shutil
import subprocess
import sys
import tempfile

# 允许直接从仓库根或 engines/ 下运行
_ENGINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _ENGINES_DIR not in sys.path:
    sys.path.insert(0, _ENGINES_DIR)

import importlib.util  # noqa: E402
_SPEC = importlib.util.spec_from_file_location("slice_mod", os.path.join(_ENGINES_DIR, "slice.py"))
_slice = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_slice)

# ── 验收阈值（对应 PR #148 讨论结论）──
MAX_REGION_HEIGHT_RATIO = 0.09   # 动态打码区 ≤ 9% 屏高
MIN_TEXT_DENSITY_DROP = 0.60     # 源字幕文字密度下降 ≥ 60%

# 合成测试参数
W, H = 640, 360
FPS = 25
DUR = 10
SUBTITLE_TEXT = "HELLO WORLD SUBTITLE LINE"
SUBTITLE_Y = H - 76           # 字幕条位置（底部偏上），高度约 30px ≈ 8.3% 屏高
SUBTITLE_H = 30


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _have_py(mod: str) -> bool:
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def make_video(video_path: str, audio_path: str = "") -> None:
    """合成带金色字幕的测试视频。"""
    if audio_path and _have("ffmpeg"):
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x404060:s={W}x{H}:d={DUR}:r={FPS}",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % DUR,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
             video_path],
            check=True, capture_output=True,
        )
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x404060:s={W}x{H}:d={DUR}:r={FPS}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", video_path],
            check=True, capture_output=True,
        )
    # 叠加金色字幕（每 0.5s~9.5s 持续出现，跨多个 SRT 窗口）
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path,
         "-vf", (f"drawtext=text='{SUBTITLE_TEXT}':fontcolor=yellow:fontsize=24:"
                 f"x=(w-text_w)/2:y={SUBTITLE_Y}:box=1:boxcolor=black@0.5:boxborderw=4"),
         "-c:a", "copy", video_path + ".tmp.mp4"],
        check=True, capture_output=True,
    )
    os.replace(video_path + ".tmp.mp4", video_path)


def make_srt(srt_path: str) -> None:
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(
            "1\n00:00:00,500 --> 00:00:03,000\n" + SUBTITLE_TEXT + "\n\n"
            "2\n00:00:04,000 --> 00:00:07,000\n" + SUBTITLE_TEXT + "\n\n"
            "3\n00:00:08,000 --> 00:00:09,500\n" + SUBTITLE_TEXT + "\n"
        )


def run(cmd: list) -> bool:
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print("  ! 命令失败:", " ".join(cmd), file=sys.stderr)
        print("    stderr:", e.stderr.decode(errors="ignore")[-500:], file=sys.stderr)
        return False


def text_density(video_path: str, ts: float, box) -> float:
    """抽取 ts 时刻一帧，统计打码区域 box=(x,y,w,h) 内文字色（亮色）像素占比。"""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return 0.0
    x, y, w, h = box
    sub = frame[y:y + h, x:x + w, :]
    if sub.size == 0:
        return 0.0
    b = sub[:, :, 0].astype(np.int16)
    g = sub[:, :, 1].astype(np.int16)
    r = sub[:, :, 2].astype(np.int16)
    # 金色/白色字幕掩码（与 slice.py detect 逻辑一致）
    gold = (r > 130) & (g > 110) & (b < 160) & (r - b > 50) & (g - b > 40) & (abs(r - g) < 110)
    white = (r > 170) & (g > 170) & (b > 170) & (abs(r - g) < 45) & (abs(g - b) < 45) & (abs(r - b) < 45)
    mask = (gold | white).astype(np.float64)
    return float(mask.mean())


def main() -> int:
    if not (_have("ffmpeg") and _have("ffprobe") and _have_py("cv2") and _have_py("numpy")):
        print("SKIP: 缺少 ffmpeg/ffprobe/opencv/numpy，跳过回归测试（不误报失败）")
        return 2

    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "sub.mp4")
        srt = os.path.join(tmp, "sub.srt")
        masked = os.path.join(tmp, "masked.mp4")

        print("合成测试视频/字幕...")
        make_video(video)
        make_srt(srt)

        # ── 测试 A：动态打码区 ≤ 9% 屏高 ──
        print("测试 A：动态打码区高度 ≤ 9% 屏高")
        regions = _slice.detect_subtitle_dynamic_regions(video, srt)
        if not regions:
            print("  ✗ FAIL: 未检测到动态字幕区域")
            fails.append("A: 未检测到动态字幕区域")
        else:
            ok = True
            for (s, e, x, y, w, h) in regions:
                ratio = h / H
                status = "OK" if ratio <= MAX_REGION_HEIGHT_RATIO else "FAIL"
                print(f"  窗口 {s:.1f}-{e:.1f} 区域 ({x},{y},{w},{h}) 高 {h}px={ratio*100:.1f}%屏高 [{status}]")
                if ratio > MAX_REGION_HEIGHT_RATIO:
                    ok = False
            if not ok:
                fails.append("A: 存在打码区高度超过 9% 屏高")

        # ── 测试 B：打码后源字幕文字密度下降 ≥ 60% ──
        print("测试 B：源字幕文字密度下降 ≥ 60%")
        if regions:
            # 取首个窗口作为打码区域（实际 apply 会用合并后的所有窗口）
            (s0, e0, rx, ry, rw, rh) = regions[0]
            box = (rx, ry, rw, rh)
            before = text_density(video, (s0 + e0) / 2, box)
            # 应用动态打码滤镜
            cfg = {"enabled": True, "style": "delogo", "preset": "auto"}
            local = _slice._dynamic_windows_to_local(
                regions, [(s0, e0)], cfg, W, H, 1.0)
            fc = _slice.build_subtitle_mask_filter_dynamic(cfg, local, W, H)
            if not fc:
                print("  ✗ FAIL: 动态打码滤镜构建为空")
                fails.append("B: 动态打码滤镜构建为空")
            else:
                cmd = ["ffmpeg", "-y", "-i", video, "-filter_complex", fc,
                       "-map", "[vout]", "-map", "0:a:0?", "-c:v", "libx264",
                       "-c:a", "aac", "-shortest", masked]
                if run(cmd):
                    after = text_density(masked, (s0 + e0) / 2, box)
                    drop = (before - after) / before if before > 0 else 0.0
                    status = "OK" if drop >= MIN_TEXT_DENSITY_DROP else "FAIL"
                    print(f"  文字密度: 前={before:.4f} 后={after:.4f} 下降={drop*100:.1f}% [{status}]")
                    if drop < MIN_TEXT_DENSITY_DROP:
                        fails.append(f"B: 文字密度仅下降 {drop*100:.1f}%（需 ≥ {MIN_TEXT_DENSITY_DROP*100:.0f}%）")
                else:
                    fails.append("B: ffmpeg 应用打码失败")
        else:
            fails.append("B: 因未检测到区域而跳过（A 已失败）")

    if fails:
        print("\n回归测试失败：")
        for f in fails:
            print("  -", f)
        return 1
    print("\n回归测试全部通过 ✅（动态打码区 ≤9% 屏高 + 文字密度下降 ≥60%）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
