import asyncio
import json
import logging
import os
import tempfile
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


async def detect_intervals(
    video_path: str,
    mode: str,
    config: Optional[dict] = None,
    engine_path: Optional[str] = None,
    timeout: float = 600,
) -> list[dict[str, Any]]:
    """Run generic interval detection on a video file.

    Args:
        video_path: Path to the input video file.
        mode: Detection mode ('credits', 'static', 'watermark', 'custom').
        config: Detection configuration parameters.
        engine_path: Path to the detection engine script.
        timeout: Maximum seconds to wait for the engine.

    Returns:
        A list of detected intervals as dictionaries.

    Raises:
        FileNotFoundError: If the video file or engine script is not found.
        RuntimeError: If the detection subprocess fails or times out.
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    engine_path = engine_path or os.path.join(settings.ENGINES_DIR, "detect_intervals.py")
    if not os.path.isfile(engine_path):
        raise FileNotFoundError(
            f"Detection engine not found: {engine_path}. "
            "请确认 engines/ 目录已挂载或包含在镜像中。"
        )

    config_path = None
    if config:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config, f)
            config_path = f.name

    try:
        cmd = ["python", engine_path, "--input", video_path, "--mode", mode]
        if config_path:
            cmd.extend(["--config", config_path])

        logger.info("Running interval detection: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.terminate()  # SIGTERM
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()  # SIGKILL as fallback
            except ProcessLookupError:
                pass
            raise RuntimeError(f"Interval detection timed out after {timeout}s")

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            logger.error("Interval detection failed (exit=%s): %s", proc.returncode, error_msg)
            raise RuntimeError(f"Detection failed: {error_msg}")

        output_path = stdout.decode().strip()
        if not output_path or not os.path.isfile(output_path):
            raise RuntimeError("Detection script did not produce a valid output path")

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
