# backend/app/services/minio_service.py · [[object-storage-service-minio]]

- _parse_endpoint · function · L22-L30 — def _parse_endpoint(endpoint: str) -> tuple[str, bool]
- get_minio_client · function · L33-L46 — def get_minio_client() -> Minio
- get_external_minio_client · function · L49-L72 — def get_external_minio_client() -> Optional[Minio]
- _generate_presigned_url · function · L75-L107 — def _generate_presigned_url( client: Minio, bucket: str, object_key: str, expires_seconds: int, method: str = "GET", response_headers: Optional[dict] = None, ) -> Optional[str]
- upload_file · function · L110-L141 — async def upload_file( bucket: str, object_key: str, data: bytes, content_type: str = "application/octet-stream", ) -> bool
- upload_file_from_path · function · L144-L173 — async def upload_file_from_path( bucket: str, object_key: str, file_path: str, content_type: str = "application/octet-stream", ) -> bool
- _download_sync · function · L176-L185 — def _download_sync(bucket: str, object_key: str) -> bytes
- download_file · function · L188-L199 — async def download_file( bucket: str, object_key: str, ) -> Optional[bytes]
- get_presigned_url · function · L202-L235 — async def get_presigned_url( bucket: str, object_key: str, expires_seconds: int = 3600, as_attachment: bool = False, filename: Optional[str] = None, ) -> Optional[str]
- get_presigned_upload_url · function · L238-L252 — async def get_presigned_upload_url( bucket: str, object_key: str, expires_seconds: int = 7200, ) -> Optional[str]
- delete_file · function · L255-L265 — async def delete_file(bucket: str, object_key: str) -> bool
- _list_objects_sync · function · L268-L280 — def _list_objects_sync(bucket: str, prefix: str) -> list[dict]
- list_files · function · L283-L291 — async def list_files(bucket: str, prefix: str = "") -> list[dict]
- get_file_info · function · L294-L308 — async def get_file_info(bucket: str, object_key: str) -> Optional[dict]
- ensure_bucket · function · L311-L323 — async def ensure_bucket(bucket: str) -> bool
- download_to_file · function · L326-L349 — async def download_to_file( bucket: str, object_key: str, local_path: str, ) -> bool
