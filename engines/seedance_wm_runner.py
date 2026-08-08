#!/usr/bin/env python3
"""Seedance 去水印引擎执行入口（集成自 ben500500/remover 仓库的 seedance_wm 包）。

该脚本将 remover 仓库的 5 阶段流水线（抽帧 → 检测 → mask → 修复+平滑 → 合成）
封装为 clip-workflow watermark_runner 可调用的 CLI，沿用 PROGRESS:<pct> 进度约定：

    python seedance_wm_runner.py <input> -o <output> [options]

支持的选项：
  -r, --region  x,y,w,h   手动指定水印区域（跳过自动检测）
  --roi-experience NAME   借 remove-mask 内置 ROI 经验库（按原始文件名匹配，如
                          648BC321 / C0CC0472 / 0270150E / 3906E761）
                          · 自动检测到水印时与经验 ROI 合并，可一次覆盖左上+右下
  --backend     auto/lama/migan/cv2
                          - auto / lama / migan：通过 remove-ai-watermarks 的
                            LaMa-ONNX / MI-GAN-ONNX CPU 模型进行高质量修补
                            （未安装时自动降级到 OpenCV TELEA）
                          - cv2：OpenCV TELEA 经典修补（无需额外模型）
  --segments    N         分段检测段数（水印在视频中移动时调大，默认 4）
  --detector    主检测器（matchTemplate/yolov8_seg/paddleocr，默认 matchTemplate）
  --inpainter   主修复器（lama/cv2_telea/cv2_ns，默认按 config.yaml）
  --config      YAML 配置文件路径
  --no-audio              合成时不保留原音轨
  --yes                   跳过免责声明确认（无人值守部署必用）
"""

import argparse
import os
import sys
import tempfile

# 允许以源码方式直接运行（engines/seedance_wm 与脚本同目录）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from seedance_wm.cli import _confirm_disclaimer  # noqa: E402
from seedance_wm.config import Config  # noqa: E402
from seedance_wm.errors import WatermarkRemoverError  # noqa: E402
from seedance_wm.ffmpeg_io import check_ffmpeg  # noqa: E402
from seedance_wm.remover import Remover  # noqa: E402


def _parse_region(text: str):
    parts = [int(p.strip()) for p in text.split(",")]
    if len(parts) != 4 or any(v < 0 for v in parts):
        raise ValueError
    return parts


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seedance_wm_runner",
        description="Seedance 去水印引擎（seedance_wm 5 阶段流水线）",
    )
    p.add_argument("input", help="输入视频路径")
    p.add_argument("-o", "--output", help="输出视频路径")
    p.add_argument("-r", "--region", help="手动水印区域 x,y,w,h（跳过自动检测）")
    p.add_argument(
        "--roi-experience",
        default=None,
        help="借 remove-mask 内置 ROI 经验库：原始文件名（自动匹配 8 位码），自动检测时合并",
    )
    p.add_argument(
        "--backend",
        choices=["auto", "lama", "migan", "cv2"],
        default="auto",
        help="修补后端（auto: LaMa-ONNX>MI-GAN-ONNX>cv2，CPU）",
    )
    p.add_argument("--segments", type=int, default=4, help="分段检测段数（默认 4）")
    p.add_argument("--detector", default=None, help="主检测器")
    p.add_argument("--inpainter", default=None, help="主修复器")
    p.add_argument("-c", "--config", default=None, help="YAML 配置路径")
    p.add_argument("--no-audio", action="store_true", help="合成时不保留原音轨")
    p.add_argument("--yes", action="store_true", help="跳过免责声明确认")
    p.add_argument("--keep-cache", action="store_true", help="保留 cache（调试）")
    return p


def _apply_backend(config: Config, backend: str) -> None:
    """把 clip-workflow 的 backend 语义映射到 seedance_wm 的修复器。

    - auto/lama -> 优先 LaMa（lama 依赖缺失时 pipeline 自动降级 cv2）
    - migan     -> seedance_wm 无 MI-GAN 直接支持，退化为 cv2_telea
                   （MI-GAN 高质量修补由 remove-ai-watermarks 引擎提供）
    - cv2       -> cv2_telea
    """
    if backend == "cv2" or backend == "migan":
        config.inpainter.primary = "cv2_telea"
        config.inpainter.fallback = ["cv2_ns"]
    else:  # auto / lama 统一尝试 lama，缺失自动降级 cv2
        config.inpainter.primary = "lama"
        config.inpainter.fallback = ["cv2_telea", "cv2_ns"]


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    if not args.output:
        root, ext = os.path.splitext(args.input)
        args.output = f"{root}_clean{ext or '.mp4'}"

    # 加载配置
    config = Config()
    cfg_path = args.config
    if not cfg_path:
        default_cfg = os.path.join(_HERE, "seedance_wm", "config", "config.yaml")
        if os.path.isfile(default_cfg):
            cfg_path = default_cfg
    if cfg_path and os.path.isfile(cfg_path):
        try:
            config = Config.from_yaml(cfg_path)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 加载配置 {cfg_path} 失败，使用默认配置: {e}", file=sys.stderr)

    # CLI 覆盖
    if args.detector:
        config.detector.primary = args.detector
    if args.inpainter:
        config.inpainter.primary = args.inpainter
    if args.no_audio:
        config.output.keep_audio = False
    if not args.keep_cache:
        config.cache.auto_clean = True
    _apply_backend(config, args.backend)

    try:
        check_ffmpeg()
    except WatermarkRemoverError as e:
        print(f"[ERROR] {e.message}", file=sys.stderr)
        return e.exit_code

    # 免责声明：无人值守部署默认 --yes
    if not args.yes and not _confirm_disclaimer():
        print("已退出。", file=sys.stderr)
        return 0

    bbox = None
    if args.region:
        try:
            bbox = _parse_region(args.region)
        except ValueError:
            print("Error: --region 格式错误，应为 x,y,w,h（如 10,5,120,60）", file=sys.stderr)
            return 1

    # 借 remove-mask 经验库：按原始文件名匹配内置 ROI，命中时在自动检测基础上
    # 合并经验位置（手动区域最高优先级，此时不叠加经验）。
    bboxes = None
    if bbox is None and args.roi_experience:
        try:
            from remove_mask_rois import match_rois, probe_video_size, rois_to_bboxes

            rois = match_rois(args.roi_experience)
            if rois:
                width, height = probe_video_size(args.input)
                if width > 0 and height > 0:
                    bboxes = [list(b) for b in rois_to_bboxes(rois, width, height)]
                    print(
                        f"[info] 命中 remove-mask 内置 ROI 经验库: "
                        f"{list(rois.keys())} → {bboxes}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"[warn] 命中经验库但无法探测视频尺寸，跳过经验 ROI: {args.input}",
                        file=sys.stderr,
                    )
            else:
                print(
                    f"[info] 未命中 remove-mask 内置 ROI 经验库: {args.roi_experience}",
                    file=sys.stderr,
                )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 加载 remove-mask 经验库失败: {e}", file=sys.stderr)

    # 确保 cache 目录可写
    cache_dir = getattr(config.cache, "dir", None) or "/tmp/watermark/seedance_wm_cache"
    os.makedirs(cache_dir, exist_ok=True)

    remover = Remover(config)
    try:
        result = remover.process(args.input, args.output, bbox=bbox, bboxes=bboxes)
    except WatermarkRemoverError as e:
        print(f"[ERROR] {e.message} (exit={e.exit_code})", file=sys.stderr)
        return e.exit_code
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 未捕获异常: {e}", file=sys.stderr)
        return 10

    if result.success:
        print(
            f"✓ {args.input} → {args.output} "
            f"(size={result.size_bytes / 1024 / 1024:.1f}MB, "
            f"dur={result.duration_sec:.2f}s, elapsed={result.elapsed_sec:.1f}s, "
            f"method={result.method})"
        )
        return 0
    print(f"✗ 处理失败: {result.error} (exit={result.exit_code})", file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
