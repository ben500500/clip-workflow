# backend/app/services/minio_service.py · [[object-storage-service-minio]]

- _parse_endpoint · function · L22-L30 — Normalizes a MinIO endpoint string into (host:port, secure) by extracting scheme and netloc from URLs.
- get_minio_client · function · L33-L46 — Returns a lazily-created, cached MinIO client configured from settings for internal container access.
- get_external_minio_client · function · L49-L72 — Returns a cached MinIO client using the browser-reachable external endpoint so presigned URLs resolve for clients, or None if not configured.
- _generate_presigned_url · function · L75-L107 — Synchronously generates a presigned GET or PUT URL with optional response-header overrides, returning None on any error.
- upload_file · function · L110-L141 — Uploads in-memory bytes to MinIO asynchronously, creating the bucket first if it does not exist.
- upload_file_from_path · function · L144-L173 — Uploads a local file to MinIO asynchronously, creating the bucket first if needed.
- _download_sync · function · L176-L185 — Synchronous helper that fetches an object from MinIO and returns its full byte content, ensuring the connection is released.
- download_file · function · L188-L199 — Downloads a MinIO object as bytes asynchronously, returning None on S3 errors.
- get_presigned_url · function · L202-L235 — Generates a browser-accessible presigned GET URL, preferring the external endpoint and optionally forcing attachment download via response headers.
- get_presigned_upload_url · function · L238-L252 — Generates a presigned PUT URL using the internal endpoint for container-side Worker uploads.
- delete_file · function · L255-L265 — Deletes an object from MinIO asynchronously, returning success status.
- _list_objects_sync · function · L268-L280 — Synchronous helper that lists objects under a prefix and collects their key, size, etag, and last-modified metadata.
- list_files · function · L283-L291 — Lists files in a bucket under a prefix asynchronously, returning an empty list on S3 errors.
- get_file_info · function · L294-L308 — Fetches metadata for a single object asynchronously, returning None if the object does not exist.
- ensure_bucket · function · L311-L323 — Checks whether a bucket exists and creates it if missing, returning success status.
- download_to_file · function · L326-L349 — Downloads a MinIO object to a local file, creating parent directories with explicit mode to avoid executable-only dirs.
