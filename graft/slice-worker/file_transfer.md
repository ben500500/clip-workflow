# slice-worker/file_transfer.go

- FileTransfer · struct · L15-L18 — Holds the HTTP client and optional progress callback used for all file download/upload operations.
- NewFileTransfer · function · L21-L27 — Constructs a FileTransfer with an HTTP client configured with a long 30-minute timeout to accommodate large file transfers.
- SetProgressCallback · method · L30-L32 — Registers the callback invoked with download/upload progress updates.
- DownloadFile · method · L35-L101 — Downloads a file from a URL to a destination path, streaming in 32KB chunks while honoring context cancellation and reporting progress via the callback.
- UploadFile · method · L104-L142 — Uploads a local file to a presigned PUT URL, setting Content-Length and video/mp4 content type, and returns an error on non-2xx responses.
- UploadFileWithProgress · method · L145-L189 — Uploads a local file to a presigned PUT URL while wrapping the file in a progressReader so the callback reports upload progress.
- uploadURLResponse · struct · L192-L195 — Data holder for the backend's upload URL response containing the presigned URL and object file key.
- GetUploadURL · method · L201-L235 — Requests a backend-generated presigned PUT URL bound to a specific object key per output file, fixing MinIO signature invalidation from concatenating filenames into a single URL.
- progressReader · struct · L238-L245 — Reader wrapper that tracks bytes read and invokes the progress callback on each Read call.
- Read · method · L247-L254 — Delegates to the underlying reader, accumulates the byte count, and fires the progress callback with the updated downloaded/total values.
