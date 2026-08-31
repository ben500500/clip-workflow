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
    at: 'backend/app/api/slice.py:L115-L177'
  - symbol: upload_hook_video
    kind: function
    at: 'backend/app/api/slice.py:L181-L242'
  - symbol: upload_hook_folder
    kind: function
    at: 'backend/app/api/slice.py:L246-L333'
  - symbol: get_raw_preview_url
    kind: function
    at: 'backend/app/api/slice.py:L337-L368'
  - symbol: upload_subtitle_file
    kind: function
    at: 'backend/app/api/slice.py:L371-L429'
  - symbol: get_slice_preferences
    kind: function
    at: 'backend/app/api/slice.py:L433-L442'
  - symbol: save_slice_preferences
    kind: function
    at: 'backend/app/api/slice.py:L446-L462'
  - symbol: _resolve_slice_inputs
    kind: function
    at: 'backend/app/api/slice.py:L465-L776'
  - symbol: _create_slice_task_record
    kind: function
    at: 'backend/app/api/slice.py:L779-L897'
  - symbol: _dispatch_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L900-L1070'
  - symbol: _restore_clips_from_run
    kind: function
    at: 'backend/app/api/slice.py:L1073-L1143'
  - symbol: run_slice
    kind: function
    at: 'backend/app/api/slice.py:L1147-L1187'
  - symbol: list_slice_tasks
    kind: function
    at: 'backend/app/api/slice.py:L1191-L1218'
  - symbol: get_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1222-L1271'
  - symbol: get_slice_outputs
    kind: function
    at: 'backend/app/api/slice.py:L1275-L1315'
  - symbol: get_slice_output
    kind: function
    at: 'backend/app/api/slice.py:L1319-L1349'
  - symbol: get_slice_upload_url
    kind: function
    at: 'backend/app/api/slice.py:L1353-L1391'
  - symbol: slice_task_callback
    kind: function
    at: 'backend/app/api/slice.py:L1395-L1550'
  - symbol: update_slice_progress
    kind: function
    at: 'backend/app/api/slice.py:L1554-L1580'
  - symbol: retry_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1584-L1790'
  - symbol: cancel_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1794-L1841'
  - symbol: delete_slice_task
    kind: function
    at: 'backend/app/api/slice.py:L1845-L1907'
  - symbol: BadgeItem
    kind: class
    at: 'backend/app/api/slice_helpers.py:L64-L77'
  - symbol: TextOverlayItem
    kind: class
    at: 'backend/app/api/slice_helpers.py:L80-L97'
  - symbol: SliceRunRequest
    kind: class
    at: 'backend/app/api/slice_helpers.py:L100-L312'
  - symbol: SliceRunResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L315-L320'
  - symbol: SliceTaskResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L323-L360'
  - symbol: SliceOutputResponse
    kind: class
    at: 'backend/app/api/slice_helpers.py:L363-L375'
  - symbol: SliceTaskCallback
    kind: class
    at: 'backend/app/api/slice_helpers.py:L378-L388'
  - symbol: UserSliceConfigRequest
    kind: class
    at: 'backend/app/api/slice_helpers.py:L391-L392'
  - symbol: _serialize_task
    kind: function
    at: 'backend/app/api/slice_helpers.py:L400-L429'
  - symbol: _serialize_output
    kind: function
    at: 'backend/app/api/slice_helpers.py:L432-L444'
  - symbol: _ffprobe_duration
    kind: function
    at: 'backend/app/api/slice_helpers.py:L452-L463'
  - symbol: _resolve_engine
    kind: function
    at: 'backend/app/api/slice_helpers.py:L466-L474'
  - symbol: _build_watermark_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L477-L509'
  - symbol: _build_vert2horiz_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L512-L544'
  - symbol: _build_badges_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L547-L579'
  - symbol: _build_text_overlays_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L582-L615'
  - symbol: _build_remotion_mix_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L618-L680'
  - symbol: _build_subtitle_mask_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L683-L720'
  - symbol: _build_watermark_mask_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L723-L751'
  - symbol: _read_existing_subtitle
    kind: function
    at: 'backend/app/api/slice_helpers.py:L764-L798'
  - symbol: _with_subtitle_options
    kind: function
    at: 'backend/app/api/slice_helpers.py:L801-L815'
  - symbol: _read_uploaded_subtitle
    kind: function
    at: 'backend/app/api/slice_helpers.py:L818-L846'
  - symbol: _vtt_to_srt
    kind: function
    at: 'backend/app/api/slice_helpers.py:L849-L908'
  - symbol: _resolve_source_subtitle_srt
    kind: function
    at: 'backend/app/api/slice_helpers.py:L911-L948'
  - symbol: _generate_subtitle_config
    kind: function
    at: 'backend/app/api/slice_helpers.py:L951-L965'
  - symbol: _not_detect_task
    kind: function
    at: 'backend/app/api/slice_helpers.py:L968-L977'
  - symbol: _get_max_concurrent_tasks
    kind: function
    at: 'backend/app/api/slice_helpers.py:L980-L996'
  - symbol: _acquire_concurrency_slot
    kind: function
    at: 'backend/app/api/slice_helpers.py:L999-L1023'
  - symbol: _output_prefix
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1026-L1028'
  - symbol: _refresh_episode_status
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1031-L1075'
  - symbol: _publish_to_worker
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1078-L1257'
  - symbol: _subtitle_enabled
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1174-L1175'
  - symbol: _dispatch_celery
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1260-L1327'
  - symbol: _dispatch_local
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1330-L1643'
  - symbol: _finalize
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1396-L1408'
  - symbol: _do
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1402-L1407'
  - symbol: _verify_worker_token
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1646-L1656'
  - symbol: _detect_silence_points
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1670-L1714'
  - symbol: _nearest_in_window
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1717-L1732'
  - symbol: refine_clip_boundaries
    kind: function
    at: 'backend/app/api/slice_helpers.py:L1735-L1787'
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
