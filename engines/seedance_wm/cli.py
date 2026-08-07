"""CLI 主入口（API 文档 §1）。

命令:
  remove-wm -i input.mp4 -o output.mp4 [options]
  remove-wm --batch --input-dir ./in --output-dir ./out [options]
"""

from __future__ import annotations

import argparse
import sys

from seedance_wm import __version__
from seedance_wm.config import Config
from seedance_wm.errors import (
    EXIT_UNKNOWN,
    InvalidArgsError,
    WatermarkRemoverError,
)
from seedance_wm.ffmpeg_io import check_ffmpeg
from seedance_wm.log import add_file_handler, get_logger, set_level
from seedance_wm.remover import Remover

log = get_logger("cli")

DISCLAIMER = """\
========================================
Seedance 视频去水印工具 · 免责声明
========================================

本工具仅供合法的二次创作、研究学习使用。

禁止用途：
1. 冒充真人拍摄内容在社交平台发布
2. 绕过平台 AIGC 内容审核机制
3. 制作虚假新闻、诈骗、违规内容
4. 侵犯他人合法权益

继续使用即表示您同意：
- 您拥有输入视频的合法使用权
- 您将遵守所在国家 / 地区的法律法规
- 您将遵守各内容平台的使用政策
- 您将对使用本工具的一切后果负责

开发者不对任何滥用行为承担责任。

[Y] 我已阅读并同意，继续   [N] 退出
========================================
"""


def _parse_bbox(text: str) -> list[int] | None:
    """解析 'x,y,w,h' -> [x, y, w, h]。"""
    try:
        parts = [int(p.strip()) for p in text.split(",")]
        if len(parts) != 4:
            raise ValueError
        if any(v < 0 for v in parts):
            raise ValueError
        return parts
    except ValueError:
        raise InvalidArgsError(f"bbox 格式错误: '{text}'，应为 x,y,w,h（如 1700,980,180,40）") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="remove-wm",
        description="Seedance AI 视频去水印（5 阶段本地流水线，全开源零授权费）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  remove-wm -i in.mp4 -o out.mp4\n"
            "  remove-wm -i in.mp4 -o out.mp4 --device cpu --inpainter cv2_telea\n"
            "  remove-wm -i in.mp4 -o out.mp4 --bbox 1700,980,180,40\n"
            "  remove-wm --batch --input-dir ./in --output-dir ./out --workers 4\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"seedance-wm {__version__}")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--batch", action="store_true", help="批量处理模式")

    # 单文件参数
    parser.add_argument("-i", "--input", help="输入视频路径")
    parser.add_argument("-o", "--output", help="输出视频路径")
    # 批量参数
    parser.add_argument("--input-dir", help="批量输入目录")
    parser.add_argument("--output-dir", help="批量输出目录")
    parser.add_argument("--workers", type=int, default=1, help="批量并行线程数（默认 1）")
    parser.add_argument("--skip-existing", action="store_true", help="跳过已存在的输出")
    parser.add_argument("--retry-failed", type=int, default=0, help="失败重试次数")
    parser.add_argument("--failed-log", default="failed.log", help="失败日志路径")
    parser.add_argument("--extensions", nargs="+", default=None, help="扫描扩展名，如 mp4 mov avi")

    # 通用参数
    parser.add_argument("-d", "--detector", default=None, help="主检测器 (matchTemplate/yolov8_seg/paddleocr)")
    parser.add_argument("--detector-fallback", nargs="+", default=None, help="检测器降级链")
    parser.add_argument("--inpainter", default=None, help="主修复器 (lama/cv2_telea/cv2_ns)")
    parser.add_argument("--inpainter-fallback", nargs="+", default=None, help="修复器降级链")
    parser.add_argument("--device", default=None, help="auto/cuda/cpu")
    parser.add_argument("-b", "--bbox", default=None, help="手动指定水印位置 x,y,w,h")
    parser.add_argument("--crf", type=int, default=None, help="libx264 CRF (0-51，默认 18)")
    parser.add_argument("--smooth-window", type=int, default=None, help="时序平滑窗口 (1-7，默认 3)")
    parser.add_argument("--keep-audio", action="store_true", default=None, help="保留原音轨")
    parser.add_argument("--no-keep-audio", action="store_true", help="不保留原音轨")
    parser.add_argument("--cache-dir", default=None, help="临时文件目录（默认 ./cache）")
    parser.add_argument("--no-auto-clean", action="store_true", help="处理完成后不清理 cache")
    parser.add_argument("--log-level", default=None, help="debug/info/warn/error")
    parser.add_argument("--config", "-c", default=None, help="YAML 配置文件路径")
    parser.add_argument("--yes", action="store_true", help="跳过免责声明确认")
    parser.add_argument("--metrics", action="store_true", help="输出 Prometheus 格式指标")
    return parser


def _apply_cli_overrides(config: Config, args: argparse.Namespace) -> None:
    """CLI 参数覆盖配置。"""
    if args.detector:
        config.detector.primary = args.detector
    if args.detector_fallback:
        config.detector.fallback = list(args.detector_fallback)
    if args.inpainter:
        config.inpainter.primary = args.inpainter
    if args.inpainter_fallback:
        config.inpainter.fallback = list(args.inpainter_fallback)
    if args.device:
        config.inpainter.device = args.device
    if args.crf is not None:
        config.output.crf = args.crf
    if args.smooth_window is not None:
        config.temporal.window = args.smooth_window
    if args.keep_audio:
        config.output.keep_audio = True
    if args.no_keep_audio:
        config.output.keep_audio = False
    if args.cache_dir:
        config.cache.dir = args.cache_dir
    if args.no_auto_clean:
        config.cache.auto_clean = False
    if args.log_level:
        config.logging.level = args.log_level


def _confirm_disclaimer() -> bool:
    print(DISCLAIMER, file=sys.stderr)
    try:
        answer = input("请选择 [Y/N]: ").strip().lower()
    except EOFError:
        answer = "n"
    return answer in ("y", "yes")


def _print_metrics(result) -> None:
    print("# HELP remove_wm_duration_seconds Total processing duration")
    print("# TYPE remove_wm_duration_seconds histogram")
    print(f'remove_wm_duration_seconds_bucket{{le="10"}} {1 if result.elapsed_sec <= 10 else 0}')
    print(f'remove_wm_duration_seconds_bucket{{le="30"}} {1 if result.elapsed_sec <= 30 else 0}')
    print(f'remove_wm_duration_seconds_bucket{{le="60"}} {1 if result.elapsed_sec <= 60 else 0}')
    print('remove_wm_duration_seconds_bucket{le="+Inf"} 1')
    print("# HELP remove_wm_frames_processed_total Total frames processed")
    print("# TYPE remove_wm_frames_processed_total counter")
    print(f'remove_wm_frames_processed_total{{model="{result.stages.get("inpaint", {}).get("model_used", "cv2_telea")}"}} '
          f'{result.stages.get("inpaint", {}).get("processed", 0)}')
    print("# HELP remove_wm_detect_method Counter of detection method")
    print("# TYPE remove_wm_detect_method counter")
    print(f'remove_wm_detect_method{{method="{result.method}"}} 1')


def run(args: argparse.Namespace) -> int:
    # 加载配置
    config = Config()
    if args.config:
        config = Config.from_yaml(args.config)
    _apply_cli_overrides(config, args)

    set_level(config.logging.level)
    if config.logging.file:
        add_file_handler(config.logging.file)

    # FFmpeg 检查
    try:
        check_ffmpeg()
    except WatermarkRemoverError as e:
        print(f"[ERROR] {e.message}", file=sys.stderr)
        return e.exit_code

    # 免责声明
    if not args.yes and not _confirm_disclaimer():
        print("已退出。", file=sys.stderr)
        return 0

    bbox = _parse_bbox(args.bbox) if args.bbox else None
    remover = Remover(config)

    try:
        if args.batch:
            if not args.input_dir or not args.output_dir:
                raise InvalidArgsError("批量模式需要 --input-dir 和 --output-dir")
            batch = remover.batch(
                input_dir=args.input_dir,
                output_dir=args.output_dir,
                workers=args.workers,
                skip_existing=args.skip_existing,
                retry_failed=args.retry_failed,
                failed_log=args.failed_log,
                extensions=args.extensions,
            )
            print(f"\n批量处理完成: 成功 {batch.success_count}/{len(batch.results)}")
            for r in batch.failed:
                print(f"  ✗ {r.input_file}: {r.error}")
            if batch.failed:
                print(f"失败详情见 {args.failed_log}")
            return 0 if not batch.failed else 3

        if not args.input or not args.output:
            raise InvalidArgsError("需要 --input 和 --output（或使用 --batch 批量模式）")

        result = remover.process(args.input, args.output, bbox=bbox)
        if result.success:
            print(
                f"✓ {args.input} → {args.output} "
                f"(size={result.size_bytes / 1024 / 1024:.1f}MB, "
                f"dur={result.duration_sec:.2f}s, elapsed={result.elapsed_sec:.1f}s, "
                f"method={result.method})"
            )
        else:
            print(f"✗ 处理失败: {result.error} (exit={result.exit_code})", file=sys.stderr)
        if args.metrics:
            _print_metrics(result)
        return result.exit_code

    except InvalidArgsError as e:
        print(f"[ERROR] {e.message}", file=sys.stderr)
        return e.exit_code
    except WatermarkRemoverError as e:
        print(f"[ERROR] {e.message} (exit={e.exit_code})", file=sys.stderr)
        return e.exit_code
    except Exception as e:  # noqa: BLE001
        log.exception("未捕获异常")
        print(f"[ERROR] 未捕获异常: {e}", file=sys.stderr)
        return EXIT_UNKNOWN


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n[ERROR] 已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
