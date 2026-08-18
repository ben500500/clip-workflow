---
name: Video Slicing Pipeline
slug: video-slicing-pipeline
type: system
sources:
  - path: backend/app/api/projects.py
    hash: 37f06b824474fae30f8705f8d2e947a87d0ac69f820336301c760537a0a1377c
  - path: backend/app/api/slice_helpers.py
    hash: cf30b6d84ff85693edfdddf545be88db80f054845506ceddf93d08f26fe37ffb
  - path: backend/app/api/slice.py
    hash: 827b87b74fad0a42eb282ac3cde89d47711b448dd68c59bd21d28997a9c9c6d0
sources_digest: cd08a9251ac5d19eef1711fdb4fdfdee61eea67d07a608fe295c6db01b260c47
links:
  - to: autoclip-pipeline-batch-slicing
    relation: uses
    description: >-
      slice.py imports run_autoclip for backend fallback when no clip candidates
      exist.
  - to: data-isolation-access-control
    relation: uses
    description: run_slice validates episode access via check_project_access_by_episode.
  - to: minio-storage-upload
    relation: uses
    description: Uses minio_service for badge/subtitle uploads and presigned URLs.
generator:
  version: 1
covers:
  - symbol: _remove_path
    kind: function
    at: 'backend/app/api/projects.py:L37-L47'
  - symbol: ProjectCreate
    kind: class
    at: 'backend/app/api/projects.py:L54-L57'
  - symbol: ProjectUpdate
    kind: class
    at: 'backend/app/api/projects.py:L60-L64'
  - symbol: ProjectResponse
    kind: class
    at: 'backend/app/api/projects.py:L67-L79'
  - symbol: EpisodeCreate
    kind: class
    at: 'backend/app/api/projects.py:L82-L88'
  - symbol: EpisodeResponse
    kind: class
    at: 'backend/app/api/projects.py:L91-L104'
  - symbol: EpisodeListResponse
    kind: class
    at: 'backend/app/api/projects.py:L107-L109'
  - symbol: ProjectOutputItem
    kind: class
    at: 'backend/app/api/projects.py:L112-L127'
  - symbol: ProjectOutputListResponse
    kind: class
    at: 'backend/app/api/projects.py:L130-L132'
  - symbol: _serialize_project
    kind: function
    at: 'backend/app/api/projects.py:L137-L153'
  - symbol: _serialize_episode
    kind: function
    at: 'backend/app/api/projects.py:L156-L169'
  - symbol: _data_scope_filter
    kind: function
    at: 'backend/app/api/projects.py:L175-L183'
  - symbol: _check_project_access
    kind: function
    at: 'backend/app/api/projects.py:L186-L190'
  - symbol: create_project
    kind: function
    at: 'backend/app/api/projects.py:L194-L209'
  - symbol: list_projects
    kind: function
    at: 'backend/app/api/projects.py:L213-L249'
  - symbol: project_stats
    kind: function
    at: 'backend/app/api/projects.py:L253-L310'
  - symbol: get_project
    kind: function
    at: 'backend/app/api/projects.py:L314-L336'
  - symbol: update_project
    kind: function
    at: 'backend/app/api/projects.py:L340-L371'
  - symbol: _cleanup_episode_minio
    kind: function
    at: 'backend/app/api/projects.py:L374-L389'
  - symbol: _cleanup_episode_media
    kind: function
    at: 'backend/app/api/projects.py:L392-L408'
  - symbol: delete_project
    kind: function
    at: 'backend/app/api/projects.py:L412-L451'
  - symbol: create_episode
    kind: function
    at: 'backend/app/api/projects.py:L458-L490'
  - symbol: list_episodes
    kind: function
    at: 'backend/app/api/projects.py:L494-L521'
  - symbol: list_project_outputs
    kind: function
    at: 'backend/app/api/projects.py:L525-L603'
  - symbol: project_workflow_status
    kind: function
    at: 'backend/app/api/projects.py:L608-L791'
  - symbol: _stage_status
    kind: function
    at: 'backend/app/api/projects.py:L671-L682'
  - symbol: get_episode
    kind: function
    at: 'backend/app/api/projects.py:L795-L847'
  - symbol: get_episode_video_url
    kind: function
    at: 'backend/app/api/projects.py:L851-L881'
  - symbol: delete_episode
    kind: function
    at: 'backend/app/api/projects.py:L885-L915'
  - symbol: _cleanup_orphan_media_files
    kind: function
    at: 'backend/app/api/projects.py:L918-L957'
  - symbol: _cleanup_episode_media_files
    kind: function
    at: 'backend/app/api/projects.py:L960-L981'
  - symbol: upload_badge_image
    kind: function
    at: 'backend/app/api/slice.py:L104-L166'
  - symbol: upload_subtitle_file
    kind: function
    at: 'backend/app/api/slice.py:L170-L228'
  - symbol: get_slice_preferences
    kind: function
    at: 'backend/app/api/slice.py:L232-L241'
  - symbol: save_slice_preferences
    kind: function
    at: 'backend/app/api/slice.py:L245-L261'
  - symbol: run_slice
    kind: function
    at: 'backend/app/api/slice.py:L265-L662'
  - symbol: list_slice_tasks
    kind: function
    at: 'backend/app/api/slice.py:L666-L693'
  - symbol: get_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L697-L746'
  - symbol: get_slice_outputs
    kind: function
    at: 'backend/app/api/slice.py:L750-L790'
  - symbol: get_slice_upload_url
    kind: function
    at: 'backend/app/api/slice.py:L794-L831'
  - symbol: slice_task_callback
    kind: function
    at: 'backend/app/api/slice.py:L835-L965'
  - symbol: update_slice_progress
    kind: function
    at: 'backend/app/api/slice.py:L969-L995'
  - symbol: retry_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L999-L1140'
  - symbol: cancel_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1144-L1183'
  - symbol: delete_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1187-L1245'
  - symbol: BadgeItem
    kind: class
    at: 'backend/app/api/slice_helpers.py:L63-L76'
  - symbol: TextOverlayItem
    kind: class
    at: 'backend/app/api/slice_helpers.py:L79-L96'
  - symbol: SliceRunRequest
    kind: class
    at: 'backend/app/api/slice_helpers.py:L99-L249'
  - symbol: SliceRunResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L252-L257'
  - symbol: SliceTaskResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L260-L285'
  - symbol: SliceOutputResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L288-L300'
  - symbol: SliceTaskCallback
    kind: class
    at: 'backend/app/api/slice_helpers.py:L303-L313'
  - symbol: UserSliceConfigRequest
    kind: class
    at: 'backend/app/api/slice_helpers.py:L316-L317'
  - symbol: _serialize_task
    kind: function
    at: 'backend/app/api/slice_helpers.py:L325-L349'
  - symbol: _serialize_output
    kind: function
    at: 'backend/app/api/slice_helpers.py:L352-L364'
  - symbol: _ffprobe_duration
    kind: function
    at: 'backend/app/api/slice_helpers.py:L372-L383'
  - symbol: _resolve_engine
    kind: function
    at: 'backend/app/api/slice_helpers.py:L386-L394'
  - symbol: _build_watermark_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L397-L429'
  - symbol: _build_vert2horiz_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L432-L464'
  - symbol: _build_badges_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L467-L499'
  - symbol: _build_text_overlays_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L502-L535'
  - symbol: _build_subtitle_mask_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L538-L575'
  - symbol: _build_watermark_mask_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L578-L606'
  - symbol: _read_existing_subtitle
    kind: function
    at: 'backend/app/api/slice_helpers.py:L619-L653'
  - symbol: _with_subtitle_options
    kind: function
    at: 'backend/app/api/slice_helpers.py:L656-L670'
  - symbol: _read_uploaded_subtitle
    kind: function
    at: 'backend/app/api/slice_helpers.py:L673-L701'
  - symbol: _vtt_to_srt
    kind: function
    at: 'backend/app/api/slice_helpers.py:L704-L763'
  - symbol: _resolve_source_subtitle_srt
    kind: function
    at: 'backend/app/api/slice_helpers.py:L766-L803'
  - symbol: _generate_subtitle_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L806-L820'
  - symbol: _not_detect_task
    kind: function
    at: 'backend/app/api/slice_helpers.py:L823-L832'
  - symbol: _get_max_concurrent_tasks
    kind: function
    at: 'backend/app/api/slice_helpers.py:L835-L851'
  - symbol: _acquire_concurrency_slot
    kind: function
    at: 'backend/app/api/slice_helpers.py:L854-L878'
  - symbol: _output_prefix
    kind: function
    at: 'backend/app/api/slice_helpers.py:L881-L883'
  - symbol: _refresh_episode_status
    kind: function
    at: 'backend/app/api/slice_helpers.py:L886-L930'
  - symbol: _publish_to_worker
    kind: function
    at: 'backend/app/api/slice_helpers.py:L933-L1073'
  - symbol: _subtitle_enabled
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1004-L1005'
  - symbol: _dispatch_celery
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1076-L1132'
  - symbol: _verify_worker_token
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1135-L1145'
---
<!-- context:generated:start -->
## Summary

Core slicing workflow: run_slice orchestrates three modes (no-cut fast conversion, re-cutting from existing output, standard clip-based slicing), manages fallback when no accepted clips exist, acquires concurrency slots, creates SliceTask records, and dispatches via Redis Streams to Go workers with Celery fallback. slice_helpers builds engine-specific configs (watermark, badges, subtitles, masking, vert2horiz, GPU encoding), reuses ASR-generated subtitles from the autoclip selection phase via _read_existing_subtitle to avoid redundant transcription, and persists all config variants on the task record for retry scenarios. Includes a race-condition mitigation polling for clip candidates after autoclip completion.

## Related

- uses [[autoclip-pipeline-batch-slicing]] — slice.py imports run_autoclip for backend fallback when no clip candidates exist.
- uses [[data-isolation-access-control]] — run_slice validates episode access via check_project_access_by_episode.
- uses [[minio-storage-upload]] — Uses minio_service for badge/subtitle uploads and presigned URLs.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
