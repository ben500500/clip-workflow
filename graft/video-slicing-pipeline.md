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
    at: 'backend/app/api/projects.py:L88-L103'
  - symbol: EpisodeListResponse
    kind: class
    at: 'backend/app/api/projects.py:L106-L108'
  - symbol: ProjectOutputItem
    kind: class
    at: 'backend/app/api/projects.py:L111-L126'
  - symbol: ProjectOutputListResponse
    kind: class
    at: 'backend/app/api/projects.py:L129-L131'
  - symbol: _serialize_project
    kind: function
    at: 'backend/app/api/projects.py:L136-L152'
  - symbol: _serialize_episode
    kind: function
    at: 'backend/app/api/projects.py:L155-L169'
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
  - symbol: get_episode
    kind: function
    at: 'backend/app/api/projects.py:L607-L659'
  - symbol: EpisodeUpdate
    kind: class
    at: 'backend/app/api/projects.py:L662-L664'
  - symbol: update_episode
    kind: function
    at: 'backend/app/api/projects.py:L668-L706'
  - symbol: get_episode_video_url
    kind: function
    at: 'backend/app/api/projects.py:L710-L740'
  - symbol: delete_episode
    kind: function
    at: 'backend/app/api/projects.py:L744-L774'
  - symbol: _cleanup_orphan_media_files
    kind: function
    at: 'backend/app/api/projects.py:L777-L818'
  - symbol: _cleanup_episode_media_files
    kind: function
    at: 'backend/app/api/projects.py:L821-L842'
  - symbol: upload_badge_image
    kind: function
    at: 'backend/app/api/slice.py:L116-L178'
  - symbol: upload_hook_video
    kind: function
    at: 'backend/app/api/slice.py:L182-L243'
  - symbol: upload_hook_folder
    kind: function
    at: 'backend/app/api/slice.py:L247-L334'
  - symbol: get_raw_preview_url
    kind: function
    at: 'backend/app/api/slice.py:L338-L369'
  - symbol: upload_subtitle_file
    kind: function
    at: 'backend/app/api/slice.py:L372-L430'
  - symbol: get_slice_preferences
    kind: function
    at: 'backend/app/api/slice.py:L434-L443'
  - symbol: save_slice_preferences
    kind: function
    at: 'backend/app/api/slice.py:L447-L463'
  - symbol: _resolve_slice_inputs
    kind: function
    at: 'backend/app/api/slice.py:L466-L806'
  - symbol: _create_slice_task_record
    kind: function
    at: 'backend/app/api/slice.py:L809-L927'
  - symbol: _dispatch_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L930-L1100'
  - symbol: _restore_clips_from_run
    kind: function
    at: 'backend/app/api/slice.py:L1103-L1173'
  - symbol: run_slice
    kind: function
    at: 'backend/app/api/slice.py:L1177-L1217'
  - symbol: list_slice_tasks
    kind: function
    at: 'backend/app/api/slice.py:L1221-L1248'
  - symbol: get_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1252-L1301'
  - symbol: get_slice_outputs
    kind: function
    at: 'backend/app/api/slice.py:L1305-L1345'
  - symbol: get_slice_output
    kind: function
    at: 'backend/app/api/slice.py:L1349-L1379'
  - symbol: get_slice_upload_url
    kind: function
    at: 'backend/app/api/slice.py:L1383-L1421'
  - symbol: slice_task_callback
    kind: function
    at: 'backend/app/api/slice.py:L1425-L1580'
  - symbol: update_slice_progress
    kind: function
    at: 'backend/app/api/slice.py:L1584-L1610'
  - symbol: retry_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1614-L1820'
  - symbol: cancel_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1824-L1871'
  - symbol: delete_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1875-L1937'
  - symbol: BadgeItem
    kind: class
    at: 'backend/app/api/slice_helpers.py:L64-L77'
  - symbol: TextOverlayItem
    kind: class
    at: 'backend/app/api/slice_helpers.py:L80-L97'
  - symbol: SliceRunRequest
    kind: class
    at: 'backend/app/api/slice_helpers.py:L100-L315'
  - symbol: SliceRunResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L318-L323'
  - symbol: SliceTaskResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L326-L363'
  - symbol: SliceOutputResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L366-L378'
  - symbol: SliceTaskCallback
    kind: class
    at: 'backend/app/api/slice_helpers.py:L381-L391'
  - symbol: UserSliceConfigRequest
    kind: class
    at: 'backend/app/api/slice_helpers.py:L394-L395'
  - symbol: _serialize_task
    kind: function
    at: 'backend/app/api/slice_helpers.py:L403-L432'
  - symbol: _serialize_output
    kind: function
    at: 'backend/app/api/slice_helpers.py:L435-L447'
  - symbol: _ffprobe_duration
    kind: function
    at: 'backend/app/api/slice_helpers.py:L455-L466'
  - symbol: _resolve_engine
    kind: function
    at: 'backend/app/api/slice_helpers.py:L469-L477'
  - symbol: _build_watermark_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L480-L512'
  - symbol: _build_vert2horiz_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L515-L547'
  - symbol: _build_badges_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L550-L582'
  - symbol: _build_text_overlays_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L585-L618'
  - symbol: _build_remotion_mix_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L621-L683'
  - symbol: _build_subtitle_mask_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L686-L723'
  - symbol: _build_watermark_mask_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L726-L754'
  - symbol: _read_existing_subtitle
    kind: function
    at: 'backend/app/api/slice_helpers.py:L767-L801'
  - symbol: _with_subtitle_options
    kind: function
    at: 'backend/app/api/slice_helpers.py:L804-L821'
  - symbol: _read_uploaded_subtitle
    kind: function
    at: 'backend/app/api/slice_helpers.py:L824-L852'
  - symbol: _vtt_to_srt
    kind: function
    at: 'backend/app/api/slice_helpers.py:L855-L914'
  - symbol: _resolve_source_subtitle_srt
    kind: function
    at: 'backend/app/api/slice_helpers.py:L917-L954'
  - symbol: _generate_subtitle_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L957-L971'
  - symbol: _not_detect_task
    kind: function
    at: 'backend/app/api/slice_helpers.py:L974-L983'
  - symbol: _get_max_concurrent_tasks
    kind: function
    at: 'backend/app/api/slice_helpers.py:L986-L1002'
  - symbol: _acquire_concurrency_slot
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1005-L1029'
  - symbol: _output_prefix
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1032-L1034'
  - symbol: _refresh_episode_status
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1037-L1095'
  - symbol: _publish_to_worker
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1098-L1277'
  - symbol: _subtitle_enabled
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1194-L1195'
  - symbol: _dispatch_celery
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1280-L1347'
  - symbol: _dispatch_local
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1350-L1670'
  - symbol: _finalize
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1416-L1428'
  - symbol: _do
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1422-L1427'
  - symbol: _verify_worker_token
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1673-L1683'
  - symbol: _detect_silence_points
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1697-L1741'
  - symbol: _nearest_in_window
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1744-L1759'
  - symbol: refine_clip_boundaries
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1762-L1814'
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
