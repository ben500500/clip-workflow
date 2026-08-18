---
name: AutoClip Pipeline & Batch Slicing
slug: autoclip-pipeline-batch-slicing
type: system
sources:
  - path: backend/app/api/autoclip.py
    hash: 1e998bdded81d944f1c4865f9a07b082e0a4a505a47057342c04e5c06473d98b
  - path: backend/app/api/batch_slice.py
    hash: 078afcff0bc659b47238493410f964aa353dc52bc4cbaba929f41d051c8d808d
  - path: backend/app/api/intervals.py
    hash: f5b361075c469e8fbac6e798025abc692c1ace58cdecf6f63d10b9b85b17cd8c
sources_digest: db14c38ba28d7552f962cbafacab88312684490cb34729056c50f6e64c000a4b
links:
  - to: data-isolation-access-control
    relation: uses
    description: Uses check_project_access_by_episode and check_project_access_by_id.
  - to: video-slicing-pipeline
    relation: uses
    description: slice.py falls back to run_autoclip when no clip candidates exist.
generator:
  version: 1
covers:
  - symbol: _merge_default_autoclip_config
    kind: function
    at: 'backend/app/api/autoclip.py:L32-L54'
  - symbol: AutoClipRunRequest
    kind: class
    at: 'backend/app/api/autoclip.py:L58-L60'
  - symbol: AutoClipRunResponse
    kind: class
    at: 'backend/app/api/autoclip.py:L63-L66'
  - symbol: AutoClipProgressResponse
    kind: class
    at: 'backend/app/api/autoclip.py:L69-L73'
  - symbol: AutoClipRunResponseItem
    kind: class
    at: 'backend/app/api/autoclip.py:L76-L90'
  - symbol: ClipUpdateRequest
    kind: class
    at: 'backend/app/api/autoclip.py:L93-L96'
  - symbol: ClipResponse
    kind: class
    at: 'backend/app/api/autoclip.py:L99-L116'
  - symbol: _serialize_clip
    kind: function
    at: 'backend/app/api/autoclip.py:L119-L136'
  - symbol: _serialize_autoclip_run
    kind: function
    at: 'backend/app/api/autoclip.py:L139-L153'
  - symbol: run_autoclip
    kind: function
    at: 'backend/app/api/autoclip.py:L157-L275'
  - symbol: get_autoclip_history
    kind: function
    at: 'backend/app/api/autoclip.py:L279-L305'
  - symbol: get_autoclip_progress
    kind: function
    at: 'backend/app/api/autoclip.py:L309-L367'
  - symbol: get_autoclip_clips
    kind: function
    at: 'backend/app/api/autoclip.py:L371-L398'
  - symbol: update_clip
    kind: function
    at: 'backend/app/api/autoclip.py:L402-L440'
  - symbol: regenerate_autoclip
    kind: function
    at: 'backend/app/api/autoclip.py:L444-L484'
  - symbol: BatchEpisodeItem
    kind: class
    at: 'backend/app/api/batch_slice.py:L42-L45'
  - symbol: BatchSliceRunRequest
    kind: class
    at: 'backend/app/api/batch_slice.py:L48-L59'
  - symbol: BatchSliceRunResponse
    kind: class
    at: 'backend/app/api/batch_slice.py:L62-L65'
  - symbol: BatchSliceItemResponse
    kind: class
    at: 'backend/app/api/batch_slice.py:L68-L86'
  - symbol: BatchSliceResponse
    kind: class
    at: 'backend/app/api/batch_slice.py:L89-L104'
  - symbol: BatchSliceOutputItem
    kind: class
    at: 'backend/app/api/batch_slice.py:L107-L114'
  - symbol: BatchSliceOutputResponse
    kind: class
    at: 'backend/app/api/batch_slice.py:L117-L119'
  - symbol: _serialize_batch
    kind: function
    at: 'backend/app/api/batch_slice.py:L127-L142'
  - symbol: _serialize_item
    kind: function
    at: 'backend/app/api/batch_slice.py:L145-L163'
  - symbol: _load_batch_owned
    kind: function
    at: 'backend/app/api/batch_slice.py:L166-L179'
  - symbol: run_batch_slice
    kind: function
    at: 'backend/app/api/batch_slice.py:L188-L240'
  - symbol: list_batch_slices
    kind: function
    at: 'backend/app/api/batch_slice.py:L244-L254'
  - symbol: get_batch_slice
    kind: function
    at: 'backend/app/api/batch_slice.py:L258-L265'
  - symbol: get_batch_items
    kind: function
    at: 'backend/app/api/batch_slice.py:L269-L282'
  - symbol: get_batch_outputs
    kind: function
    at: 'backend/app/api/batch_slice.py:L286-L361'
  - symbol: retry_batch_slice
    kind: function
    at: 'backend/app/api/batch_slice.py:L365-L395'
  - symbol: cancel_batch_slice
    kind: function
    at: 'backend/app/api/batch_slice.py:L399-L420'
  - symbol: DetectRequest
    kind: class
    at: 'backend/app/api/intervals.py:L22-L25'
  - symbol: DetectResponse
    kind: class
    at: 'backend/app/api/intervals.py:L28-L30'
  - symbol: DetectProgressResponse
    kind: class
    at: 'backend/app/api/intervals.py:L33-L39'
  - symbol: IntervalCreate
    kind: class
    at: 'backend/app/api/intervals.py:L42-L50'
  - symbol: IntervalUpdate
    kind: class
    at: 'backend/app/api/intervals.py:L53-L60'
  - symbol: IntervalResponse
    kind: class
    at: 'backend/app/api/intervals.py:L63-L76'
  - symbol: IntervalHistoryItem
    kind: class
    at: 'backend/app/api/intervals.py:L79-L91'
  - symbol: _serialize_interval
    kind: function
    at: 'backend/app/api/intervals.py:L94-L107'
  - symbol: detect_intervals
    kind: function
    at: 'backend/app/api/intervals.py:L111-L186'
  - symbol: get_detect_progress
    kind: function
    at: 'backend/app/api/intervals.py:L190-L281'
  - symbol: list_intervals
    kind: function
    at: 'backend/app/api/intervals.py:L285-L310'
  - symbol: get_interval_history
    kind: function
    at: 'backend/app/api/intervals.py:L314-L376'
  - symbol: create_interval
    kind: function
    at: 'backend/app/api/intervals.py:L380-L413'
  - symbol: update_interval
    kind: function
    at: 'backend/app/api/intervals.py:L417-L460'
  - symbol: delete_interval
    kind: function
    at: 'backend/app/api/intervals.py:L464-L490'
  - symbol: toggle_interval
    kind: function
    at: 'backend/app/api/intervals.py:L494-L522'
---
<!-- context:generated:start -->
## Summary

AI clip-selection pipeline: autoclip.py router triggers Celery-backed runs, merges SystemConfig defaults into per-request configs, creates the new project before deleting old clips on regenerate (avoiding data loss), and commits AutoClipRun history before dispatching Celery to prevent races. Falls back to local DB status when the remote AutoClip service is unreachable. batch_slice.py orchestrates phase-3 one-click slicing across episodes, deferring project lookup/creation to the background task and supporting a legacy SliceTask fallback scan.

## Related

- uses [[data-isolation-access-control]] — Uses check_project_access_by_episode and check_project_access_by_id.
- uses [[video-slicing-pipeline]] — slice.py falls back to run_autoclip when no clip candidates exist.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
