---
name: MinIO Storage & Upload
slug: minio-storage-upload
type: system
sources:
  - path: backend/app/api/preview.py
    hash: 9225738a98138a7b7a7e9cd99c7c25788f739998e5f3b98b5fbe00c39532f9af
  - path: backend/app/api/upload.py
    hash: 097ff2da64325f228b294f641404a42a6e0d05c82ab593adb1b5607642fb9fea
sources_digest: 7412e017b12fbcf4f939bbd110fba861b1577ec623203c5f62d93df3e527bedc
links:
  - to: data-isolation-access-control
    relation: uses
    description: >-
      preview.py enforces data isolation via _check_output_scope traversing
      SliceOutput→SliceTask→Episode.
  - to: video-slicing-pipeline
    relation: uses
    description: slice.py uses minio_service for badge/subtitle uploads and presigned URLs.
generator:
  version: 1
covers:
  - symbol: BatchDownloadRequest
    kind: class
    at: 'backend/app/api/preview.py:L29-L30'
  - symbol: BatchDownloadItem
    kind: class
    at: 'backend/app/api/preview.py:L33-L36'
  - symbol: BatchDownloadResponse
    kind: class
    at: 'backend/app/api/preview.py:L39-L40'
  - symbol: _check_output_scope
    kind: function
    at: 'backend/app/api/preview.py:L43-L56'
  - symbol: preview_frames
    kind: function
    at: 'backend/app/api/preview.py:L60-L111'
  - symbol: preview_video
    kind: function
    at: 'backend/app/api/preview.py:L115-L148'
  - symbol: download_output
    kind: function
    at: 'backend/app/api/preview.py:L152-L201'
  - symbol: _cleanup_tmp
    kind: function
    at: 'backend/app/api/preview.py:L204-L209'
  - symbol: batch_download
    kind: function
    at: 'backend/app/api/preview.py:L213-L270'
  - symbol: UploadResumeRequest
    kind: class
    at: 'backend/app/api/upload.py:L36-L40'
  - symbol: UploadResumeResponse
    kind: class
    at: 'backend/app/api/upload.py:L43-L49'
  - symbol: UploadProgressResponse
    kind: class
    at: 'backend/app/api/upload.py:L52-L58'
  - symbol: UploadCompleteRequest
    kind: class
    at: 'backend/app/api/upload.py:L61-L65'
  - symbol: MultiUploadResponse
    kind: class
    at: 'backend/app/api/upload.py:L68-L72'
  - symbol: _serialize_episode
    kind: function
    at: 'backend/app/api/upload.py:L75-L88'
  - symbol: _check_project_access
    kind: function
    at: 'backend/app/api/upload.py:L91-L99'
  - symbol: _store_uploaded_file
    kind: function
    at: 'backend/app/api/upload.py:L102-L149'
  - symbol: create_upload
    kind: function
    at: 'backend/app/api/upload.py:L153-L178'
  - symbol: get_upload_info
    kind: function
    at: 'backend/app/api/upload.py:L182-L197'
  - symbol: upload_chunk
    kind: function
    at: 'backend/app/api/upload.py:L201-L230'
  - symbol: complete_upload
    kind: function
    at: 'backend/app/api/upload.py:L234-L268'
  - symbol: upload_single
    kind: function
    at: 'backend/app/api/upload.py:L272-L342'
  - symbol: upload_multi
    kind: function
    at: 'backend/app/api/upload.py:L346-L509'
  - symbol: _check_av_sync
    kind: function
    at: 'backend/app/api/upload.py:L512-L551'
  - symbol: _run_ffmpeg
    kind: function
    at: 'backend/app/api/upload.py:L554-L567'
  - symbol: _ffmpeg_concat
    kind: function
    at: 'backend/app/api/upload.py:L570-L619'
  - symbol: cancel_upload
    kind: function
    at: 'backend/app/api/upload.py:L623-L626'
---
<!-- context:generated:start -->
## Summary

Object storage layer: presigned URL generation for previews, downloads, and batch downloads (up to 100 outputs), plus upload endpoints. Upload supports tus-compatible resumable protocol, single-request, and multi-file batch with optional ffmpeg merging. Runs audio-video sync check via ffprobe to reject duration-mismatched files before they enter the pipeline; _ffmpeg_concat normalizes timestamps with -avoid_negative_ts make_zero to avoid DTS discontinuities, falling back to re-encoding if stream copy fails. Returns JSON URLs instead of redirects so the frontend keeps the Authorization header.

## Related

- uses [[data-isolation-access-control]] — preview.py enforces data isolation via _check_output_scope traversing SliceOutput→SliceTask→Episode.
- uses [[video-slicing-pipeline]] — slice.py uses minio_service for badge/subtitle uploads and presigned URLs.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
