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
    at: 'backend/app/celery/shortdrama_tasks.py:L32-L44'
  - symbol: _now_str
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L47-L48'
  - symbol: _update_doubao_prompt
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L55-L107'
  - symbol: _sync_doubao_video
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L110-L191'
  - symbol: _load_doubao_config
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L194-L203'
  - symbol: _check_doubao_cancelled
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L206-L211'
  - symbol: doubao_generate_task
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L215-L433'
  - symbol: _progress_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L256-L262'
  - symbol: _qrcode_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L265-L271'
  - symbol: _on_login_success
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L275-L281'
  - symbol: _screenshot_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L284-L288'
  - symbol: _account_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L291-L297'
  - symbol: _rewrite_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L300-L339'
  - symbol: _update_seedance_prompt
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L440-L477'
  - symbol: _load_seedance_db_config
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L480-L489'
  - symbol: _check_seedance_cancelled
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L492-L497'
  - symbol: _sync_generated_video
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L500-L583'
  - symbol: seedance_generate_task
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L587-L792'
  - symbol: _progress_cb
    kind: function
    at: 'backend/app/celery/shortdrama_tasks.py:L653-L659'
  - symbol: run_async
    kind: function
    at: 'backend/app/celery/tasks.py:L130-L143'
  - symbol: _ensure_source_video
    kind: function
    at: 'backend/app/celery/tasks.py:L146-L159'
  - symbol: autoclip_task
    kind: function
    at: 'backend/app/celery/tasks.py:L163-L269'
  - symbol: batch_slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L273-L287'
  - symbol: batch_selection_consumer
    kind: function
    at: 'backend/app/celery/tasks.py:L291-L304'
  - symbol: batch_slice_dispatch
    kind: function
    at: 'backend/app/celery/tasks.py:L308-L319'
  - symbol: batch_slice_finalize
    kind: function
    at: 'backend/app/celery/tasks.py:L323-L334'
  - symbol: batch_aggregate
    kind: function
    at: 'backend/app/celery/tasks.py:L338-L346'
  - symbol: publish_schedule_dispatcher
    kind: function
    at: 'backend/app/celery/tasks.py:L350-L408'
  - symbol: _dispatch_due
    kind: function
    at: 'backend/app/celery/tasks.py:L361-L383'
  - symbol: _write_ckid
    kind: function
    at: 'backend/app/celery/tasks.py:L392-L400'
  - symbol: detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L412-L479'
  - symbol: _run
    kind: function
    at: 'backend/app/celery/tasks.py:L443-L444'
  - symbol: _create_detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L482-L504'
  - symbol: _update_detect_task_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L507-L521'
  - symbol: _fail_detect_task
    kind: function
    at: 'backend/app/celery/tasks.py:L524-L539'
  - symbol: slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L543-L819'
  - symbol: progress_cb
    kind: function
    at: 'backend/app/celery/tasks.py:L687-L692'
  - symbol: _parse_engine_manifest
    kind: function
    at: 'backend/app/celery/tasks.py:L822-L839'
  - symbol: _save_autoclip_results
    kind: function
    at: 'backend/app/celery/tasks.py:L842-L944'
  - symbol: _in_duration_range
    kind: function
    at: 'backend/app/celery/tasks.py:L865-L870'
  - symbol: _mark_autoclip_failed
    kind: function
    at: 'backend/app/celery/tasks.py:L947-L963'
  - symbol: _update_autoclip_run
    kind: function
    at: 'backend/app/celery/tasks.py:L966-L1026'
  - symbol: _save_detected_intervals
    kind: function
    at: 'backend/app/celery/tasks.py:L1029-L1095'
  - symbol: _update_episode_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1098-L1111'
  - symbol: _update_slice_task_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L1114-L1130'
  - symbol: _save_slice_outputs
    kind: function
    at: 'backend/app/celery/tasks.py:L1133-L1241'
  - symbol: _fail_slice_task
    kind: function
    at: 'backend/app/celery/tasks.py:L1244-L1261'
  - symbol: task_publish_video
    kind: function
    at: 'backend/app/celery/tasks.py:L1265-L1506'
  - symbol: _release_confirm_lock
    kind: function
    at: 'backend/app/celery/tasks.py:L1509-L1525'
  - symbol: _release
    kind: function
    at: 'backend/app/celery/tasks.py:L1516-L1521'
  - symbol: confirm_publish_worker
    kind: function
    at: 'backend/app/celery/tasks.py:L1529-L1635'
  - symbol: _acquire_lock
    kind: function
    at: 'backend/app/celery/tasks.py:L1540-L1545'
  - symbol: check_cookie_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1639-L1704'
  - symbol: sync_multi_operator_profiles
    kind: function
    at: 'backend/app/celery/tasks.py:L1708-L1725'
  - symbol: watch_multi_operator_routes
    kind: function
    at: 'backend/app/celery/tasks.py:L1729-L1746'
  - symbol: task_collect_metrics
    kind: function
    at: 'backend/app/celery/tasks.py:L1750-L1777'
  - symbol: gen_publish_trace_id
    kind: function
    at: 'backend/app/celery/tasks.py:L1780-L1783'
  - symbol: _get_publish_rate_config
    kind: function
    at: 'backend/app/celery/tasks.py:L1797-L1816'
  - symbol: _get_publish_task
    kind: function
    at: 'backend/app/celery/tasks.py:L1819-L1922'
  - symbol: _download_video_for_publish
    kind: function
    at: 'backend/app/celery/tasks.py:L1925-L1989'
  - symbol: _update_publish_task_status
    kind: function
    at: 'backend/app/celery/tasks.py:L1992-L2042'
  - symbol: _compute_funnel_snapshot
    kind: function
    at: 'backend/app/celery/tasks.py:L2045-L2131'
  - symbol: run_alert_check_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2135-L2146'
  - symbol: maintenance_daily_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2150-L2168'
  - symbol: _update_watermark_video
    kind: function
    at: 'backend/app/celery/tasks.py:L2175-L2218'
  - symbol: _recalc_watermark_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2221-L2276'
  - symbol: watermark_task
    kind: function
    at: 'backend/app/celery/tasks.py:L2280-L2493'
  - symbol: _load_videos
    kind: function
    at: 'backend/app/celery/tasks.py:L2304-L2314'
  - symbol: _mark_task_running
    kind: function
    at: 'backend/app/celery/tasks.py:L2325-L2334'
  - symbol: _persist_progress
    kind: function
    at: 'backend/app/celery/tasks.py:L2388-L2391'
  - symbol: _cb
    kind: function
    at: 'backend/app/celery/tasks.py:L2393-L2408'
  - symbol: generate_variants_task
    kind: function
    at: 'backend/app/celery/variant_tasks.py:L21-L45'
  - symbol: verify_variant_fingerprint_task
    kind: function
    at: 'backend/app/celery/variant_tasks.py:L49-L51'
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
