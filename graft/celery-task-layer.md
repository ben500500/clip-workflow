---
name: Celery Task Layer
slug: celery-task-layer
type: system
sources:
  - path: backend/app/celery/__init__.py
    hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - path: backend/app/celery/shortdrama_tasks.py
    hash: 1f5846bf3ec774a0f1fd76ac92e92ed890c585d1c60269be239a6187156cdb69
  - path: backend/app/celery/tasks.py
    hash: 58a8621b622bdb4caafd09b7c02c7f92bdcf9f247be94042e6104a74ba0cb0bf
  - path: backend/app/celery/variant_tasks.py
    hash: aa5db741fdf9571b7d5303d6e8418342fb67c09b810daa6fcd49fe880ce4a22c
sources_digest: 33d9d32ea1d5fa609a292a5ea0ac9f79b19672bb9f5a4a9782c765caff1466e1
links:
  - to: batch-slicing-workflow
    relation: uses
    description: >-
      batch_selection_consumer, batch_slice_dispatch, batch_slice_finalize drive
      the decoupled pipeline
  - to: short-drama-generation-channels
    relation: uses
    description: >-
      doubao_generate_task and seedance_generate_task invoke the two generation
      channels
  - to: variant-deduplication
    relation: uses
    description: >-
      generate_variants_task and verify_variant_fingerprint_task call
      variant_service
generator:
  version: 1
covers:
  - symbol: _load_shortdrama_prompt
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L32-L47'
  - symbol: _now_str
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L50-L51'
  - symbol: _update_doubao_prompt
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L58-L112'
  - symbol: _sync_doubao_video
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L115-L199'
  - symbol: _load_doubao_config
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L202-L213'
  - symbol: _check_doubao_cancelled
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L216-L221'
  - symbol: doubao_generate_task
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L225-L443'
  - symbol: _progress_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L266-L272'
  - symbol: _qrcode_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L275-L281'
  - symbol: _on_login_success
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L285-L291'
  - symbol: _screenshot_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L294-L298'
  - symbol: _account_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L301-L307'
  - symbol: _rewrite_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L310-L349'
  - symbol: _update_seedance_prompt
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L450-L487'
  - symbol: _load_seedance_db_config
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L490-L501'
  - symbol: _check_seedance_cancelled
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L504-L509'
  - symbol: _sync_generated_video
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L512-L598'
  - symbol: seedance_generate_task
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L602-L810'
  - symbol: _progress_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L668-L674'
  - symbol: run_async
    kind: function
    at: 'backend/app/celery/tasks.py:L137-L150'
  - symbol: _ensure_source_video
    kind: function
    at: 'backend/app/celery/tasks.py:L153-L166'
  - symbol: autoclip_task
    kind: function
    at: 'backend/app/celery/tasks.py:L170-L276'
  - symbol: batch_slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L280-L294'
  - symbol: batch_selection_consumer
    kind: function
    at: 'backend/app/celery/tasks.py:L298-L311'
  - symbol: batch_slice_dispatch
    kind: function
    at: 'backend/app/celery/tasks.py:L315-L326'
  - symbol: batch_slice_finalize
    kind: function
    at: 'backend/app/celery/tasks.py:L330-L341'
  - symbol: batch_aggregate
    kind: function
    at: 'backend/app/celery/tasks.py:L345-L353'
  - symbol: publish_schedule_dispatcher
    kind: function
    at: 'backend/app/celery/tasks.py:L357-L415'
  - symbol: _dispatch_due
    kind: function
    at: 'backend/app/celery/tasks.py:L368-L390'
  - symbol: _write_ckid
    kind: function
    at: 'backend/app/celery/tasks.py:L399-L407'
  - symbol: detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L419-L482'
  - symbol: _run
    kind: function
    at: 'backend/app/celery/tasks.py:L450-L451'
  - symbol: _create_detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L485-L507'
  - symbol: _update_detect_task_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L510-L524'
  - symbol: _fail_detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L527-L542'
  - symbol: slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L546-L818'
  - symbol: progress_cb
    kind: function
    at: 'backend/app/celery/tasks.py:L690-L695'
  - symbol: _parse_engine_manifest
    kind: function
    at: 'backend/app/celery/tasks.py:L821-L838'
  - symbol: _save_autoclip_results
    kind: function
    at: 'backend/app/celery/tasks.py:L841-L910'
  - symbol: _mark_autoclip_failed
    kind: function
    at: 'backend/app/celery/tasks.py:L913-L932'
  - symbol: _update_autoclip_run
    kind: function
    at: 'backend/app/celery/tasks.py:L935-L995'
  - symbol: _save_detected_intervals
    kind: function
    at: 'backend/app/celery/tasks.py:L998-L1064'
  - symbol: _update_episode_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1067-L1080'
  - symbol: _update_slice_task_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L1083-L1099'
  - symbol: _save_slice_outputs
    kind: function
    at: 'backend/app/celery/tasks.py:L1102-L1210'
  - symbol: _fail_slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L1213-L1230'
  - symbol: task_publish_video
    kind: function
    at: 'backend/app/celery/tasks.py:L1234-L1469'
  - symbol: _release_confirm_lock
    kind: function
    at: 'backend/app/celery/tasks.py:L1472-L1488'
  - symbol: _release
    kind: function
    at: 'backend/app/celery/tasks.py:L1479-L1484'
  - symbol: confirm_publish_worker
    kind: function
    at: 'backend/app/celery/tasks.py:L1492-L1596'
  - symbol: _acquire_lock
    kind: function
    at: 'backend/app/celery/tasks.py:L1503-L1508'
  - symbol: check_cookie_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1600-L1664'
  - symbol: sync_multi_operator_profiles
    kind: function
    at: 'backend/app/celery/tasks.py:L1668-L1684'
  - symbol: watch_multi_operator_routes
    kind: function
    at: 'backend/app/celery/tasks.py:L1688-L1704'
  - symbol: task_collect_metrics
    kind: function
    at: 'backend/app/celery/tasks.py:L1708-L1734'
  - symbol: gen_publish_trace_id
    kind: function
    at: 'backend/app/celery/tasks.py:L1737-L1740'
  - symbol: _get_publish_rate_config
    kind: function
    at: 'backend/app/celery/tasks.py:L1754-L1775'
  - symbol: _get_publish_task
    kind: function
    at: 'backend/app/celery/tasks.py:L1778-L1883'
  - symbol: _download_video_for_publish
    kind: function
    at: 'backend/app/celery/tasks.py:L1886-L1954'
  - symbol: _update_publish_task_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1957-L2007'
  - symbol: _compute_funnel_snapshot
    kind: function
    at: 'backend/app/celery/tasks.py:L2010-L2096'
  - symbol: run_alert_check_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2100-L2110'
  - symbol: maintenance_daily_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2114-L2131'
  - symbol: _update_watermark_video
    kind: function
    at: 'backend/app/celery/tasks.py:L2138-L2181'
  - symbol: _recalc_watermark_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2184-L2239'
  - symbol: watermark_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2243-L2460'
  - symbol: _load_videos
    kind: function
    at: 'backend/app/celery/tasks.py:L2267-L2281'
  - symbol: _mark_task_running
    kind: function
    at: 'backend/app/celery/tasks.py:L2292-L2301'
  - symbol: _persist_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L2355-L2358'
  - symbol: _cb
    kind: function
    at: 'backend/app/celery/tasks.py:L2360-L2375'
  - symbol: generate_variants_task
    kind: function
    at: 'backend/app/celery/variant_tasks.py:L21-L57'
  - symbol: verify_variant_fingerprint_task
    kind: function
    at: 'backend/app/celery/variant_tasks.py:L61-L63'
---
<!-- context:generated:start -->
## Summary

Central Celery app with Redis broker/backend, explicit queue routing (selection vs video_processing) to isolate heavy workloads, and beat schedules. Uses per-thread event loop via run_async to avoid asyncpg loop-binding. Notable gotchas: never call update_state(state='FAILURE') before returning a dict (Celery misinterprets as exception), use `is not None` instead of `or` for falsy config values, and clean up source videos in finally blocks.

## Related

- uses [[batch-slicing-workflow]] — batch_selection_consumer, batch_slice_dispatch, batch_slice_finalize drive the decoupled pipeline
- uses [[short-drama-generation-channels]] — doubao_generate_task and seedance_generate_task invoke the two generation channels
- uses [[variant-deduplication]] — generate_variants_task and verify_variant_fingerprint_task call variant_service
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
