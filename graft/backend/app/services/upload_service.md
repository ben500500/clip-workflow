# backend/app/services/upload_service.py · [[resumable-upload-service]]

- _get_redis · function · L20-L24 — def _get_redis() -> redis.Redis
- _deserialize_session · function · L27-L40 — def _deserialize_session(raw: dict) -> dict
- create_upload_session · function · L43-L70 — def create_upload_session( file_name: str, file_size: int, chunk_size: int = 5 * 1024 * 1024, metadata: Optional[dict] = None, ) -> dict
- get_upload_session · function · L73-L79 — def get_upload_session(upload_id: str) -> Optional[dict]
- _rebuild_hash · function · L82-L94 — def _rebuild_hash(digest: str) -> hashlib.md5
- write_chunk · function · L97-L152 — def write_chunk(upload_id: str, data: bytes, offset: int) -> Optional[int]
- finalize_upload · function · L155-L191 — def finalize_upload(upload_id: str, output_path: str) -> Optional[str]
- get_upload_progress · function · L194-L211 — def get_upload_progress(upload_id: str) -> Optional[dict]
- delete_upload_session · function · L214-L231 — def delete_upload_session(upload_id: str) -> bool
- get_temp_file_path · function · L234-L236 — def get_temp_file_path(upload_id: str) -> str
- validate_file_name · function · L239-L248 — def validate_file_name(file_name: str) -> str
