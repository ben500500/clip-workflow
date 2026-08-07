"""
seedance_wm — Seedance AI 视频去水印（5 阶段本地流水线）

架构:
  Agent 编排层(可选) -> Tool 注册层(5 个原子工具) -> 模型层(可热插拔) -> I/O 层(FFmpeg)

阶段:
  1. extract_frames        抽帧 + 抽音轨 (FFmpeg)
  2. detect_watermark      水印检测 (matchTemplate -> YOLOv8-seg -> PaddleOCR)
  3. generate_mask_sequence bbox -> 帧级 mask 序列
  4. inpaint_frames        逐帧修复 (LaMa -> cv2_telea/cv2_ns) + 时序平滑
  5. mux_video             FFmpeg 合成 (libx264 + 原音轨)
"""

from seedance_wm.config import Config
from seedance_wm.remover import BatchResult, Remover
from seedance_wm.version import __version__

__all__ = ["Config", "Remover", "BatchResult", "__version__"]
