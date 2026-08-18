---
name: Watermark Removal
slug: watermark-removal
type: system
sources:
  - path: backend/app/api/watermark.py
    hash: 21a9c2d3640e16b2358ef738aa301f740a8e3fbdd0c5375c2e130808671888bc
sources_digest: f2e09511377cf3cebd29063e972a44c31862fda5a597e7eb91cda39297bef3db
links:
  - to: minio-storage-upload
    relation: uses
    description: Uses MinIO services for file storage and presigned URLs.
generator:
  version: 1
covers:
  - symbol: gen_task_name
    kind: function
    at: 'backend/app/api/watermark.py:L46-L65'
  - symbol: _fallback_seq
    kind: function
    at: 'backend/app/api/watermark.py:L71-L74'
  - symbol: WatermarkRunRequest
    kind: class
    at: 'backend/app/api/watermark.py:L90-L114'
  - symbol: WatermarkVideoItem
    kind: class
    at: 'backend/app/api/watermark.py:L117-L131'
  - symbol: WatermarkTaskItem
    kind: class
    at: 'backend/app/api/watermark.py:L134-L150'
  - symbol: WatermarkTaskDetail
    kind: class
    at: 'backend/app/api/watermark.py:L153-L154'
  - symbol: WatermarkDeleteRequest
    kind: class
    at: 'backend/app/api/watermark.py:L157-L158'
  - symbol: _serialize_video
    kind: function
    at: 'backend/app/api/watermark.py:L166-L186'
  - symbol: _serialize_task
    kind: function
    at: 'backend/app/api/watermark.py:L189-L215'
  - symbol: upload_watermark_video
    kind: function
    at: 'backend/app/api/watermark.py:L224-L275'
  - symbol: run_watermark_task
    kind: function
    at: 'backend/app/api/watermark.py:L279-L428'
  - symbol: list_watermark_tasks
    kind: function
    at: 'backend/app/api/watermark.py:L432-L460'
  - symbol: get_watermark_task
    kind: function
    at: 'backend/app/api/watermark.py:L464-L511'
  - symbol: delete_watermark_task
    kind: function
    at: 'backend/app/api/watermark.py:L515-L556'
  - symbol: batch_delete_watermark_tasks
    kind: function
    at: 'backend/app/api/watermark.py:L560-L608'
  - symbol: delete_watermark_video
    kind: function
    at: 'backend/app/api/watermark.py:L612-L641'
  - symbol: download_watermark_video
    kind: function
    at: 'backend/app/api/watermark.py:L645-L671'
  - symbol: batch_download_watermark_videos
    kind: function
    at: 'backend/app/api/watermark.py:L675-L711'
---
<!-- context:generated:start -->
## Summary

v4 watermark removal API supporting four engines (remove_ai, seedance, seedance_wm, remove_mask) with engine-specific options (region, segments, detector, inpainter) validated and persisted into task options. Uses Redis for cross-instance task name sequence generation, marks running tasks as cancelled before deleting resources to prevent worker conflicts, and preserves source files belonging to prompt records during deletion. Enforces 200-video batch limit and 100-item batch delete/download limits.

## Related

- uses [[minio-storage-upload]] — Uses MinIO services for file storage and presigned URLs.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
