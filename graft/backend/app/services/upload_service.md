# backend/app/services/upload_service.py · [[resumable-upload-service]]

- _get_redis · function · L20-L24 — Lazily initializes and returns a shared Redis client for upload session storage.
- _deserialize_session · function · L27-L40 — Converts a Redis hash of strings back into the typed session dict, parsing ints, JSON metadata, and booleans.
- create_upload_session · function · L43-L70 — Creates a new upload session with a unique ID, temp directory, and initial offset, persisting it to Redis with a TTL.
- get_upload_session · function · L73-L79 — Fetches and deserializes an upload session from Redis by ID, returning None if it doesn't exist.
- _rebuild_hash · function · L82-L94 — Returns a fresh md5 object since md5 internal state cannot be restored from a hex digest.
- write_chunk · function · L97-L152 — Writes an incoming chunk to disk, verifies offset ordering, recomputes the running hash from all chunks, and marks the session complete when the file size is reached.
- finalize_upload · function · L155-L191 — Concatenates all stored chunks in offset order into a single output file and cleans up the temp directory.
- get_upload_progress · function · L194-L211 — Returns upload progress as a percentage of bytes received relative to the declared file size.
- delete_upload_session · function · L214-L231 — Removes an upload session's temp files and its Redis record.
- get_temp_file_path · function · L234-L236 — Returns the canonical temp file path for an upload session.
- validate_file_name · function · L239-L248 — Sanitizes an uploaded file name to its basename and rejects empty names or unsupported video extensions.
