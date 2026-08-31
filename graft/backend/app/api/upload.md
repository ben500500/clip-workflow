# backend/app/api/upload.py · [[minio-storage-upload]]

- UploadResumeRequest · class · L36-L40 — Request payload for initiating a resumable upload session, carrying file name, size, chunk size, and metadata.
- UploadResumeResponse · class · L43-L49 — Response model returning the created upload session id and current offset for resumable uploads.
- UploadProgressResponse · class · L52-L58 — Response model reporting upload progress including offset, completion flag, and percentage.
- UploadCompleteRequest · class · L61-L65 — Request payload finalizing an upload session into an Episode, carrying upload id, project id, title, and episode number.
- MultiUploadResponse · class · L68-L72 — Response model summarizing a multi-video batch upload result with project info and created episodes.
- _serialize_episode · function · L75-L89 — Converts an Episode ORM object into a plain dict with stringified ids and ISO timestamps for API responses.
- _check_project_access · function · L92-L100 — Enforces data isolation by allowing only the project creator (or a user with global material access) to upload to a project, returning 404 otherwise.
- _store_uploaded_file · function · L103-L150 — Finalizes a completed tus upload session by validating the project exists, running AV-sync check, storing the file in MinIO, and creating an Episode record.
- create_upload · function · L154-L179 — Creates a new tus-like resumable upload session after validating file size bounds and file name.
- get_upload_info · function · L183-L198 — Handles tus HEAD requests to report current upload offset and length via response headers.
- upload_chunk · function · L202-L231 — Handles tus PATCH requests to write a chunk of data at the given offset, returning updated progress.
- complete_upload · function · L235-L269 — Finalizes a completed upload session into an Episode after validating project access and upload completion.
- upload_single · function · L273-L343 — Handles a single-request file upload: validates project access, streams the file to disk enforcing max size, runs AV-sync check, stores in MinIO, and creates an Episode.
- upload_multi · function · L347-L510 — Batch-uploads multiple videos into a project (found by id or created/found by name), optionally merging them into one Episode via ffmpeg concat, with per-file AV-sync checks and sequential episode numbering.
- _check_av_sync · function · L513-L552 — Rough audio-video sync validation that blocks files with mismatched audio/video durations from silently entering the production pipeline.
- _run_ffmpeg · function · L555-L568 — Runs a single ffmpeg subprocess command and returns success, logging the stderr tail on failure.
- _ffmpeg_concat · function · L571-L620 — Concatenates multiple videos into one using ffmpeg, first normalizing timestamps losslessly to fix DTS discontinuities, then stream-copying, and falling back to re-encoding when parameters mismatch.
- cancel_upload · function · L624-L627 — Cancels an in-progress upload session.
