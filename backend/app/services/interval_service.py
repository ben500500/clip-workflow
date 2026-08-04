import asyncio
import json
import logging
import os
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def detect_intervals(
    video_path: str,
    mode: str,
    config: Optional[dict] = None,
    engine_path: str = "engines/detect_intervals.py",
) -> list[dict[str, Any]]:
    """Run generic interval detection on a video file.

    Args:
        video_path: Path to the input video file.
        mode: Detection mode ('credits', 'static', 'watermark', 'custom').
        config: Detection configuration parameters.
        engine_path: Path to the detection engine script.

    Returns:
        A list of detected intervals as dictionaries.

    Raises:
        FileNotFoundError: If the video file or engine script is not found.
        RuntimeError: If the detection subprocess fails.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if not os.path.isfile(engine_path):
        logger.warning(f"Engine script not found at {engine_path}, using mock detection")
        return _mock_detect(mode, config)

    # Write config to a temp file
    config_path = None
    if config:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config, f)
            config_path = f.name

    try:
        cmd = [
            "python",
            engine_path,
            "--input",
            video_path,
            "--mode",
            mode,
        ]
        if config_path:
            cmd.extend(["--config", config_path])

        logger.info(f"Running interval detection: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            logger.error(f"Interval detection failed (exit={proc.returncode}): {error_msg}")
            raise RuntimeError(f"Detection failed: {error_msg}")

        output_path = stdout.decode().strip()
        if not output_path or not os.path.isfile(output_path):
            raise RuntimeError(f"Detection script did not produce a valid output path")

        with open(output_path, "r") as f:
            intervals = json.load(f)

        if isinstance(intervals, dict) and "intervals" in intervals:
            return intervals["intervals"]
        if isinstance(intervals, list):
            return intervals
        return []

    finally:
        if config_path and os.path.isfile(config_path):
            os.unlink(config_path)


def _mock_detect(mode: str, config: Optional[dict] = None) -> list[dict[str, Any]]:
    """Generate mock detection results for development/testing."""
    mock_intervals = [
        {
            "interval_type": mode,
            "start_time": 300.0,
            "end_time": 315.0,
            "confidence": 0.95,
            "label": f"Detected {mode} segment",
            "enabled": True,
            "source": "auto",
        },
        {
            "interval_type": mode,
            "start_time": 600.0,
            "end_time": 620.0,
            "confidence": 0.88,
            "label": f"Detected {mode} segment 2",
            "enabled": True,
            "source": "auto",
        },
    ]
    return mock_intervals