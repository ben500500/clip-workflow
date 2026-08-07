"""日志模块。

规范（TRD §5.3 / API §2）:
  所有日志输出到 stderr，格式: [HH:MM:SS.mmm] [LEVEL] [module] message
  可选写入文件 ./remove-wm.log
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATE_FORMAT = "%H:%M:%S"


class _UtcFormatter(logging.Formatter):
    """带毫秒的时间戳，符合 [HH:MM:SS.mmm] 规范。"""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        return dt.strftime("%H:%M:%S") + f".{int(record.msecs):03d}"


def get_logger(name: str = "seedance_wm") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        _configure(logger)
    return logger


def _configure(logger: logging.Logger) -> None:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_UtcFormatter(_FORMAT, _DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False


def set_level(level: str) -> None:
    logger = get_logger()
    logger.setLevel(_LEVELS.get(level.lower(), logging.INFO))


def add_file_handler(log_file: str | Path) -> None:
    log_path = Path(log_file)
    if log_path.parent:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(_UtcFormatter(_FORMAT, _DATE_FORMAT))
    get_logger().addHandler(handler)
