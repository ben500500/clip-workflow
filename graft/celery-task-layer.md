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
    at: 'backend/app/celery/shortdrama_tasks.py:L225-L452'
  - symbol: _progress_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L267-L273'
  - symbol: _qrcode_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L276-L282'
  - symbol: _on_login_success
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L286-L292'
  - symbol: _screenshot_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L295-L299'
  - symbol: _account_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L302-L308'
  - symbol: _rewrite_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L311-L350'
  - symbol: _update_seedance_prompt
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L459-L496'
  - symbol: _load_seedance_db_config
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L499-L510'
  - symbol: _check_seedance_cancelled
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L513-L518'
  - symbol: _sync_generated_video
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L521-L607'
  - symbol: seedance_generate_task
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L611-L828'
  - symbol: _progress_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L678-L684'
  - symbol: run_async
    kind: function
    at: 'backend/app/celery/tasks.py:L149-L162'
  - symbol: _ensure_source_video
    kind: function
    at: 'backend/app/celery/tasks.py:L165-L178'
  - symbol: autoclip_task
    kind: function
    at: 'backend/app/celery/tasks.py:L182-L305'
  - symbol: batch_slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L309-L323'
  - symbol: batch_selection_consumer
    kind: function
    at: 'backend/app/celery/tasks.py:L327-L340'
  - symbol: batch_slice_dispatch
    kind: function
    at: 'backend/app/celery/tasks.py:L344-L355'
  - symbol: batch_slice_finalize
    kind: function
    at: 'backend/app/celery/tasks.py:L359-L370'
  - symbol: batch_aggregate
    kind: function
    at: 'backend/app/celery/tasks.py:L374-L382'
  - symbol: publish_schedule_dispatcher
    kind: function
    at: 'backend/app/celery/tasks.py:L386-L444'
  - symbol: _dispatch_due
    kind: function
    at: 'backend/app/celery/tasks.py:L397-L419'
  - symbol: _write_ckid
    kind: function
    at: 'backend/app/celery/tasks.py:L428-L436'
  - symbol: detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L448-L511'
  - symbol: _run
    kind: function
    at: 'backend/app/celery/tasks.py:L479-L480'
  - symbol: _create_detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L514-L536'
  - symbol: _update_detect_task_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L539-L553'
  - symbol: _fail_detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L556-L571'
  - symbol: slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L575-L888'
  - symbol: progress_cb
    kind: function
    at: 'backend/app/celery/tasks.py:L746-L751'
  - symbol: _parse_engine_manifest
    kind: function
    at: 'backend/app/celery/tasks.py:L891-L908'
  - symbol: _save_autoclip_results
    kind: function
    at: 'backend/app/celery/tasks.py:L911-L994'
  - symbol: _autoclip_auto_dispatch_slice
    kind: function
    at: 'backend/app/celery/tasks.py:L997-L1066'
  - symbol: _mark_autoclip_failed
    kind: function
    at: 'backend/app/celery/tasks.py:L1069-L1097'
  - symbol: _update_autoclip_run
    kind: function
    at: 'backend/app/celery/tasks.py:L1100-L1160'
  - symbol: _save_detected_intervals
    kind: function
    at: 'backend/app/celery/tasks.py:L1163-L1229'
  - symbol: _update_episode_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1232-L1245'
  - symbol: _update_slice_task_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L1248-L1264'
  - symbol: _save_slice_outputs
    kind: function
    at: 'backend/app/celery/tasks.py:L1267-L1375'
  - symbol: _fail_slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L1378-L1395'
  - symbol: task_publish_video
    kind: function
    at: 'backend/app/celery/tasks.py:L1399-L1634'
  - symbol: _release_confirm_lock
    kind: function
    at: 'backend/app/celery/tasks.py:L1637-L1653'
  - symbol: _release
    kind: function
    at: 'backend/app/celery/tasks.py:L1644-L1649'
  - symbol: confirm_publish_worker
    kind: function
    at: 'backend/app/celery/tasks.py:L1657-L1761'
  - symbol: _acquire_lock
    kind: function
    at: 'backend/app/celery/tasks.py:L1668-L1673'
  - symbol: check_cookie_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1765-L1829'
  - symbol: sync_multi_operator_profiles
    kind: function
    at: 'backend/app/celery/tasks.py:L1833-L1849'
  - symbol: watch_multi_operator_routes
    kind: function
    at: 'backend/app/celery/tasks.py:L1853-L1869'
  - symbol: task_collect_metrics
    kind: function
    at: 'backend/app/celery/tasks.py:L1873-L1899'
  - symbol: gen_publish_trace_id
    kind: function
    at: 'backend/app/celery/tasks.py:L1902-L1905'
  - symbol: _get_publish_rate_config
    kind: function
    at: 'backend/app/celery/tasks.py:L1919-L1940'
  - symbol: _get_publish_task
    kind: function
    at: 'backend/app/celery/tasks.py:L1943-L2048'
  - symbol: _download_video_for_publish
    kind: function
    at: 'backend/app/celery/tasks.py:L2051-L2119'
  - symbol: _update_publish_task_status
    kind: function
    at: 'backend/app/celery/tasks.py:L2122-L2172'
  - symbol: _compute_funnel_snapshot
    kind: function
    at: 'backend/app/celery/tasks.py:L2175-L2261'
  - symbol: run_alert_check_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2265-L2275'
  - symbol: maintenance_daily_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2279-L2296'
  - symbol: _update_watermark_video
    kind: function
    at: 'backend/app/celery/tasks.py:L2303-L2346'
  - symbol: _recalc_watermark_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2349-L2404'
  - symbol: watermark_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2408-L2625'
  - symbol: _load_videos
    kind: function
    at: 'backend/app/celery/tasks.py:L2432-L2446'
  - symbol: _mark_task_running
    kind: function
    at: 'backend/app/celery/tasks.py:L2457-L2466'
  - symbol: _persist_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L2520-L2523'
  - symbol: _cb
    kind: function
    at: 'backend/app/celery/tasks.py:L2525-L2540'
  - symbol: generate_variants_task
    kind: function
    at: 'backend/app/celery/variant_tasks.py:L21-L67'
  - symbol: verify_variant_fingerprint_task
    kind: function
    at: 'backend/app/celery/variant_tasks.py:L71-L73'
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
