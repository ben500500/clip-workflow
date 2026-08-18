# graft — repo map

Small markdown nodes summarising this repo. `grep` any term, symbol, or
filename here, or run `graft ask "<task>"`. Each node carries prose plus exact
`file:line`; open a source file only to edit the named span.

The same graph is queryable as MCP tools (`graft_find_code`, `graft_find_all`,
`graft_trace_calls`, `graft_file_api`, `graft_repo_map`) where a host exposes them, and
as the `graft` CLI everywhere else. Edges — who calls what — live only in the
graph, not in these files: `graft callers <symbol>` is the only way to read them.

## Concepts

- [alembic-migration-chain](alembic-migration-chain.md) — Alembic Migration Chain · alembic/env.py, alembic/versions/0001_initial.py, alembic/versions/0002_autoclip_runs.py, alembic/versions/0003_slice_task_vert2horiz.py, alembic/versions/0004_watermark.py, alembic/versions/0005_shortdrama_prompts.py, alembic/versions/0006_shortdrama_prompt_video.py, alembic/versions/0007_publish_materials.py, alembic/versions/0008_data_scope.py, alembic/versions/0009_prompt_versions.py, alembic/versions/0010_watermark_prompt_link.py, alembic/versions/0011_doubao_generation.py, alembic/versions/0012_prompt_default_duration.py, alembic/versions/0013_video_accounts_mini_programs.py, alembic/versions/0014_seedance_generate.py, alembic/versions/0015_doubao_progress.py, alembic/versions/0016_doubao_screenshot.py, alembic/versions/0017_doubao_account.py, alembic/versions/0018_slice_task_badges.py, alembic/versions/0019_slice_task_badge_default_width.py, alembic/versions/0020_slice_task_subtitle.py, alembic/versions/0021_slice_task_text_overlays.py, alembic/versions/0022_batch_item_detect_task.py, alembic/versions/0023_slice_task_subtitle_mask.py, alembic/versions/0024_user_preferences.py, alembic/versions/0025_slice_task_subtitle_align_mask.py, alembic/versions/0026_worker_node_encoder_capabilities.py, alembic/versions/0027_multi_operator_ownership.py, alembic/versions/0028_multi_operator_audit.py, alembic/versions/0029_wechat_download.py, alembic/versions/0030_publish_task_dead_letter.py, alembic/versions/0031_channel_accounts.py, alembic/versions/0032_channel_video_account_unique.py, alembic/versions/0033_publish_time_slots_scheduled_at.py, alembic/versions/0034_multi_video_dedup_variants.py
- [analytics-dashboard-pages](analytics-dashboard-pages.md) — Analytics Dashboard Pages · frontend/src/pages/ContentAnalysis.tsx, frontend/src/pages/DashboardOverview.tsx, frontend/src/pages/DashboardSettings.tsx, frontend/src/pages/DataImport.tsx, frontend/src/pages/DramaMonetization.tsx, frontend/src/pages/Ecosystem.tsx
- [analytics-dashboards](analytics-dashboards.md) — Analytics Dashboards · frontend/src/pages/FunnelAnalysis.tsx, frontend/src/pages/ShortDramaAnalysis.tsx
- [auth-session-management](auth-session-management.md) — Auth & Session Management · frontend/src/api/auth.ts, frontend/src/components/AuthGuard.tsx, frontend/src/contexts/AuthContext.tsx
- [auth-users-settings](auth-users-settings.md) — Auth, Users & Settings · frontend/src/pages/Login.tsx, frontend/src/pages/Profile.tsx, frontend/src/pages/ResourceDownload.tsx, frontend/src/pages/Settings.tsx, frontend/src/pages/UserManagement.tsx
- [autoclip-auxiliary-services](autoclip-auxiliary-services.md) — AutoClip Auxiliary Services · autoclip/app/services/publish_material_generator.py, autoclip/app/services/script_optimizer.py, autoclip/app/services/seedance_prompt_generator.py
- [autoclip-fastapi-service](autoclip-fastapi-service.md) — AutoClip FastAPI Service · autoclip/app/main.py
- [autoclip-pipeline-stages](autoclip-pipeline-stages.md) — AutoClip Pipeline Stages · autoclip/app/pipeline/step1_outline.py, autoclip/app/pipeline/step2_timeline.py, autoclip/app/pipeline/step3_scoring.py, autoclip/app/pipeline/step4_title.py
- [backend-utility-layer](backend-utility-layer.md) — Backend Utility Layer · backend/app/utils/__init__.py, backend/app/utils/helpers.py
- [celery-task-queue](celery-task-queue.md) — Celery Task Queue · autoclip/app/celery_app.py
- [clip-workflow-pages](clip-workflow-pages.md) — Clip Workflow Pages · frontend/src/pages/BatchSlice.tsx, frontend/src/pages/ChannelAccounts.tsx, frontend/src/pages/ClipReview.tsx, frontend/src/pages/Dashboard.tsx
- [database-schema-migrations](database-schema-migrations.md) — Database Schema & Migrations · init.sql, migrations/fix_missing_indexes.sql, scripts/db_sync_columns.py
- [deployment-operations](deployment-operations.md) — Deployment & Operations · deploy_remote_worker.sh, deploy.sh, deploy/cmd.sh, deploy/init.sql
- [deployment-ops-scripts](deployment-ops-scripts.md) — Deployment & Ops Scripts · scripts/deploy_server.sh, scripts/healthcheck.sh, scripts/init_admin.sh, scripts/init.sh, scripts/logs.sh, scripts/restart.sh, scripts/server-setup.sh
- [detection-mask-inpaint-pipeline](detection-mask-inpaint-pipeline.md) — Detection/Mask/Inpaint Pipeline · engines/seedance_wm/tools.py
- [episode-production-pipeline-pages](episode-production-pipeline-pages.md) — Episode Production Pipeline Pages · frontend/src/pages/EpisodeDetail.tsx, frontend/src/pages/IntervalDetection.tsx, frontend/src/pages/SliceTasks.tsx
- [face-aware-crop](face-aware-crop.md) — Face-Aware Crop · engines/vert2horiz_crop.py
- [ffmpeg-i-o-layer](ffmpeg-i-o-layer.md) — FFmpeg I/O Layer · engines/seedance_wm/remover.py, engines/seedance_wm/tools.py, engines/slice.py
- [ffmpeg-path-resolution](ffmpeg-path-resolution.md) — FFmpeg Path Resolution · autoclip/app/utils/ffmpeg_utils.py
- [frontend-api-client-layer](frontend-api-client-layer.md) — Frontend API Client Layer · frontend/src/api/auth.ts, frontend/src/api/autoclip.ts, frontend/src/api/batchSlice.ts, frontend/src/api/channelAccounts.ts, frontend/src/api/client.ts, frontend/src/api/config.ts, frontend/src/api/dashboard.ts, frontend/src/api/intervals.ts, frontend/src/api/monitor.ts, frontend/src/api/preview.ts, frontend/src/api/projects.ts, frontend/src/api/publish.ts, frontend/src/api/publishMaterial.ts, frontend/src/api/shortdrama.ts, frontend/src/api/slice.ts, frontend/src/api/upload.ts, frontend/src/api/variants.ts, frontend/src/api/watermark.ts, frontend/src/api/wechatDl.ts
- [frontend-api-layer](frontend-api-layer.md) — Frontend API Layer · frontend/src/types/index.ts, frontend/src/utils/format.ts, frontend/vite.config.ts
- [frontend-routing-shell](frontend-routing-shell.md) — Frontend Routing & Shell · frontend/src/App.tsx, frontend/src/components/AppLayout.tsx, frontend/src/main.tsx
- [frontend-shared-ui-components](frontend-shared-ui-components.md) — Frontend Shared UI Components · frontend/src/components/DedupeManualConfig.tsx, frontend/src/components/ErrorHint.tsx, frontend/src/components/ResizableTable.tsx
- [interval-detection-engine](interval-detection-engine.md) — Interval Detection Engine · engines/detect_intervals.py
- [llm-evaluation-harness](llm-evaluation-harness.md) — LLM Evaluation Harness · eval/grade_highlight_llm.py
- [llm-manager-provider-abstraction](llm-manager-provider-abstraction.md) — LLM Manager & Provider Abstraction · autoclip/app/core/llm_manager.py, autoclip/app/core/llm_providers.py, autoclip/app/core/ollama_client.py, autoclip/app/core/shared_config.py
- [minio-storage-service](minio-storage-service.md) — MinIO Storage Service · backend/app/services/minio_service.py
- [monitoring-maintenance-workers](monitoring-maintenance-workers.md) — Monitoring, Maintenance & Workers · frontend/src/pages/Maintenance.tsx, frontend/src/pages/Monitor.tsx, frontend/src/pages/Workers.tsx
- [opencv-watermark-remover](opencv-watermark-remover.md) — OpenCV Watermark Remover · engines/remove_mask_remover.py
- [preview-frame-extraction-engine](preview-frame-extraction-engine.md) — Preview Frame Extraction Engine · engines/preview.py
- [project-episode-management](project-episode-management.md) — Project & Episode Management · frontend/src/pages/ProjectDetail.tsx, frontend/src/pages/Projects.tsx
- [publishing-material-generation](publishing-material-generation.md) — Publishing Material Generation · frontend/src/pages/PublishMaterialTab.tsx
- [publishing-output-hub](publishing-output-hub.md) — Publishing & Output Hub · frontend/src/pages/OutputPreview.tsx, frontend/src/pages/PublishManagement.tsx
- [redis-stream-task-coordination](redis-stream-task-coordination.md) — Redis Stream Task Coordination · backend/app/services/redis_stream.py
- [resumable-upload-service](resumable-upload-service.md) — Resumable Upload Service · backend/app/services/upload_service.py
- [rpa-multi-operator-infrastructure](rpa-multi-operator-infrastructure.md) — RPA Multi-Operator Infrastructure · rpa/bootstrap.py, rpa/cdp_proxy.py, rpa/start_chromium.sh, scripts/chaos_drill.py
- [seedance-watermark-removal-engine](seedance-watermark-removal-engine.md) — Seedance Watermark Removal Engine · engines/seedance_wm_runner.py, engines/seedance_wm/__init__.py, engines/seedance_wm/__main__.py, engines/seedance_wm/agent.py, engines/seedance_wm/cli.py, engines/seedance_wm/config.py, engines/seedance_wm/detect.py, engines/seedance_wm/errors.py, engines/seedance_wm/ffmpeg_io.py, engines/seedance_wm/inpaint.py, engines/seedance_wm/log.py, engines/seedance_wm/mask.py, engines/seedance_wm/pipeline.py, engines/seedance_wm/remover.py, engines/seedance_wm/tools.py, engines/seedance_wm/version.py
- [short-drama-generation-workflow](short-drama-generation-workflow.md) — Short-Drama Generation Workflow · frontend/src/pages/ShortDrama.tsx, frontend/src/pages/Watermark.tsx
- [slice-configuration-presets](slice-configuration-presets.md) — Slice Configuration & Presets · frontend/src/pages/EpisodeDetail.tsx, frontend/src/pages/Settings.tsx, frontend/src/pages/SliceTasks.tsx, frontend/src/utils/sliceConfigTooltip.ts, frontend/src/utils/watermarkStyles.ts
- [slice-engine-orchestration](slice-engine-orchestration.md) — Slice Engine Orchestration · backend/app/services/slice_service.py
- [slicing-engine](slicing-engine.md) — Slicing Engine · engines/slice.py
- [smart-import-service](smart-import-service.md) — Smart Import Service · backend/app/services/smart_import_service.py
- [storage-cleanup-orphan-reclamation](storage-cleanup-orphan-reclamation.md) — Storage Cleanup & Orphan Reclamation · scripts/cleanup_orphans.py, scripts/qr_render_spike.py
- [subtitle-mask-regression](subtitle-mask-regression.md) — Subtitle Mask Regression · engines/tests/test_subtitle_mask_regression.py
- [variant-generation-pipeline](variant-generation-pipeline.md) — Variant Generation Pipeline · backend/app/services/variant_service.py
- [variant-matrix-dedupe-verification](variant-matrix-dedupe-verification.md) — Variant Matrix & Dedupe Verification · frontend/src/pages/VariantMatrix.tsx
- [video-publishing-pipeline](video-publishing-pipeline.md) — Video Publishing Pipeline · backend/app/services/publish_service.py
- [watermark-removal-roi-library](watermark-removal-roi-library.md) — Watermark Removal ROI Library · engines/remove_mask_rois.py
- [wechat-download-pipeline](wechat-download-pipeline.md) — WeChat Download Pipeline · backend/wechat_download/__init__.py, backend/wechat_download/api.py, backend/wechat_download/base.py, backend/wechat_download/downloader.py, backend/wechat_download/models.py, backend/wechat_download/preview_client.py, backend/wechat_download/provider_registry.py, backend/wechat_download/service.py, backend/wechat_download/tasks.py, backend/wechat_download/yuanbao_client.py

## Files

261 per-file wiring cards mirror the source tree under `graft/` (231 carry extracted symbols). They are deliberately not enumerated here —
`grep` a symbol or `find`/`ls` a filename under `graft/` to land on the card for that file.
