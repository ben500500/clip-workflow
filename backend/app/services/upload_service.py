import hashlib
import json
import logging
import os
import uuid
from typing import Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Redis-based store for upload sessions (replaces in-memory dict)
_redis_client = None

SESSION_TTL = 86400  # 24 hours


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _deserialize_session(raw: dict) -> dict:
    """Convert a Redis hash (all strings) back to the session dict format."""
    return {
        "id": raw["id"],
        "file_name": raw["file_name"],
        "file_size": int(raw["file_size"]),
        "chunk_size": int(raw["chunk_size"]),
        "offset": int(raw["offset"]),
        "metadata": json.loads(raw.get("metadata", "{}")),
        "temp_dir": raw["temp_dir"],
        "completed": raw["completed"] == "true",
        "file_hash": hashlib.md5(),
        "_hash_digest": raw.get("hash_digest", ""),
    }


def create_upload_session(
    file_name: str,
    file_size: int,
    chunk_size: int = 5 * 1024 * 1024,
    metadata: Optional[dict] = None,
) -> dict:
    """Create a new upload session (tus-like protocol)."""
    r = _get_redis()
    upload_id = str(uuid.uuid4())
    temp_dir = os.path.join(settings.UPLOAD_TEMP_DIR, upload_id)
    os.makedirs(temp_dir, exist_ok=True)

    session = {
        "id": upload_id,
        "file_name": file_name,
        "file_size": str(file_size),
        "chunk_size": str(chunk_size),
        "offset": "0",
        "metadata": json.dumps(metadata or {}),
        "temp_dir": temp_dir,
        "completed": "false",
        "hash_digest": "",
    }
    r.hset(f"upload:{upload_id}", mapping=session)
    r.expire(f"upload:{upload_id}", SESSION_TTL)

    logger.info(f"Created upload session: {upload_id} for {file_name} ({file_size} bytes)")
    return _deserialize_session(session)


def get_upload_session(upload_id: str) -> Optional[dict]:
    """Get an upload session by ID."""
    r = _get_redis()
    raw = r.hgetall(f"upload:{upload_id}")
    if not raw:
        return None
    return _deserialize_session(raw)


def _rebuild_hash(digest: str) -> hashlib.md5:
    """Rebuild an md5 object from a stored hex digest.

    Since md5 does not allow restoring internal state from a hex digest,
    we store the digest and use it to verify/continue incrementally by
    tracking the digest separately. For simplicity we return a fresh md5
    object and store the prior digest alongside it.
    """
    h = hashlib.md5()
    # We cannot restore md5 state from a hex digest, so callers must
    # recompute from scratch if needed. We store the last known digest
    # and use it for final verification.
    return h


def write_chunk(upload_id: str, data: bytes, offset: int) -> Optional[int]:
    """Write a chunk of data to the upload session.

    Returns the new offset, or None if the session is invalid.
    """
    r = _get_redis()
    raw = r.hgetall(f"upload:{upload_id}")
    if not raw:
        logger.error(f"Upload session not found: {upload_id}")
        return None

    session = _deserialize_session(raw)

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

    # Update hash: rebuild from stored digest by re-hashing all chunks
    # Since md5 state cannot be restored from hex digest, we recompute
    # the hash from all chunk files on disk.
    file_hash = hashlib.md5()
    chunk_files = sorted(
        [f for f in os.listdir(session["temp_dir"]) if f.startswith("chunk_")],
        key=lambda x: int(x.split("_")[-1]),
    )
    for cf in chunk_files:
        with open(os.path.join(session["temp_dir"], cf), "rb") as f:
            file_hash.update(f.read())
    hash_digest = file_hash.hexdigest()

    new_offset = session["offset"] + len(data)

    # Check if upload is complete
    completed = "false"
    if new_offset >= session["file_size"]:
        completed = "true"
        logger.info(f"Upload session {upload_id} completed")

    r.hset(f"upload:{upload_id}", mapping={
        "offset": str(new_offset),
        "completed": completed,
        "hash_digest": hash_digest,
    })

    return new_offset


def finalize_upload(upload_id: str, output_path: str) -> Optional[str]:
    """Finalize an upload by concatenating all chunks into a single file.

    Returns the output path, or None on failure.
    """
    r = _get_redis()
    raw = r.hgetall(f"upload:{upload_id}")
    if not raw:
        return None

    session = _deserialize_session(raw)

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
    r = _get_redis()
    raw = r.hgetall(f"upload:{upload_id}")
    if not raw:
        return None

    session = _deserialize_session(raw)
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
    r = _get_redis()
    raw = r.hgetall(f"upload:{upload_id}")
    if not raw:
        return False

    temp_dir = raw.get("temp_dir", "")
    if temp_dir and os.path.isdir(temp_dir):
        for f in os.listdir(temp_dir):
            os.unlink(os.path.join(temp_dir, f))
        try:
            os.rmdir(temp_dir)
        except OSError:
            pass

    r.delete(f"upload:{upload_id}")
    return True


def get_temp_file_path(upload_id: str) -> str:
    """Get the temporary file path for an upload session."""
    return os.path.join(settings.UPLOAD_TEMP_DIR, upload_id, "uploaded_file")


def validate_file_name(file_name: str) -> str:
    """Sanitize an uploaded file name and validate its extension."""
    base = os.path.basename(file_name or "").strip()
    if not base:
        raise ValueError("empty file name")
    allowed = {e.strip().lower() for e in settings.ALLOWED_VIDEO_EXTENSIONS.split(",")}
    ext = os.path.splitext(base)[1].lower()
    if ext not in allowed:
        raise ValueError(f"unsupported file type: {ext}")
    return base
