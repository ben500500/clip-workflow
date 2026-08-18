# backend/app/api/upload.py

- UploadResumeRequest · class · L35-L39 — Request payload for initiating a resumable upload session, carrying file name, size, chunk size, and metadata.
- UploadResumeResponse · class · L42-L48 — Response model returning the created upload session id and current offset for resumable uploads.
- UploadProgressResponse · class · L51-L57 — Response model reporting upload progress including offset, completion flag, and percentage.
- UploadCompleteRequest · class · L60-L64 — Request payload finalizing an upload session into an Episode, carrying upload id, project id, title, and episode number.
- MultiUploadResponse · class · L67-L71 — Response model summarizing a multi-video batch upload result with project info and created episodes.
- _serialize_episode · function · L74-L87 — Converts an Episode ORM object into a plain dict with stringified ids and ISO timestamps for API responses.
- _check_project_access · function · L90-L98 — Enforces data isolation by allowing only the project creator (or a user with global material access) to upload to a project, returning 404 otherwise.
- _store_uploaded_file · function · L101-L140 — Finalizes a completed upload session by validating the project, moving the file to MinIO raw-footage storage, and creating an Episode record.
- create_upload · function · L144-L169 — Creates a new tus-like resumable upload session after validating file size bounds and file name.
- get_upload_info · function · L173-L188 — Handles tus HEAD requests to report current upload offset and length via response headers.
- upload_chunk · function · L192-L221 — Handles tus PATCH requests to write a chunk of data at the given offset, returning updated progress.
- get_upload_progress_endpoint · function · L225-L237 — Returns the current upload progress for a session as a JSON response.
- complete_upload · function · L241-L275 — Finalizes a completed upload session into an Episode after validating project access and upload completion.
- upload_single · function · L279-L340 — Handles a single-request file upload: validates project access, streams the file to disk enforcing max size, stores it in MinIO, and creates an Episode.
- upload_multi · function · L344-L459 — Batch-uploads multiple videos into a project found-or-created by name for the current user, optionally merging them into one Episode via ffmpeg, with episode numbering continuing from existing max.
- _run_ffmpeg · function · L462-L475 — Runs a single ffmpeg subprocess command and returns success, logging the stderr tail on failure.
- _ffmpeg_concat · function · L478-L527 — Concatenates multiple videos into one using ffmpeg, first normalizing timestamps losslessly to fix DTS discontinuities, then stream-copying, and falling back to re-encoding when parameters mismatch.
- cancel_upload · function · L531-L534 — Cancels an in-progress upload session.
