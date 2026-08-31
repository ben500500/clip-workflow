# slice-worker/file_transfer.go · [[slice-worker-node]]

- FileTransfer · struct · L16-L19 — Holds the HTTP client and optional progress callback used for all file download/upload operations.
- NewFileTransfer · function · L22-L28 — Constructs a FileTransfer with an HTTP client configured with a long 30-minute timeout to accommodate large file transfers.
- SetProgressCallback · method · L31-L33 — Registers the callback invoked with download/upload progress updates.
- DownloadFile · method · L36-L102 — Downloads a file from a URL to a destination path, streaming in 32KB chunks while honoring context cancellation and reporting progress via the callback.
- UploadFile · method · L105-L143 — Uploads a local file to a presigned PUT URL, setting Content-Length and video/mp4 content type, and returns an error on non-2xx responses.
- UploadFileWithProgress · method · L146-L190 — Uploads a local file to a presigned PUT URL while wrapping the file in a progressReader so the callback reports upload progress.
- uploadURLResponse · struct · L193-L196 — Data holder for the backend's upload URL response containing the presigned URL and object file key.
- GetUploadURL · method · L202-L239 — Requests a backend-generated presigned PUT URL bound to a specific object key per output file, fixing MinIO signature invalidation from concatenating filenames into a single URL.
- progressReader · struct · L242-L249 — Reader wrapper that tracks bytes read and invokes the progress callback on each Read call.
- Read · method · L251-L258 — Delegates to the underlying reader, accumulates the byte count, and fires the progress callback with the updated downloaded/total values.
