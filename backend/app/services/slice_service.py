import asyncio
import logging
import os
import tempfile
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


async def run_slice_scrub(
    source_path: str,
    cutlist_path: str,
    intervals_path: str,
    output_dir: str,
    engine_path: str = "engines/slice_scrub.sh",
) -> tuple[int, str, str]:
    """Run the scrub-mode slice script (with interval removal).

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    if not os.path.isfile(engine_path):
        logger.warning(f"Engine script not found: {engine_path}")
        return _mock_slice_scrub(source_path, cutlist_path, intervals_path, output_dir)

    cmd = ["bash", engine_path, source_path, cutlist_path, intervals_path, output_dir]
    logger.info(f"Running slice scrub: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def run_slice_fast(
    source_path: str,
    cutlist_path: str,
    output_dir: str,
    mode: str = "fast",
    engine_path: str = "engines/slice.sh",
) -> tuple[int, str, str]:
    """Run the fast/dedupe mode slice script.

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    if not os.path.isfile(engine_path):
        logger.warning(f"Engine script not found: {engine_path}")
        return _mock_slice_fast(source_path, cutlist_path, output_dir, mode)

    cmd = ["bash", engine_path, source_path, cutlist_path, mode]
    logger.info(f"Running slice: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def run_preview(
    source_path: str,
    output_dir: str,
    engine_path: str = "engines/preview.sh",
) -> tuple[int, str, str]:
    """Run the preview frame extraction script.

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    if not os.path.isfile(engine_path):
        logger.warning(f"Preview script not found: {engine_path}")
        return 0, "", "Preview script not available"

    cmd = ["bash", engine_path, source_path, output_dir]
    logger.info(f"Running preview: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


def _mock_slice_scrub(
    source_path: str,
    cutlist_path: str,
    intervals_path: str,
    output_dir: str,
) -> tuple[int, str, str]:
    """Mock scrub slicing for development."""
    os.makedirs(output_dir, exist_ok=True)
    # Create a placeholder output file
    placeholder = os.path.join(output_dir, "clip_01.mp4")
    if not os.path.isfile(placeholder):
        with open(placeholder, "w") as f:
            f.write("placeholder")
    return 0, f"Output: {output_dir}", "Mock scrub slice completed"


def _mock_slice_fast(
    source_path: str, cutlist_path: str, output_dir: str, mode: str
) -> tuple[int, str, str]:
    """Mock fast slicing for development."""
    os.makedirs(output_dir, exist_ok=True)
    placeholder = os.path.join(output_dir, "clip_01.mp4")
    if not os.path.isfile(placeholder):
        with open(placeholder, "w") as f:
            f.write("placeholder")
    return 0, f"Output: {output_dir}", f"Mock {mode} slice completed"