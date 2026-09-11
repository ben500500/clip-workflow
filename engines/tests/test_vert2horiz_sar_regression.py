#!/usr/bin/env python3
"""竖转横（vert2horiz-crop）输出 SAR 归一化回归测试。

把 issue #351 的验收指标固化为自动化脚本，防止「裁切高度为奇数 ->
scale 改写 SAR -> 播放器显示宽度 >1280（拉伸）」的缺陷回归。

背景：
  crop_h = int(1080 * 9/16) = int(607.5) = 607（奇数，无法被整数命中 16:9）。
  1080:607 的宽高比 1.779242 != 16:9 的 1.777778，ffmpeg 的 scale 默认
  **靠改写 SAR 来保持输入 DAR**，把这点偏差写成 SAR 405:404，
  播放器显示宽度 1280 * 405/404 = 1283.17（画面被横向拉伸）。
  修法：两条滤镜链末尾追加 setsar=1，把输出归一为方形像素。

覆盖的验收指标（issue #351）：
  A. 输出 width=1280 / height=720。
  B. 输出 sample_aspect_ratio=1:1（修复前为 405:404）。
  C. 输出 display_aspect_ratio=16:9（修复前为 180:101）。
  D. fixed 与 dynamic 两条链路都满足 A/B/C。
  E. dynamic 模式的帧数与帧率不变（证明 setsar 未破坏 fps/sendcmd 链路）。

用 ffmpeg 合成 1080x1920（SAR 1:1）竖屏源（无需真实片源），
并直接调用真实的 apply_fixed_crop / apply_dynamic_crop 验证。
若环境缺 ffmpeg 则跳过并提示（不误报失败）。

用法：
  python3 engines/tests/test_vert2horiz_sar_regression.py
退出码：0=通过 / 1=失败 / 2=跳过（依赖缺失）。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

_ENGINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _ENGINES_DIR not in sys.path:
    sys.path.insert(0, _ENGINES_DIR)

# ── 验收阈值（对应 issue #351 讨论结论）──
EXPECT_W = 1280
EXPECT_H = 720
EXPECT_SAR = "1:1"          # 修复前：405:404
EXPECT_DAR = "16:9"         # 修复前：180:101

# 源片几何（issue #351 复现参数）
SRC_W, SRC_H = 1080, 1920
CROP_RATIO = 9 / 16         # -> crop_h = 607（奇数，本缺陷的根因）
FPS = 30
N_FRAMES = 60


def _have(tool):
    return shutil.which(tool) is not None


def _run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def _probe(path):
    """返回视频流几何信息 dict。"""
    out = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,sample_aspect_ratio,display_aspect_ratio,"
        "r_frame_rate,nb_read_frames",
        "-count_frames",
        "-of", "json", path,
    ]).stdout
    return json.loads(out)["streams"][0]


def _load_vert2horiz():
    """加载 engines/vert2horiz_crop.py（cv2/numpy 缺失时用品替身，apply_* 路径不需要真实现）。"""
    spec = importlib.util.spec_from_file_location(
        "vert2horiz_mod", os.path.join(_ENGINES_DIR, "vert2horiz_crop.py"))

    def _stub(name, **attrs):
        if name in sys.modules:
            return
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod

    class _Cascade:
        def __init__(self, *a, **k):
            pass

        def detectMultiScale(self, *a, **k):
            return []

    _stub(
        "cv2",
        data=types.SimpleNamespace(haarcascade_frontalface_default=""),
        CascadeClassifier=_Cascade,
        cvtColor=lambda *a, **k: a[0],
        COLOR_BGR2GRAY=0,
        VideoCapture=object,
        CAP_PROP_FPS=5,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        CAP_PROP_FRAME_COUNT=7,
    )
    _stub(
        "numpy",
        ndarray=list, float32=float, float64=float,
        array=lambda *a, **k: [], mean=lambda *a, **k: 0.0,
        median=lambda *a, **k: 0.0, clip=lambda v, lo, hi: max(lo, min(hi, v)),
        polyfit=lambda *a, **k: [0, 0], poly1d=lambda c: (lambda x: 0),
        linspace=lambda *a, **k: [], arange=lambda *a, **k: [],
        gradient=lambda *a, **k: [], convolve=lambda *a, **k: [],
    )

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_source(path):
    """合成 1080x1920 SAR 1:1 竖屏源 + 音轨。"""
    _run([
        "ffmpeg", "-v", "error",
        "-f", "lavfi", "-i",
        f"testsrc2=size={SRC_W}x{SRC_H}:rate={FPS}:duration={N_FRAMES / FPS:.3f}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={N_FRAMES / FPS:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-y", path,
    ])


def _check(name, failures, label, got, want):
    ok = str(got) == str(want)
    print(f"  [{name}] {label}: got={got} want={want} {'OK' if ok else 'FAIL'}")
    if not ok:
        failures.append(f"{name}.{label}: got={got} want={want}")


def main():
    missing = [t for t in ("ffmpeg", "ffprobe") if not _have(t)]
    if missing:
        print(f"SKIP: 缺少依赖 {missing}，无法运行 SAR 回归测试")
        return 2

    v2h = _load_vert2horiz()

    tmpdir = tempfile.mkdtemp(prefix="v2h_sar_")
    failures = []
    try:
        src = os.path.join(tmpdir, "src_1080x1920.mp4")
        _make_source(src)

        # 前置断言：源必须是 1080x1920 SAR 1:1（否则测试前提不成立）
        sst = _probe(src)
        _check("source", failures, "width", sst["width"], SRC_W)
        _check("source", failures, "height", sst["height"], SRC_H)
        _check("source", failures, "sample_aspect_ratio", sst["sample_aspect_ratio"], "1:1")

        # 复现 issue #351 的真实几何：crop_h = int(1080 * 9/16) = 607（奇数）
        crop_w = SRC_W
        crop_h = int(SRC_W * CROP_RATIO)
        print(f"\n  crop 参数: crop_w={crop_w} crop_h={crop_h} "
              f"(奇数={crop_h % 2 == 1}, {crop_w}:{crop_h}="
              f"{crop_w / crop_h:.6f} vs 16:9={16 / 9:.6f})")
        if crop_h % 2 == 0:
            print("  WARN: crop_h 非奇数，未复现 #351 的几何前提")

        # ── A/B/C/D: fixed 链路 ──
        print("\n[fixed] apply_fixed_crop()")
        fixed_out = os.path.join(tmpdir, "fixed.mp4")
        v2h.apply_fixed_crop(src, fixed_out, {
            "crop_w": crop_w, "crop_h": crop_h, "crop_x": 0, "crop_y": 600,
        }, f"{EXPECT_W}x{EXPECT_H}")
        fst = _probe(fixed_out)
        _check("fixed", failures, "width", fst["width"], EXPECT_W)
        _check("fixed", failures, "height", fst["height"], EXPECT_H)
        _check("fixed", failures, "sample_aspect_ratio", fst["sample_aspect_ratio"], EXPECT_SAR)
        _check("fixed", failures, "display_aspect_ratio", fst["display_aspect_ratio"], EXPECT_DAR)

        # ── A/B/C/D/E: dynamic 链路（走 sendcmd + 缓动）──
        print("\n[dynamic] apply_dynamic_crop()")
        cps = [{
            "frame": i, "crop_w": crop_w, "crop_h": crop_h,
            "crop_x": 0, "crop_y": int(min(300, i * 6)),   # 6px/帧 平滑平移
        } for i in range(N_FRAMES)]
        dyn_out = os.path.join(tmpdir, "dynamic.mp4")
        v2h.apply_dynamic_crop(src, dyn_out, cps, FPS, f"{EXPECT_W}x{EXPECT_H}")
        dst = _probe(dyn_out)
        _check("dynamic", failures, "width", dst["width"], EXPECT_W)
        _check("dynamic", failures, "height", dst["height"], EXPECT_H)
        _check("dynamic", failures, "sample_aspect_ratio", dst["sample_aspect_ratio"], EXPECT_SAR)
        _check("dynamic", failures, "display_aspect_ratio", dst["display_aspect_ratio"], EXPECT_DAR)
        # E: setsar 不得破坏既有 fps/sendcmd 链路 —— 帧数/帧率必须不变
        _check("dynamic", failures, "r_frame_rate", dst["r_frame_rate"], f"{FPS}/1")
        _check("dynamic", failures, "nb_read_frames", dst["nb_read_frames"], N_FRAMES)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    if failures:
        print(f"FAIL: {len(failures)} 项断言未通过")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: 所有 SAR / 几何 / 帧数断言通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
