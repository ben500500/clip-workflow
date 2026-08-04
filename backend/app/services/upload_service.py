import hashlib
import json
import logging
import os
import uuid
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory store for upload sessions (in production, use Redis)
_upload_sessions: dict[str, dict] = {}


def create_upload_session(
    file_name: str,
    file_size: int,
    chunk_size: int = 5 * 1024 * 1024,
    metadata: Optional[dict] = None,
) -> dict:
    """Create a new upload session (tus-like protocol)."""
    upload_id = str(uuid.uuid4())
    temp_dir = os.path.join(settings.UPLOAD_TEMP_DIR, upload_id)
    os.makedirs(temp_dir, exist_ok=True)

    session = {
        "id": upload_id,
        "file_name": file_name,
        "file_size": file_size,
        "chunk_size": chunk_size,
        "offset": 0,
        "metadata": metadata or {},
        "temp_dir": temp_dir,
        "completed": False,
        "file_hash": hashlib.md5(),
    }
    _upload_sessions[upload_id] = session
    logger.info(f"Created upload session: {upload_id} for {file_name} ({file_size} bytes)")
    return session


def get_upload_session(upload_id: str) -> Optional[dict]:
    """Get an upload session by ID."""
    return _upload_sessions.get(upload_id)


def write_chunk(upload_id: str, data: bytes, offset: int) -> Optional[int]:
    """Write a chunk of data to the upload session.

    Returns the new offset, or None if the session is invalid.
    """
    session = _upload_sessions.get(upload_id)
    if not session:
        logger.error(f"Upload session not found: {upload_id}")
        return None

    if session["completed"]:
        logger.warning(f"Upload session {upload_id} already completed")
        return session["offset"]

    if offset != session["offset"]:
        logger.error(
            f"Offset mismatch for {upload_id}: expected {session['offset']}, got {offset}"
        )
        return None

    # Write chunk to temp file
    chunk_path = os.path.join(session["temp_dir"], f"chunk_{offset}")
    with open(chunk_path, "wb") as f:
        f.write(data)

    # Update hash and offset
    session["file_hash"].update(data)
    session["offset"] += len(data)

    # Check if upload is complete
    if session["offset"] >= session["file_size"]:
        session["completed"] = True
        logger.info(f"Upload session {upload_id} completed")

    return session["offset"]


def finalize_upload(upload_id: str, output_path: str) -> Optional[str]:
    """Finalize an upload by concatenating all chunks into a single file.

    Returns the output path, or None on failure.
    """
    session = _upload_sessions.get(upload_id)
    if not session:
        return None

    if not session["completed"]:
        logger.warning(f"Upload session {upload_id} is not yet complete")
        return None

    temp_dir = session["temp_dir"]
    chunk_files = sorted(
        [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.startswith("chunk_")],
        key=lambda x: int(x.split("_")[-1]),
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as outfile:
        for chunk_file in chunk_files:
            with open(chunk_file, "rb") as infile:
                outfile.write(infile.read())
            os.unlink(chunk_file)

    # Clean up temp directory
    try:
        os.rmdir(temp_dir)
    except OSError:
        pass

    logger.info(f"Finalized upload {upload_id} -> {output_path}")
    return output_path


def get_upload_progress(upload_id: str) -> Optional[dict]:
    """Get the current progress of an upload session."""
    session = _upload_sessions.get(upload_id)
    if not session:
        return None
    return {
        "id": session["id"],
        "file_name": session["file_name"],
        "file_size": session["file_size"],
        "offset": session["offset"],
        "completed": session["completed"],
        "progress_pct": round(
            (session["offset"] / session["file_size"]) * 100, 1
        ) if session["file_size"] > 0 else 0,
    }


def delete_upload_session(upload_id: str) -> bool:
    """Delete an upload session and its temporary files."""
    session = _upload_sessions.pop(upload_id, None)
    if not session:
        return False
    temp_dir = session["temp_dir"]
    if os.path.isdir(temp_dir):
        for f in os.listdir(temp_dir):
            os.unlink(os.path.join(temp_dir, f))
        os.rmdir(temp_dir)
    return True


def get_temp_file_path(upload_id: str) -> str:
    """Get the temporary file path for an upload session."""
    return os.path.join(settings.UPLOAD_TEMP_DIR, upload_id, "uploaded_file")