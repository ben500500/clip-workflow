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
    at: 'backend/app/celery/tasks.py:L149-L162'
  - symbol: _ensure_source_video
    kind: function
    at: 'backend/app/celery/tasks.py:L165-L178'
  - symbol: autoclip_task
    kind: function
    at: 'backend/app/celery/tasks.py:L182-L288'
  - symbol: batch_slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L292-L306'
  - symbol: batch_selection_consumer
    kind: function
    at: 'backend/app/celery/tasks.py:L310-L323'
  - symbol: batch_slice_dispatch
    kind: function
    at: 'backend/app/celery/tasks.py:L327-L338'
  - symbol: batch_slice_finalize
    kind: function
    at: 'backend/app/celery/tasks.py:L342-L353'
  - symbol: batch_aggregate
    kind: function
    at: 'backend/app/celery/tasks.py:L357-L365'
  - symbol: publish_schedule_dispatcher
    kind: function
    at: 'backend/app/celery/tasks.py:L369-L427'
  - symbol: _dispatch_due
    kind: function
    at: 'backend/app/celery/tasks.py:L380-L402'
  - symbol: _write_ckid
    kind: function
    at: 'backend/app/celery/tasks.py:L411-L419'
  - symbol: detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L431-L494'
  - symbol: _run
    kind: function
    at: 'backend/app/celery/tasks.py:L462-L463'
  - symbol: _create_detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L497-L519'
  - symbol: _update_detect_task_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L522-L536'
  - symbol: _fail_detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L539-L554'
  - symbol: slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L558-L864'
  - symbol: progress_cb
    kind: function
    at: 'backend/app/celery/tasks.py:L724-L729'
  - symbol: _parse_engine_manifest
    kind: function
    at: 'backend/app/celery/tasks.py:L867-L884'
  - symbol: _save_autoclip_results
    kind: function
    at: 'backend/app/celery/tasks.py:L887-L957'
  - symbol: _mark_autoclip_failed
    kind: function
    at: 'backend/app/celery/tasks.py:L960-L979'
  - symbol: _update_autoclip_run
    kind: function
    at: 'backend/app/celery/tasks.py:L982-L1042'
  - symbol: _save_detected_intervals
    kind: function
    at: 'backend/app/celery/tasks.py:L1045-L1111'
  - symbol: _update_episode_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1114-L1127'
  - symbol: _update_slice_task_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L1130-L1146'
  - symbol: _save_slice_outputs
    kind: function
    at: 'backend/app/celery/tasks.py:L1149-L1257'
  - symbol: _fail_slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L1260-L1277'
  - symbol: task_publish_video
    kind: function
    at: 'backend/app/celery/tasks.py:L1281-L1516'
  - symbol: _release_confirm_lock
    kind: function
    at: 'backend/app/celery/tasks.py:L1519-L1535'
  - symbol: _release
    kind: function
    at: 'backend/app/celery/tasks.py:L1526-L1531'
  - symbol: confirm_publish_worker
    kind: function
    at: 'backend/app/celery/tasks.py:L1539-L1643'
  - symbol: _acquire_lock
    kind: function
    at: 'backend/app/celery/tasks.py:L1550-L1555'
  - symbol: check_cookie_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1647-L1711'
  - symbol: sync_multi_operator_profiles
    kind: function
    at: 'backend/app/celery/tasks.py:L1715-L1731'
  - symbol: watch_multi_operator_routes
    kind: function
    at: 'backend/app/celery/tasks.py:L1735-L1751'
  - symbol: task_collect_metrics
    kind: function
    at: 'backend/app/celery/tasks.py:L1755-L1781'
  - symbol: gen_publish_trace_id
    kind: function
    at: 'backend/app/celery/tasks.py:L1784-L1787'
  - symbol: _get_publish_rate_config
    kind: function
    at: 'backend/app/celery/tasks.py:L1801-L1822'
  - symbol: _get_publish_task
    kind: function
    at: 'backend/app/celery/tasks.py:L1825-L1930'
  - symbol: _download_video_for_publish
    kind: function
    at: 'backend/app/celery/tasks.py:L1933-L2001'
  - symbol: _update_publish_task_status
    kind: function
    at: 'backend/app/celery/tasks.py:L2004-L2054'
  - symbol: _compute_funnel_snapshot
    kind: function
    at: 'backend/app/celery/tasks.py:L2057-L2143'
  - symbol: run_alert_check_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2147-L2157'
  - symbol: maintenance_daily_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2161-L2178'
  - symbol: _update_watermark_video
    kind: function
    at: 'backend/app/celery/tasks.py:L2185-L2228'
  - symbol: _recalc_watermark_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2231-L2286'
  - symbol: watermark_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2290-L2507'
  - symbol: _load_videos
    kind: function
    at: 'backend/app/celery/tasks.py:L2314-L2328'
  - symbol: _mark_task_running
    kind: function
    at: 'backend/app/celery/tasks.py:L2339-L2348'
  - symbol: _persist_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L2402-L2405'
  - symbol: _cb
    kind: function
    at: 'backend/app/celery/tasks.py:L2407-L2422'
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
