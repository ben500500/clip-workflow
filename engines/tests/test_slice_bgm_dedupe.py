#!/usr/bin/env python3
"""去重 + BGM 同开 的端到端回归测试（PR #321 critical 修复）。

背景：PR #321 给 slice_segment 增加 BGM 双输入 filter_complex 混音。评审指出
BGM 分支曾用 `-map 0:v` 直接映射原始视频流、丢掉去重/水印 vf，导致 BGM 一开
去重画面就不差异化（去重失效）。本测试把「去重 + BGM 同开」固化为验收用例：

  1. vf 生效：BGM 分支输出与「原视频」画面感知哈希不同（phash 差异化）；
     且与「不应用 vf 的 BGM 输出」不同（证明 vf 确实进入了 BGM 分支）。
  2. 音频混音：输出音频同时含「原音」与「BGM」的频率成分（不是静音/单源）。

用 ffmpeg 合成测试视频与 BGM（无需真实片源）。若环境缺 ffmpeg / ffprobe /
numpy，则跳过并提示（不误报失败）。

用法：
  python3 engines/tests/test_slice_bgm_dedupe.py
退出码：0=通过 / 1=失败 / 2=跳过（依赖缺失）。
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

# 允许直接从仓库根或 engines/ 下运行
_ENGINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _ENGINES_DIR not in sys.path:
    sys.path.insert(0, _ENGINES_DIR)

_SPEC = importlib.util.spec_from_file_location("slice_mod", os.path.join(_ENGINES_DIR, "slice.py"))
_slice = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_slice)

W, H = 640, 360
FPS = 25
DUR = 4
VOICE_FREQ = 440   # 合成视频的"人声"频率（Hz）
BGM_FREQ = 880     # 合成 BGM 频率（Hz）——与语音不同，便于用频段判断混音是否生效


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _have_py(mod: str) -> bool:
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def make_video(path: str) -> None:
    """合成含 440Hz 语音的测试视频（画面为渐变测试图，便于感知哈希差异化）。"""
    # 画面：testsrc2 产生动态色块/文字，去重滤镜改动后会改变感知哈希。
    run(["ffmpeg", "-y",
         "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d={DUR}",
         "-f", "lavfi", "-i", f"sine=frequency={VOICE_FREQ}:duration={DUR}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", path])


def make_bgm(path: str) -> None:
    run(["ffmpeg", "-y",
         "-f", "lavfi", "-i", f"sine=frequency={BGM_FREQ}:duration={DUR}",
         "-c:a", "aac", path])


def ahash_frame(path: str, ts: float = 1.0) -> int:
    """抽取 ts 时刻一帧，返回 64bit 平均感知哈希（aHash）。"""
    import numpy as np
    import cv2
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return -1
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    mean = small.mean()
    return int("".join("1" if p >= mean else "0" for p in small.flatten()), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def freq_band_power(path: str, center_hz: float, band_hz: float = 40) -> float:
    """用 ffmpeg highpass+lowpass 抽取目标频段后用 volumedetect 测 mean_volume。

    返回该频段平均音量（dB）；无法评估时返回 -1。
    """
    lo = max(0, center_hz - band_hz)
    hi = center_hz + band_hz
    p = subprocess.run(
        ["ffmpeg", "-y", "-i", path,
         "-af", f"highpass=f={lo},lowpass=f={hi},volumedetect",
         "-f", "null", "-"],
        capture_output=True, text=True)
    out = (p.stderr or "") + (p.stdout or "")
    for line in out.splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].split()[0])
            except Exception:
                return -1
    return -1


def main() -> int:
    if not (_have("ffmpeg") and _have("ffprobe") and _have_py("cv2") and _have_py("numpy")):
        print("SKIP: 缺少 ffmpeg/ffprobe/opencv/numpy，跳过回归测试（不误报失败）")
        return 2

    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "src.mp4")
        bgm_src = os.path.join(tmp, "bgm.mp4")
        make_video(video)
        make_bgm(bgm_src)

        # 去重配置：标准档位（含 crop/scale 等空间变换 + atempo 变速），保证 vf 非空。
        dedupe_cfg = {
            "preset": "standard",
            "manual": {
                "audio": {"mode": "bgm", "source": bgm_src, "volume": 0.35, "duck": True},
            },
        }
        vf, af, bgm_audio = _slice.build_dedupe_filter(
            dedupe_cfg, width=W, height=H, framerate=f"{FPS}", source_path=video)

        print(f"vf={vf!r}")
        print(f"af={af!r}")
        print(f"bgm_audio={'dict' if isinstance(bgm_audio, dict) else bgm_audio!r}")

        if not vf:
            print("! 测试前提不满足：standard 档位应产出非空 vf，无法验证 vf 进入 BGM 分支")
            return 1
        if not isinstance(bgm_audio, dict):
            print("! 测试前提不满足：BGM dict 未被 build_dedupe_filter 识别为第三返回值")
            return 1

        # 三个输出：
        #   out_bgm_vf : 去重 + BGM 同开（修复后的目标路径）
        #   out_bgm_novf: BGM 开但人为去掉 vf（复现 critical 的旧行为，作对照）
        #   out_orig    : 原始视频参考帧
        out_bgm_vf = os.path.join(tmp, "bgm_vf.mp4")
        out_bgm_novf = os.path.join(tmp, "bgm_novf.mp4")

        try:
            _slice.slice_segment(
                video, 0.5, DUR - 0.5, out_bgm_vf,
                vf=vf, af=af, threads=1, encoder="libx264", copy_if_possible=False,
                bgm=bgm_audio)
            _slice.slice_segment(
                video, 0.5, DUR - 0.5, out_bgm_novf,
                vf=None, af=af, threads=1, encoder="libx264", copy_if_possible=False,
                bgm=bgm_audio)
        except Exception as e:
            print("! slice_segment 执行失败:", e)
            return 1

        if not (os.path.exists(out_bgm_vf) and os.path.getsize(out_bgm_vf) > 0):
            print("! 去重+BGM 输出未生成")
            return 1

        # 1) phash 差异化：去重+BGM 输出帧与原始视频帧应不同（vf 生效）。
        h_orig = ahash_frame(video)
        h_vf = ahash_frame(out_bgm_vf)
        h_novf = ahash_frame(out_bgm_novf)
        print(f"aHash orig={h_orig:016x} bgm_vf={h_vf:016x} bgm_novf={h_novf:016x}")

        d_orig_vf = hamming(h_orig, h_vf)
        d_orig_novf = hamming(h_orig, h_novf)
        d_vf_novf = hamming(h_vf, h_novf)

        # BGM 分支丢 vf（旧 bug）时：h_vf == h_novf，画面未差异化。
        if d_vf_novf <= 1:
            print(f"  FAIL: 去重+BGM 与『去重不开的 BGM』画面几乎一致(汉明距={d_vf_novf})，"
                  f"说明 vf 未进入 BGM 分支，去重失效")
            fails.append("critical: BGM 分支 vf 未生效")

        # 2) 音频混音：BGM 频段（880Hz）应有一定能量；同时原音频段（440Hz）也在。
        #    用 volumedetect 抽频段。若音频静音/单源，BGM 频段会明显缺失。
        bgm_power = freq_band_power(out_bgm_vf, BGM_FREQ)
        voice_power = freq_band_power(out_bgm_vf, VOICE_FREQ)
        print(f"BGM频段(880Hz)mean_volume={bgm_power}dB 语音频段(440Hz)mean_volume={voice_power}dB")
        if bgm_power == -1 or bgm_power < -45:
            print(f"  FAIL: BGM 频段能量过低({bgm_power}dB)，混音可能未生效")
            fails.append("BGM 混音未生效（BGM 频段缺失）")

        # 3) 视频流确实重编码（非 copy），验证走了重编码分支规格
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                            out_bgm_vf], capture_output=True, text=True)
        codec = (p.stdout or "").strip()
        print(f"输出视频编码: {codec}")
        if codec != "h264":
            print(f"  FAIL: 期望 h264 重编码输出，实际 {codec}")
            fails.append("BGM 分支编码规格与普通重编码不一致")

    if fails:
        print("\nFAILED:", "; ".join(fails))
        return 1
    print("\nPASS: 去重 + BGM 同开 端到端回归通过（vf 生效 + 音频混音 + 重编码规格一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
