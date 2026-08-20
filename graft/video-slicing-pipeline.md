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
    at: 'backend/app/api/projects.py:L34-L44'
  - symbol: ProjectCreate
    kind: class
    at: 'backend/app/api/projects.py:L51-L54'
  - symbol: ProjectUpdate
    kind: class
    at: 'backend/app/api/projects.py:L57-L61'
  - symbol: ProjectResponse
    kind: class
    at: 'backend/app/api/projects.py:L64-L76'
  - symbol: EpisodeCreate
    kind: class
    at: 'backend/app/api/projects.py:L79-L85'
  - symbol: EpisodeResponse
    kind: class
    at: 'backend/app/api/projects.py:L88-L101'
  - symbol: EpisodeListResponse
    kind: class
    at: 'backend/app/api/projects.py:L104-L106'
  - symbol: ProjectOutputItem
    kind: class
    at: 'backend/app/api/projects.py:L109-L124'
  - symbol: ProjectOutputListResponse
    kind: class
    at: 'backend/app/api/projects.py:L127-L129'
  - symbol: _serialize_project
    kind: function
    at: 'backend/app/api/projects.py:L134-L150'
  - symbol: _serialize_episode
    kind: function
    at: 'backend/app/api/projects.py:L153-L166'
  - symbol: _data_scope_filter
    kind: function
    at: 'backend/app/api/projects.py:L172-L180'
  - symbol: _check_project_access
    kind: function
    at: 'backend/app/api/projects.py:L183-L187'
  - symbol: create_project
    kind: function
    at: 'backend/app/api/projects.py:L191-L206'
  - symbol: list_projects
    kind: function
    at: 'backend/app/api/projects.py:L210-L246'
  - symbol: project_stats
    kind: function
    at: 'backend/app/api/projects.py:L250-L307'
  - symbol: get_project
    kind: function
    at: 'backend/app/api/projects.py:L311-L333'
  - symbol: update_project
    kind: function
    at: 'backend/app/api/projects.py:L337-L368'
  - symbol: _cleanup_episode_minio
    kind: function
    at: 'backend/app/api/projects.py:L371-L386'
  - symbol: _cleanup_episode_media
    kind: function
    at: 'backend/app/api/projects.py:L389-L405'
  - symbol: delete_project
    kind: function
    at: 'backend/app/api/projects.py:L409-L448'
  - symbol: create_episode
    kind: function
    at: 'backend/app/api/projects.py:L455-L487'
  - symbol: list_episodes
    kind: function
    at: 'backend/app/api/projects.py:L491-L518'
  - symbol: list_project_outputs
    kind: function
    at: 'backend/app/api/projects.py:L522-L600'
  - symbol: get_episode
    kind: function
    at: 'backend/app/api/projects.py:L604-L656'
  - symbol: get_episode_video_url
    kind: function
    at: 'backend/app/api/projects.py:L660-L690'
  - symbol: delete_episode
    kind: function
    at: 'backend/app/api/projects.py:L694-L724'
  - symbol: _cleanup_orphan_media_files
    kind: function
    at: 'backend/app/api/projects.py:L727-L768'
  - symbol: _cleanup_episode_media_files
    kind: function
    at: 'backend/app/api/projects.py:L771-L792'
  - symbol: upload_badge_image
    kind: function
    at: 'backend/app/api/slice.py:L107-L169'
  - symbol: upload_subtitle_file
    kind: function
    at: 'backend/app/api/slice.py:L173-L231'
  - symbol: get_slice_preferences
    kind: function
    at: 'backend/app/api/slice.py:L235-L244'
  - symbol: save_slice_preferences
    kind: function
    at: 'backend/app/api/slice.py:L248-L264'
  - symbol: _resolve_slice_inputs
    kind: function
    at: 'backend/app/api/slice.py:L267-L556'
  - symbol: _create_slice_task_record
    kind: function
    at: 'backend/app/api/slice.py:L559-L645'
  - symbol: _dispatch_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L648-L806'
  - symbol: run_slice
    kind: function
    at: 'backend/app/api/slice.py:L810-L850'
  - symbol: list_slice_tasks
    kind: function
    at: 'backend/app/api/slice.py:L854-L881'
  - symbol: get_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L885-L934'
  - symbol: get_slice_outputs
    kind: function
    at: 'backend/app/api/slice.py:L938-L978'
  - symbol: get_slice_output
    kind: function
    at: 'backend/app/api/slice.py:L982-L1012'
  - symbol: get_slice_upload_url
    kind: function
    at: 'backend/app/api/slice.py:L1016-L1053'
  - symbol: slice_task_callback
    kind: function
    at: 'backend/app/api/slice.py:L1057-L1212'
  - symbol: update_slice_progress
    kind: function
    at: 'backend/app/api/slice.py:L1216-L1242'
  - symbol: retry_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1246-L1428'
  - symbol: cancel_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1432-L1471'
  - symbol: delete_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1475-L1533'
  - symbol: BadgeItem
    kind: class
    at: 'backend/app/api/slice_helpers.py:L63-L76'
  - symbol: TextOverlayItem
    kind: class
    at: 'backend/app/api/slice_helpers.py:L79-L96'
  - symbol: SliceRunRequest
    kind: class
    at: 'backend/app/api/slice_helpers.py:L99-L258'
  - symbol: SliceRunResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L261-L266'
  - symbol: SliceTaskResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L269-L294'
  - symbol: SliceOutputResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L297-L309'
  - symbol: SliceTaskCallback
    kind: class
    at: 'backend/app/api/slice_helpers.py:L312-L322'
  - symbol: UserSliceConfigRequest
    kind: class
    at: 'backend/app/api/slice_helpers.py:L325-L326'
  - symbol: _serialize_task
    kind: function
    at: 'backend/app/api/slice_helpers.py:L334-L358'
  - symbol: _serialize_output
    kind: function
    at: 'backend/app/api/slice_helpers.py:L361-L373'
  - symbol: _ffprobe_duration
    kind: function
    at: 'backend/app/api/slice_helpers.py:L381-L392'
  - symbol: _resolve_engine
    kind: function
    at: 'backend/app/api/slice_helpers.py:L395-L403'
  - symbol: _build_watermark_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L406-L438'
  - symbol: _build_vert2horiz_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L441-L473'
  - symbol: _build_badges_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L476-L508'
  - symbol: _build_text_overlays_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L511-L544'
  - symbol: _build_subtitle_mask_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L547-L584'
  - symbol: _build_watermark_mask_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L587-L615'
  - symbol: _read_existing_subtitle
    kind: function
    at: 'backend/app/api/slice_helpers.py:L628-L662'
  - symbol: _with_subtitle_options
    kind: function
    at: 'backend/app/api/slice_helpers.py:L665-L679'
  - symbol: _read_uploaded_subtitle
    kind: function
    at: 'backend/app/api/slice_helpers.py:L682-L710'
  - symbol: _vtt_to_srt
    kind: function
    at: 'backend/app/api/slice_helpers.py:L713-L772'
  - symbol: _resolve_source_subtitle_srt
    kind: function
    at: 'backend/app/api/slice_helpers.py:L775-L812'
  - symbol: _generate_subtitle_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L815-L829'
  - symbol: _not_detect_task
    kind: function
    at: 'backend/app/api/slice_helpers.py:L832-L841'
  - symbol: _get_max_concurrent_tasks
    kind: function
    at: 'backend/app/api/slice_helpers.py:L844-L860'
  - symbol: _acquire_concurrency_slot
    kind: function
    at: 'backend/app/api/slice_helpers.py:L863-L887'
  - symbol: _output_prefix
    kind: function
    at: 'backend/app/api/slice_helpers.py:L890-L892'
  - symbol: _refresh_episode_status
    kind: function
    at: 'backend/app/api/slice_helpers.py:L895-L939'
  - symbol: _publish_to_worker
    kind: function
    at: 'backend/app/api/slice_helpers.py:L942-L1082'
  - symbol: _subtitle_enabled
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1013-L1014'
  - symbol: _dispatch_celery
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1085-L1141'
  - symbol: _dispatch_local
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1144-L1378'
  - symbol: _verify_worker_token
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1381-L1391'
  - symbol: _detect_silence_points
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1405-L1449'
  - symbol: _nearest_in_window
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1452-L1467'
  - symbol: refine_clip_boundaries
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1470-L1522'
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
