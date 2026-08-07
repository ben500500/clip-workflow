"""错误码与异常定义（API 文档 §5）。

退出码:
  0  OK               成功
  1  INVALID_ARGS     参数错误
  2  VIDEO_READ_FAIL  视频读取失败
  3  DETECT_FAIL      水印检测全部失败
  4  FFMPEG_MISSING   FFmpeg 未安装
  5  INPAINT_FAIL     所有修复器失败
  6  MUX_FAIL         视频合成失败
  7  OUT_OF_DISK      磁盘空间不足
  8  GPU_OOM          显存不足（已自动切 CPU，WARN 级）
  9  LICENSE_FAIL     许可证校验失败（ProPainter 商用）
  10 UNKNOWN          未捕获异常
"""

EXIT_OK = 0
EXIT_INVALID_ARGS = 1
EXIT_VIDEO_READ_FAIL = 2
EXIT_DETECT_FAIL = 3
EXIT_FFMPEG_MISSING = 4
EXIT_INPAINT_FAIL = 5
EXIT_MUX_FAIL = 6
EXIT_OUT_OF_DISK = 7
EXIT_GPU_OOM = 8
EXIT_LICENSE_FAIL = 9
EXIT_UNKNOWN = 10


class WatermarkRemoverError(Exception):
    """所有业务异常的基类。"""

    exit_code = EXIT_UNKNOWN

    def __init__(self, message: str, *args):
        super().__init__(message, *args)
        self.message = message


class InvalidArgsError(WatermarkRemoverError):
    exit_code = EXIT_INVALID_ARGS


class VideoReadError(WatermarkRemoverError):
    exit_code = EXIT_VIDEO_READ_FAIL


class DetectFailError(WatermarkRemoverError):
    exit_code = EXIT_DETECT_FAIL


class FfmpegMissingError(WatermarkRemoverError):
    exit_code = EXIT_FFMPEG_MISSING


class InpaintError(WatermarkRemoverError):
    exit_code = EXIT_INPAINT_FAIL


class MuxError(WatermarkRemoverError):
    exit_code = EXIT_MUX_FAIL


class OutOfDiskError(WatermarkRemoverError):
    exit_code = EXIT_OUT_OF_DISK


class GpuOomError(WatermarkRemoverError):
    """GPU OOM，会自动降级到 CPU，不视为致命错误。"""

    exit_code = EXIT_GPU_OOM


class LicenseError(WatermarkRemoverError):
    exit_code = EXIT_LICENSE_FAIL
