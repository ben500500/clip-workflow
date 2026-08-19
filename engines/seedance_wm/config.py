"""配置模块（API 文档 §2 YAML 配置格式）。

支持:
  - 默认配置（匹配推荐档）
  - 从 YAML 文件加载（--config）
  - 从 CLI 参数覆盖
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ROI = {"h_ratio": 0.12, "w_ratio": 0.08}


@dataclass
class DetectorConfig:
    primary: str = "matchTemplate"
    fallback: list[str] = field(default_factory=lambda: ["yolov8_seg", "paddleocr"])
    roi: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ROI))
    confidence_threshold: float = 0.6
    max_sample_frames: int = 60


@dataclass
class InpainterConfig:
    primary: str = "lama"
    fallback: list[str] = field(default_factory=lambda: ["cv2_telea", "cv2_ns"])
    device: str = "auto"
    fp16: bool = True
    batch_size: int = 1
    expand_px: int = 5
    roi_only: bool = False  # 方向二 mask 加速：仅对 mask 覆盖 ROI 做局部修复


@dataclass
class TemporalConfig:
    enabled: bool = True
    window: int = 3
    weights: str = "gaussian"


@dataclass
class OutputConfig:
    codec: str = "libx264"
    crf: int = 18
    pix_fmt: str = "yuv420p"
    movflags: str = "+faststart"
    keep_audio: bool = True


@dataclass
class LoggingConfig:
    level: str = "info"
    format: str = "[{ts}] [{level}] [{module}] {msg}"
    file: str | None = "remove-wm.log"


@dataclass
class CacheConfig:
    dir: str = "./cache"
    auto_clean: bool = True
    max_size_gb: float = 10.0


@dataclass
class Config:
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    inpainter: InpainterConfig = field(default_factory=InpainterConfig)
    temporal: TemporalConfig = field(default_factory=TemporalConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Config:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> Config:
        cfg = cls()
        det = raw.get("detector") or {}
        cfg.detector.primary = det.get("primary", cfg.detector.primary)
        cfg.detector.fallback = det.get("fallback", cfg.detector.fallback)
        if "roi" in det:
            cfg.detector.roi.update(det["roi"])
        cfg.detector.confidence_threshold = det.get(
            "confidence_threshold", cfg.detector.confidence_threshold
        )
        cfg.detector.max_sample_frames = det.get(
            "max_sample_frames", cfg.detector.max_sample_frames
        )

        inp = raw.get("inpainter") or {}
        cfg.inpainter.primary = inp.get("primary", cfg.inpainter.primary)
        cfg.inpainter.fallback = inp.get("fallback", cfg.inpainter.fallback)
        cfg.inpainter.device = inp.get("device", cfg.inpainter.device)
        cfg.inpainter.fp16 = inp.get("fp16", cfg.inpainter.fp16)
        cfg.inpainter.batch_size = inp.get("batch_size", cfg.inpainter.batch_size)

        tmp = raw.get("temporal") or {}
        cfg.temporal.enabled = tmp.get("enabled", cfg.temporal.enabled)
        cfg.temporal.window = tmp.get("window", cfg.temporal.window)
        cfg.temporal.weights = tmp.get("weights", cfg.temporal.weights)

        out = raw.get("output") or {}
        cfg.output.codec = out.get("codec", cfg.output.codec)
        cfg.output.crf = out.get("crf", cfg.output.crf)
        cfg.output.pix_fmt = out.get("pix_fmt", cfg.output.pix_fmt)
        cfg.output.movflags = out.get("movflags", cfg.output.movflags)
        cfg.output.keep_audio = out.get("keep_audio", cfg.output.keep_audio)

        lg = raw.get("logging") or {}
        cfg.logging.level = lg.get("level", cfg.logging.level)
        cfg.logging.file = lg.get("file", cfg.logging.file)

        cache = raw.get("cache") or {}
        cfg.cache.dir = cache.get("dir", cfg.cache.dir)
        cfg.cache.auto_clean = cache.get("auto_clean", cfg.cache.auto_clean)
        cfg.cache.max_size_gb = cache.get("max_size_gb", cfg.cache.max_size_gb)
        return cfg

    def to_yaml(self) -> str:
        raw = {
            "detector": {
                "primary": self.detector.primary,
                "fallback": self.detector.fallback,
                "roi": self.detector.roi,
                "confidence_threshold": self.detector.confidence_threshold,
                "max_sample_frames": self.detector.max_sample_frames,
            },
            "inpainter": {
                "primary": self.inpainter.primary,
                "fallback": self.inpainter.fallback,
                "device": self.inpainter.device,
                "fp16": self.inpainter.fp16,
                "batch_size": self.inpainter.batch_size,
                "expand_px": self.inpainter.expand_px,
            },
            "temporal": {
                "enabled": self.temporal.enabled,
                "window": self.temporal.window,
                "weights": self.temporal.weights,
            },
            "output": {
                "codec": self.output.codec,
                "crf": self.output.crf,
                "pix_fmt": self.output.pix_fmt,
                "movflags": self.output.movflags,
                "keep_audio": self.output.keep_audio,
            },
            "logging": {"level": self.logging.level, "file": self.logging.file},
            "cache": {
                "dir": self.cache.dir,
                "auto_clean": self.cache.auto_clean,
                "max_size_gb": self.cache.max_size_gb,
            },
        }
        return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
