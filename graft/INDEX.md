# graft — repo map

Small markdown nodes summarising this repo. `grep` any term, symbol, or
filename here, or run `graft ask "<task>"`. Each node carries prose plus exact
`file:line`; open a source file only to edit the named span.

The same graph is queryable as MCP tools (`graft_find_code`, `graft_find_all`,
`graft_trace_calls`, `graft_file_api`, `graft_repo_map`) where a host exposes them, and
as the `graft` CLI everywhere else. Edges — who calls what — live only in the
graph, not in these files: `graft callers <symbol>` is the only way to read them.

## Concepts

- [admin-user-management](admin-user-management.md) — Admin & User Management · frontend/src/pages/Settings.tsx, frontend/src/pages/UserManagement.tsx
- [alembic-migration-chain](alembic-migration-chain.md) — Alembic Migration Chain · alembic/env.py, alembic/versions/0001_initial.py, alembic/versions/0002_autoclip_runs.py, alembic/versions/0003_slice_task_vert2horiz.py, alembic/versions/0004_watermark.py, alembic/versions/0005_shortdrama_prompts.py, alembic/versions/0006_shortdrama_prompt_video.py, alembic/versions/0007_publish_materials.py, alembic/versions/0008_data_scope.py, alembic/versions/0009_prompt_versions.py, alembic/versions/0010_watermark_prompt_link.py, alembic/versions/0011_doubao_generation.py, alembic/versions/0012_prompt_default_duration.py, alembic/versions/0013_video_accounts_mini_programs.py, alembic/versions/0014_seedance_generate.py, alembic/versions/0015_doubao_progress.py, alembic/versions/0016_doubao_screenshot.py, alembic/versions/0017_doubao_account.py, alembic/versions/0018_slice_task_badges.py, alembic/versions/0019_slice_task_badge_default_width.py, alembic/versions/0020_slice_task_subtitle.py, alembic/versions/0021_slice_task_text_overlays.py, alembic/versions/0022_batch_item_detect_task.py, alembic/versions/0023_slice_task_subtitle_mask.py, alembic/versions/0024_user_preferences.py, alembic/versions/0025_slice_task_subtitle_align_mask.py, alembic/versions/0026_worker_node_encoder_capabilities.py, alembic/versions/0027_multi_operator_ownership.py, alembic/versions/0028_multi_operator_audit.py, alembic/versions/0029_wechat_download.py, alembic/versions/0030_publish_task_dead_letter.py, alembic/versions/0031_channel_accounts.py, alembic/versions/0032_channel_video_account_unique.py, alembic/versions/0033_publish_time_slots_scheduled_at.py, alembic/versions/0034_multi_video_dedup_variants.py, alembic/versions/0035_publish_profile_location.py, alembic/versions/0035_slice_task_cover_image.py, alembic/versions/0036_drama_management.py
- [audit-observability](audit-observability.md) — Audit & Observability · backend/app/models/audit.py, backend/app/models/monitor.py, backend/app/services/audit_service.py
- [auth-session-layer](auth-session-layer.md) — Auth & Session Layer · backend/app/auth.py, backend/app/models/user.py
- [authentication-profile](authentication-profile.md) — Authentication & Profile · frontend/src/pages/Login.tsx, frontend/src/pages/Profile.tsx
- [autoclip-integration](autoclip-integration.md) — AutoClip Integration · backend/app/services/autoclip_service.py
- [autoclip-llm-evaluation-harness](autoclip-llm-evaluation-harness.md) — AutoClip LLM evaluation harness · eval/grade_highlight_llm.py
- [autoclip-pipeline](autoclip-pipeline.md) — AutoClip Pipeline · autoclip/app/core/shared_config.py, autoclip/app/pipeline/step1_outline.py, autoclip/app/pipeline/step2_timeline.py, autoclip/app/pipeline/step3_scoring.py, autoclip/app/pipeline/step4_title.py
- [autoclip-pipeline-batch-slicing](autoclip-pipeline-batch-slicing.md) — AutoClip Pipeline & Batch Slicing · backend/app/api/autoclip.py, backend/app/api/batch_slice.py, backend/app/api/intervals.py
- [autoclip-service-entry](autoclip-service-entry.md) — AutoClip Service Entry · autoclip/app/celery_app.py, autoclip/app/main.py, autoclip/app/services/publish_material_generator.py, autoclip/app/services/script_optimizer.py
- [backend-app-factory-auth](backend-app-factory-auth.md) — Backend App Factory & Auth · backend/app/__init__.py, backend/app/api/auth.py
- [batch-slicing-workflow](batch-slicing-workflow.md) — Batch Slicing Workflow · backend/app/models/material.py, backend/app/services/batch_decoupled_service.py, backend/app/services/batch_slice_service.py
- [celery-task-layer](celery-task-layer.md) — Celery Task Layer · backend/app/celery/__init__.py, backend/app/celery/shortdrama_tasks.py, backend/app/celery/tasks.py, backend/app/celery/variant_tasks.py
- [channel-accounts-mini-programs](channel-accounts-mini-programs.md) — Channel Accounts & Mini Programs · backend/app/api/channel_accounts.py, backend/app/api/publish_mini_programs.py
- [configuration-database-bootstrap](configuration-database-bootstrap.md) — Configuration & Database Bootstrap · backend/app/config.py, backend/app/database.py
- [dashboard-analytics](dashboard-analytics.md) — Dashboard & Analytics · backend/app/api/dashboard.py
- [dashboard-analytics-pages](dashboard-analytics-pages.md) — Dashboard Analytics Pages · frontend/src/pages/DramaMonetization.tsx, frontend/src/pages/Ecosystem.tsx, frontend/src/pages/FunnelAnalysis.tsx, frontend/src/pages/ShortDramaAnalysis.tsx
- [dashboard-metrics-aggregation](dashboard-metrics-aggregation.md) — Dashboard & Metrics Aggregation · backend/app/models/dashboard.py, backend/app/services/dashboard_service.py, backend/app/services/data_import_service.py, backend/app/services/maintenance_service.py
- [data-import-template-workflow](data-import-template-workflow.md) — Data Import & Template Workflow · frontend/src/pages/DataImport.tsx
- [data-isolation-access-control](data-isolation-access-control.md) — Data Isolation & Access Control · backend/app/api/autoclip.py, backend/app/api/batch_slice.py, backend/app/api/channel_accounts.py, backend/app/api/intervals.py, backend/app/api/preview.py, backend/app/api/publications.py, backend/app/api/publish_video_accounts.py
- [data-isolation-rbac](data-isolation-rbac.md) — Data Isolation & RBAC · backend/app/database.py, backend/app/models/user.py, backend/app/services/data_scope.py
- [database-schema-migration-tooling](database-schema-migration-tooling.md) — Database Schema & Migration Tooling · init.sql, migrations/fix_missing_indexes.sql, scripts/db_sync_columns.py
- [dedupe-config-contract](dedupe-config-contract.md) — dedupe config contract · engines/slice.py, frontend/src/components/DedupeManualConfig.tsx
- [deployment-infrastructure](deployment-infrastructure.md) — Deployment & Infrastructure · deploy_remote_worker.sh, deploy.sh, deploy/cmd.sh, deploy/init.sql
- [deployment-ops-scripts](deployment-ops-scripts.md) — Deployment & Ops Scripts · scripts/cleanup_orphans.py, scripts/deploy_server.sh, scripts/healthcheck.sh, scripts/init_admin.sh, scripts/init.sh, scripts/logs.sh, scripts/restart.sh, scripts/server-setup.sh, scripts/start.sh, scripts/status.sh, scripts/stop.sh
- [docker-compose-stack-contract](docker-compose-stack-contract.md) — Docker Compose Stack Contract · scripts/logs.sh, scripts/restart.sh, scripts/server-setup.sh, scripts/start.sh, scripts/status.sh
- [drama-library-management](drama-library-management.md) — Drama Library Management · frontend/src/pages/DramaLibrary.tsx
- [drama-management-import](drama-management-import.md) — Drama Management & Import · backend/app/api/dramas.py
- [engine-execution-layer](engine-execution-layer.md) — Engine Execution Layer · backend/app/engines/__init__.py, backend/app/engines/watermark_runner.py, backend/app/services/interval_service.py
- [engine-update-versioning](engine-update-versioning.md) — Engine Update & Versioning · scripts/sync-engines-to-worker.sh, slice-worker/engine_update_test.go, slice-worker/engine_update.go
- [episode-slicing-control-panel](episode-slicing-control-panel.md) — Episode Slicing Control Panel · frontend/src/pages/EpisodeDetail.tsx
- [fastapi-application-wiring](fastapi-application-wiring.md) — FastAPI Application Wiring · backend/app/main.py
- [ffmpeg-utilities](ffmpeg-utilities.md) — FFmpeg Utilities · autoclip/app/utils/ffmpeg_utils.py
- [frame-analysis](frame-analysis.md) — Frame Analysis · autoclip/app/utils/frame_analyzer.py
- [frontend-api-layer](frontend-api-layer.md) — frontend API layer · frontend/src/api/auth.ts, frontend/src/api/autoclip.ts, frontend/src/api/batchSlice.ts, frontend/src/api/channelAccounts.ts, frontend/src/api/client.ts, frontend/src/api/config.ts, frontend/src/api/dashboard.ts, frontend/src/api/dramas.ts, frontend/src/api/intervals.ts, frontend/src/api/monitor.ts, frontend/src/api/preview.ts, frontend/src/api/projects.ts, frontend/src/api/publish.ts, frontend/src/api/publishMaterial.ts, frontend/src/api/shortdrama.ts, frontend/src/api/slice.ts, frontend/src/api/upload.ts, frontend/src/api/variants.ts, frontend/src/api/watermark.ts, frontend/src/api/wechatDl.ts
- [frontend-app-shell-routing](frontend-app-shell-routing.md) — frontend app shell & routing · frontend/src/App.tsx, frontend/src/components/AppLayout.tsx, frontend/src/main.tsx
- [frontend-auth-session](frontend-auth-session.md) — frontend auth & session · frontend/src/components/AppLayout.tsx, frontend/src/components/AuthGuard.tsx, frontend/src/contexts/AuthContext.tsx
- [frontend-build-dev-server](frontend-build-dev-server.md) — Frontend Build & Dev Server · frontend/vite.config.ts
- [frontend-dashboard-analytics-pages](frontend-dashboard-analytics-pages.md) — frontend dashboard & analytics pages · frontend/src/pages/ContentAnalysis.tsx, frontend/src/pages/Dashboard.tsx, frontend/src/pages/DashboardOverview.tsx, frontend/src/pages/DashboardSettings.tsx
- [frontend-reusable-ui-components](frontend-reusable-ui-components.md) — frontend reusable UI components · frontend/src/components/DedupeManualConfig.tsx, frontend/src/components/ErrorHint.tsx, frontend/src/components/ResizableTable.tsx
- [frontend-workflow-pages](frontend-workflow-pages.md) — frontend workflow pages · frontend/src/pages/BatchSlice.tsx, frontend/src/pages/ChannelAccounts.tsx, frontend/src/pages/ClipReview.tsx
- [git-remote-sync](git-remote-sync.md) — Git Remote Sync · scripts/sync_remotes.sh
- [interval-detection-management](interval-detection-management.md) — Interval Detection Management · frontend/src/pages/IntervalDetection.tsx
- [llm-manager-client-compatibility](llm-manager-client-compatibility.md) — LLM Manager & Client Compatibility · autoclip/app/utils/llm_client.py
- [llm-manager-providers](llm-manager-providers.md) — LLM Manager & Providers · autoclip/app/core/llm_manager.py, autoclip/app/core/llm_providers.py, autoclip/app/core/ollama_client.py
- [login-qr-self-service](login-qr-self-service.md) — Login QR Self-Service · backend/app/services/login_qr_service.py
- [maintenance-monitoring](maintenance-monitoring.md) — Maintenance & Monitoring · backend/app/api/maintenance.py, backend/app/api/monitor.py
- [maintenance-operations](maintenance-operations.md) — Maintenance Operations · frontend/src/pages/Maintenance.tsx
- [minio-storage-upload](minio-storage-upload.md) — MinIO Storage & Upload · backend/app/api/preview.py, backend/app/api/upload.py
- [monitoring-alerting-dashboard](monitoring-alerting-dashboard.md) — Monitoring & Alerting Dashboard · frontend/src/pages/Monitor.tsx
- [monitoring-alerting-service](monitoring-alerting-service.md) — Monitoring & Alerting Service · backend/app/services/monitor_service.py
- [multi-operator-rbac-audit](multi-operator-rbac-audit.md) — Multi-Operator RBAC & Audit · alembic/versions/0008_data_scope.py, alembic/versions/0027_multi_operator_ownership.py, alembic/versions/0028_multi_operator_audit.py, alembic/versions/0031_channel_accounts.py, alembic/versions/0032_channel_video_account_unique.py
- [multi-operator-routing-service](multi-operator-routing-service.md) — Multi-Operator Routing Service · backend/app/services/multi_operator.py
- [multi-video-dedup-fingerprinting](multi-video-dedup-fingerprinting.md) — Multi-Video Dedup & Fingerprinting · alembic/versions/0034_multi_video_dedup_variants.py
- [notfound-fallback](notfound-fallback.md) — NotFound Fallback · frontend/src/pages/NotFound.tsx
- [object-storage-service-minio](object-storage-service-minio.md) — Object Storage Service (MinIO) · backend/app/services/minio_service.py
- [orm-model-registry](orm-model-registry.md) — ORM Model Registry · backend/app/models/__init__.py, backend/app/models/audit.py, backend/app/models/channel.py, backend/app/models/dashboard.py, backend/app/models/drama.py, backend/app/models/material.py, backend/app/models/models.py, backend/app/models/monitor.py, backend/app/models/publish.py, backend/app/models/shortdrama.py, backend/app/models/variant.py
- [project-episode-management](project-episode-management.md) — Project & Episode Management · frontend/src/pages/ProjectDetail.tsx, frontend/src/pages/Projects.tsx
- [provider-fallback-chain](provider-fallback-chain.md) — Provider Fallback Chain · backend/wechat_download/preview_client.py, backend/wechat_download/provider_registry.py, backend/wechat_download/yuanbao_client.py
- [publish-api-facade](publish-api-facade.md) — Publish API Facade · backend/app/api/publish_common.py, backend/app/api/publish.py
- [publish-audit-login-qr](publish-audit-login-qr.md) — Publish Audit & Login QR · backend/app/api/publish_audit.py, backend/app/api/publish_login_qr.py
- [publish-material-generation](publish-material-generation.md) — Publish Material Generation · backend/app/api/publish_material.py
- [publish-materials-generation](publish-materials-generation.md) — Publish Materials Generation · frontend/src/pages/PublishMaterialTab.tsx
- [publish-profiles-video-accounts](publish-profiles-video-accounts.md) — Publish Profiles & Video Accounts · backend/app/api/publish_profiles.py, backend/app/api/publish_video_accounts.py
- [publish-tasks-scheduling](publish-tasks-scheduling.md) — Publish Tasks & Scheduling · backend/app/api/publish_batches.py, backend/app/api/publish_tasks.py, backend/app/api/publish_time_slots.py
- [publishing-video-account-matrix](publishing-video-account-matrix.md) — Publishing & Video Account Matrix · alembic/versions/0013_video_accounts_mini_programs.py, alembic/versions/0027_multi_operator_ownership.py, alembic/versions/0030_publish_task_dead_letter.py, alembic/versions/0031_channel_accounts.py, alembic/versions/0032_channel_video_account_unique.py, alembic/versions/0033_publish_time_slots_scheduled_at.py, alembic/versions/0035_publish_profile_location.py
- [publishing-workflow-management](publishing-workflow-management.md) — Publishing Workflow Management · frontend/src/pages/PublishManagement.tsx
- [qr-spike-validation](qr-spike-validation.md) — QR Spike Validation · scripts/qr_render_spike.py
- [redis-stream-service](redis-stream-service.md) — Redis Stream Service · backend/app/services/redis_stream.py
- [redis-streams-real-time-state](redis-streams-real-time-state.md) — Redis Streams & Real-time State · backend/app/api/workers.py, backend/app/services/batch_decoupled_service.py, backend/app/services/dashboard_service.py, backend/app/services/login_qr_service.py
- [redis-task-coordination-contract](redis-task-coordination-contract.md) — Redis Task Coordination Contract · slice-worker/redis_client.go, slice-worker/tray_common.go, slice-worker/tray.go
- [resumable-upload-service](resumable-upload-service.md) — Resumable Upload Service · backend/app/services/upload_service.py
- [rpa-multi-operator-container](rpa-multi-operator-container.md) — RPA Multi-Operator Container · rpa/bootstrap.py, rpa/cdp_proxy.py, rpa/start_chromium.sh
- [rpa-publishing-service](rpa-publishing-service.md) — RPA Publishing Service · backend/app/services/publish_service.py
- [rpa-route-table-chaos-validation](rpa-route-table-chaos-validation.md) — RPA Route Table & Chaos Validation · rpa/bootstrap.py, scripts/chaos_drill.py
- [seedance-prompt-generation](seedance-prompt-generation.md) — Seedance Prompt Generation · autoclip/app/services/seedance_prompt_generator.py, backend/app/api/shortdrama.py
- [seedance-wm-engine](seedance-wm-engine.md) — seedance_wm engine · engines/seedance_wm/log.py, engines/seedance_wm/mask.py, engines/seedance_wm/pipeline.py, engines/seedance_wm/remover.py, engines/seedance_wm/tools.py, engines/seedance_wm/version.py
- [seedance-wm-logging-convention](seedance-wm-logging-convention.md) — seedance_wm logging convention · engines/seedance_wm/log.py
- [seedance-wm-mask-generation](seedance-wm-mask-generation.md) — seedance_wm mask generation · engines/seedance_wm/mask.py
- [seedance-wm-resumability-state](seedance-wm-resumability-state.md) — seedance_wm resumability & state · engines/seedance_wm/pipeline.py
- [shared-backend-utilities](shared-backend-utilities.md) — Shared Backend Utilities · backend/app/utils/__init__.py, backend/app/utils/helpers.py
- [shared-frontend-types-formatting](shared-frontend-types-formatting.md) — Shared Frontend Types & Formatting · frontend/src/types/index.ts, frontend/src/utils/format.ts
- [short-drama-generation-channels](short-drama-generation-channels.md) — Short-Drama Generation Channels · backend/app/models/shortdrama.py, backend/app/services/ark_client.py, backend/app/services/doubao_service.py
- [short-drama-production-workflow](short-drama-production-workflow.md) — Short-Drama Production Workflow · alembic/versions/0004_watermark.py, alembic/versions/0005_shortdrama_prompts.py, alembic/versions/0006_shortdrama_prompt_video.py, alembic/versions/0007_publish_materials.py, alembic/versions/0009_prompt_versions.py, alembic/versions/0010_watermark_prompt_link.py, alembic/versions/0011_doubao_generation.py, alembic/versions/0012_prompt_default_duration.py, alembic/versions/0014_seedance_generate.py, alembic/versions/0015_doubao_progress.py, alembic/versions/0016_doubao_screenshot.py, alembic/versions/0017_doubao_account.py, frontend/src/pages/ShortDrama.tsx
- [slice-config-tooltip-watermark-styles](slice-config-tooltip-watermark-styles.md) — Slice Config Tooltip & Watermark Styles · frontend/src/utils/sliceConfigTooltip.ts, frontend/src/utils/watermarkStyles.ts
- [slice-configuration-presets](slice-configuration-presets.md) — Slice Configuration Presets · frontend/src/pages/EpisodeDetail.tsx, frontend/src/pages/ProjectDetail.tsx, frontend/src/pages/SliceTasks.tsx
- [slice-engine](slice-engine.md) — slice engine · engines/slice.py
- [slice-engine-orchestration](slice-engine-orchestration.md) — Slice Engine Orchestration · backend/app/services/slice_service.py
- [slice-task-config-persistence](slice-task-config-persistence.md) — Slice Task Config Persistence · alembic/versions/0003_slice_task_vert2horiz.py, alembic/versions/0018_slice_task_badges.py, alembic/versions/0019_slice_task_badge_default_width.py, alembic/versions/0020_slice_task_subtitle.py, alembic/versions/0021_slice_task_text_overlays.py, alembic/versions/0023_slice_task_subtitle_mask.py, alembic/versions/0024_user_preferences.py, alembic/versions/0025_slice_task_subtitle_align_mask.py, alembic/versions/0035_slice_task_cover_image.py
- [slice-tasks-output-management](slice-tasks-output-management.md) — Slice Tasks & Output Management · frontend/src/pages/OutputPreview.tsx, frontend/src/pages/SliceTasks.tsx
- [slice-worker-node](slice-worker-node.md) — Slice Worker Node · slice-worker/callback.go, slice-worker/config.go, slice-worker/engine_update_test.go, slice-worker/engine_update.go, slice-worker/exec_unix.go, slice-worker/exec_windows.go, slice-worker/file_transfer.go, slice-worker/heartbeat_backend.go, slice-worker/instance_lock.go, slice-worker/main.go, slice-worker/redis_client.go, slice-worker/task_executor.go, slice-worker/worker.go
- [smart-import-service](smart-import-service.md) — Smart Import Service · backend/app/services/smart_import_service.py
- [speech-recognition](speech-recognition.md) — Speech Recognition · autoclip/app/utils/speech_recognizer.py
- [subtitle-mask-regression-test](subtitle-mask-regression-test.md) — subtitle mask regression test · engines/tests/test_subtitle_mask_regression.py
- [system-config-platform-profiles](system-config-platform-profiles.md) — System Config & Platform Profiles · backend/app/api/config.py
- [text-processing-utilities](text-processing-utilities.md) — Text Processing Utilities · autoclip/app/utils/text_processor.py
- [variant-deduplication](variant-deduplication.md) — Variant Deduplication · backend/app/models/variant.py, backend/app/services/fingerprint_service.py
- [variant-generation-pipeline](variant-generation-pipeline.md) — Variant Generation Pipeline · backend/app/services/variant_service.py
- [variant-matrix-dedup-dashboard](variant-matrix-dedup-dashboard.md) — Variant Matrix Dedup Dashboard · frontend/src/pages/VariantMatrix.tsx
- [variant-matrix-deduplication](variant-matrix-deduplication.md) — Variant Matrix & Deduplication · backend/app/api/variants.py
- [vert2horiz-crop](vert2horiz-crop.md) — vert2horiz crop · engines/vert2horiz_crop.py
- [video-processing-engines](video-processing-engines.md) — Video Processing Engines · engines/detect_intervals.py, engines/preview.py, engines/remove_mask_remover.py, engines/remove_mask_rois.py, engines/seedance_watermark_remover.py, engines/seedance_wm_runner.py, engines/seedance_wm/__init__.py, engines/seedance_wm/__main__.py, engines/seedance_wm/agent.py, engines/seedance_wm/cli.py, engines/seedance_wm/config.py, engines/seedance_wm/detect.py, engines/seedance_wm/errors.py, engines/seedance_wm/ffmpeg_io.py, engines/seedance_wm/inpaint.py
- [video-slicing-pipeline](video-slicing-pipeline.md) — Video Slicing Pipeline · backend/app/api/projects.py, backend/app/api/slice_helpers.py, backend/app/api/slice.py
- [watermark-removal](watermark-removal.md) — Watermark Removal · backend/app/api/watermark.py
- [watermark-removal-degradation-chain](watermark-removal-degradation-chain.md) — Watermark Removal Degradation Chain · engines/remove_mask_remover.py, engines/remove_mask_rois.py, engines/seedance_wm/detect.py, engines/seedance_wm/errors.py, engines/seedance_wm/inpaint.py
- [watermark-removal-workflow](watermark-removal-workflow.md) — Watermark Removal Workflow · frontend/src/pages/Watermark.tsx
- [wechat-channels-resource-download](wechat-channels-resource-download.md) — WeChat Channels Resource Download · frontend/src/pages/ResourceDownload.tsx
- [wechat-download-drama-management](wechat-download-drama-management.md) — WeChat Download & Drama Management · alembic/versions/0029_wechat_download.py, alembic/versions/0036_drama_management.py
- [wechat-download-pipeline](wechat-download-pipeline.md) — WeChat Download Pipeline · backend/wechat_download/__init__.py, backend/wechat_download/api.py, backend/wechat_download/base.py, backend/wechat_download/downloader.py, backend/wechat_download/models.py, backend/wechat_download/preview_client.py, backend/wechat_download/provider_registry.py, backend/wechat_download/service.py, backend/wechat_download/tasks.py, backend/wechat_download/yuanbao_client.py
- [worker-node-management](worker-node-management.md) — Worker Node Management · frontend/src/pages/Workers.tsx
- [worker-node-management-engine-update](worker-node-management-engine-update.md) — Worker Node Management & Engine Update · backend/app/api/workers.py
- [worker-packaging-deployment](worker-packaging-deployment.md) — Worker Packaging & Deployment · slice-worker/macos/build_mac.sh, slice-worker/macos/launchd_worker.sh, slice-worker/macos/manage_worker.sh, slice-worker/ubuntu/build_package.sh, slice-worker/ubuntu/deploy_ubuntu.sh
- [worker-platform-abstractions](worker-platform-abstractions.md) — Worker Platform Abstractions · slice-worker/exec_unix.go, slice-worker/exec_windows.go, slice-worker/tray_common.go, slice-worker/tray_darwin_nocgo.go, slice-worker/tray_darwin.go, slice-worker/tray_other.go, slice-worker/tray_windows.go, slice-worker/tray.go, slice-worker/tui.go

## Files

328 per-file wiring cards mirror the source tree under `graft/` (292 carry extracted symbols). They are deliberately not enumerated here —
`grep` a symbol or `find`/`ls` a filename under `graft/` to land on the card for that file.
