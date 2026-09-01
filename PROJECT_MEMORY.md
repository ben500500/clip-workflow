# 项目记忆 · clip-workflow

> 用途：作为 **主 Agent / 开发 / 审阅** 的**单一事实记忆源**，记录项目当前真实状态、演进轨迹、健康度与技术债。
> 定位：**精简 · 高频更新 · 供 Agent 快速对齐**。详细功能描述请参考 `PROJECT.md`（大而全），本文件负责「现在是什么样、哪里在烂、下一步改哪里」。
>
> 记忆基线：`34a88cd`（2026-08-12，main）｜ 最近一次梳理：2026-08-12

---

## 0. 一句话认知

**短剧切片分发自动化平台**：覆盖「上传 → AI 选点(AutoClip) → 通用区间检测 → 多平台去重切片 → RPA 自动发布 → IAA 数据看板」全链路，外加 **短片制作**（去水印 / Seedance 提示词 / 豆包出片 / 发布素材）与 **分布式切片 Worker（Go）** 扩展。

---

## ⛔ 0.5 用户冻结项：RPA（163 的 clip-rpa-worker）—— 不许动

> **用户明确指示（2026-09-01）：RPA 现在不用，先放着；直到用户以后明确说「启用 RPA」才允许动它。**
> 在此之前，**任何 Agent / 任何人不得重启、重建、修复、删除、改动 rpa 相关容器/镜像/profile/配置**（包括顺手清理、健康检查修复等）。

**背景（为什么是冻结状态）**：
- 2026-09-01 做垃圾清理时，按当时建议重启了 163 的 `clip-rpa-worker` 以释放 /tmp 被占用文件，**导致其 chromium 的 CDP 端口（9227）不再响应 HTTP，容器 unhealthy**。
- 排查过：多次重启 / 清 profile 缓存 / 重建 profile / 重建 rpa 镜像均复现；chromium 日志报 "DevTools listening" 但 HTTP 空响应，怀疑 `cdp_proxy` 与 chrome 同绑 9227（profiles.json `listen_port==target_port==9227`）的端口冲突，属组件级配置问题，未深入修。
- 旧发布账号 profile 已备份在 163 卷 `clip-workflow_chrome_profiles`：`29033bb6-corrupt-20260901.bak`（登录态在其中，如需恢复登录可从这里找）。

**解除冻结的条件**：用户明确说「启用 RPA / 修 RPA」后才处理；届时优先查 cdp_proxy 端口冲突 + 恢复/重建 profile 登录态。

---

## 1. 真实规模（实测，勿信旧文档）

| 维度 | 数值 | 备注 |
|------|------|------|
| 代码总量 | **≈ 5.6 万行** | Python 34,400 / TS+TSX 16,861 / Go 3,634 / Shell 1,763 |
| API 模块 | 19 个 | `backend/app/api/` |
| Service 层 | 17 个 | `backend/app/services/` |
| ORM 模型 | 36 个 | `backend/app/models/models.py` |
| 前端页面 | 29 个 | `frontend/src/pages/` |
| Celery 任务 | 5+ 个 | `backend/app/celery/tasks.py` |
| Alembic 迁移 | 10 个 | `alembic/versions/` |
| Docker 服务 | 15 个 | `docker-compose.yml`（含 ollama 新增） |
| Git 提交 | 293 个 | 无 tag（建议补版本 tag） |

---

## 2. 架构速记（四条端到端链路）

1. **导入→切片→预览**：上传 → `slice:outputs` 队列 → **Go slice-worker**（Redis Stream `XReadGroup`）→ 直传 MinIO → presigned 播放
2. **去水印**：`POST /api/watermark/run` → Celery `watermark_runner.py` 四路分发（`remove_mask`/`seedance`/`seedance_wm`/RAiW）
3. **AI 选点**：`autoclip_task` → `autoclip:8000/pipeline/run` → ASR + LLM → 写 `clip_candidates`
4. **发布**：`task_publish_video` → Playwright **CDP 连 `rpa_worker:9222`** → 截图审核 → 确认发布

**关键拓扑**：CNB = 主仓，GitHub = 备份仓，先推 CNB 再推 GitHub（`scripts/sync_remotes.sh`）。cnb remote URL **必须内联 access token**。

---

## 3. 模块演进时间线（记忆锚点）

| 阶段 | 功能 | 入口模块 |
|------|------|---------|
| 一期 | 上传 / 素材 / AutoClip / 区间检测 / 切片 / 看板 MVP | `api/{projects,upload,autoclip,intervals,slice,dashboard}` |
| 二期 | RPA 发布 / IAA 看板 / 分布式切片 / 智能导入 / JWT+RBAC / Alembic | `api/{publish,dashboard,workers}`、`services/redis_stream.py` |
| 三期 | 监控告警 / 运维优化 / GPU 编码 / 竖屏转横屏 | `api/{monitor,maintenance}` |
| V4/V5 | **去水印** 任务 + 四套引擎 | `api/watermark.py`、`engines/watermark_runner.py`、`engines/seedance_wm_runner.py` |
| V6 | **Seedance 提示词生成**（三版本）+ 豆包 RPA 出片 + Seedance 官方 API 直连 | `api/shortdrama.py`、`services/{doubao_service,ark_client}.py` |
| V7 | **短剧发布素材** 生成 | `api/publish_material.py` |
| V8-V14 | remove_mask ROI 经验库 / 四角检测 / 自动水印分析 / 模板可编辑 | `engines/remove_mask_{remover,rois}.py` |
| 最新 | **批量切片工作流** + 一键切片接入 AI 选点/区间检测 + 切片配置预设 | `api/batch_slice.py`、`services/batch_slice_service.py` |
| 本次 | **源字幕打码配置简化 + 回归自动化**：subtitle-mask 把 temporal/spatial 两个独立开关收敛为 自动/精细/快速 三档预设（`preset` 字段，向后兼容旧字段）；新增源字幕打码回归测试 `engines/tests/test_subtitle_mask_regression.py`（验收指标：动态打码区≤9%屏高、源字幕文字密度下降≥60%），并接入 `.cnb.yml` push/PR 流水线（docker.build 预装 ffmpeg/opencv/numpy，缺依赖自动跳过不误报） | `engines/slice.py`（preset 解析）、`backend/app/api/slice.py`（`subtitle_mask_preset` 字段 + `_build_subtitle_mask_config`）、前端 `EpisodeDetail.tsx`/`BatchSlice.tsx`/`SliceTasks.tsx`/`api/slice.ts`/`utils/sliceConfigTooltip.ts`（三档预设下拉）、新增 `engines/tests/{test_subtitle_mask_regression.py,Dockerfile}`、`.cnb.yml` |
| 本次 | **固定文字字体 B+C 方案**（fc-match 动态解析 + SC 单字体提取，根治"门"字） + **字幕间距/高度配置开放**（`subtitle_spacing` / 默认字号降为 0.22） + **字幕对齐源字幕打码区域**（`subtitle_align_mask`，默认开启：开启源字幕打码并检测到区域时 ASR 字幕默认位置对齐打码区域） + **字幕默认间距再缩小**（`SUBTITLE_SPACING` -1→-2） | `engines/slice.py`、`api/slice.py`、`services/slice_service.py`、`celery/tasks.py`、`batch_slice_service.py`、`slice-worker/{redis_client,task_executor}.go`、前端 2 文件、`alembic/0025` |
| 本次 | **视频号多运营者发布 Phase 0**（方案 v3.1：账号归属 + RBAC 过滤 + Batch 模型 + 路由表/Lua 配额/CDP token 后端基础） | `models/models.py`（`created_by/operator_id`/`tier` 等 + `PublishBatch`）、`api/publish.py`（RBAC 过滤 + 批次 assign 端点）、`services/multi_operator.py`（新增：路由表 + Lua 原子配额 + 端口池 + 幂等 pending + cdp token）、`alembic/0027` |
| 本次 | **视频号多运营者发布 Phase 1（方案 A 浏览器层）**：CDP 端口收敛 + 多 profile 端口映射 + 路由表秒级失效闭环（R12）+ 幂等重填外移 Redis（R13/R18）+ cdp_proxy token 鉴权（R19）+ 配额双闸门接线（R22） | `publish_service.py`（cdp_url/token 注入 + Redis pending 幂等重填）、`celery/tasks.py`（发布/确认接入路由表端口+配额+token；新增 sync_multi_operator_profiles / watch_multi_operator_routes beat）、`multi_operator.py`（check_route_heartbeats + sync_profiles_from_db + get_profiles + freeze_pending）、`rpa/start_chromium.sh`（按 profile 起 N 个 Chromium）、`rpa/cdp_proxy.py`（多实例 + token 鉴权中间件）、`rpa/bootstrap.py`（新增：从 Redis 落盘 profiles）、`rpa/requirements.txt`、`docker-compose.yml`（rpa healthcheck） |
| 本次 | **视频号多运营者发布 P1（审计 + 可观测 + 前端端口矩阵看板）**：四类审计表（publish_audits/login_audits/cookie_access_logs/risk_events）+ 发布/确认/cookie 巡检链路写审计 + trace_id 串联 + 端口矩阵/审计查询端点 + 前端「运营者矩阵」&「审计日志」Tab | `models.py`（PublishAudit/LoginAudit/CookieAccessLog/RiskEvent）、`alembic/0028`、`services/audit_service.py`（新增：四类日志写 + trace_id 溯源）、`multi_operator.py`（get_route_matrix/get_operator_stats）、`celery/tasks.py`（publish/confirm/cookie 审计 + gen_publish_trace_id + _get_publish_task 补 profile_id/port/actor_id）、`api/publish.py`（matrix/operators/audit/trace 端点）、前端 `publish.ts` + `types` + `PublishManagement.tsx`（矩阵+审计 Tab） |
| 本次 | **接入 Graft 代码地图**：用 NanoNets/Graft（tree-sitter，零 LLM）为全仓生成 `graft/` 代码地图（227 文件 / 2115 符号 / 5589 边，Python+TS+Go 全保真），并接线 Claude Code（`.claude/skills/graft/SKILL.md` + `.mcp.json` MCP 工具）。**决策：提交可读 markdown 地图（`graft/**/*.md`）进 git 随代码同步**；仅 gitignore 可再生机器产物（`graft/.cache/`、`graft/.graph/`），队友 clone 后跑 `graft build` 重建。Agent 开新会话即自动读取代码地图，探索成本大幅下降（官方基准 tool-call -46% / token -42%） | `graft/`（markdown 代码地图）、`.claude/skills/graft/SKILL.md`、`.claude/helpers/{graft-hooks,graft-statusline}.cjs`、`.claude/settings.json`、`.mcp.json`、`.gitignore`、`.ignore` |
| 本次 | **修复 AI 选点"0 候选"根因（评分 JSON 解析失败静默归零）**：step3 评分 LLM（agnes-2.0-flash）偶尔把中文引号打成未转义的英文 `"`，导致 `parse_json_response` 兜底全部解析失败 → `_get_llm_evaluation` 把全部片段标 `final_score=0.0` → `/clips` 接口按 `min_score` 过滤成 0 候选。修复三层：① step3 评分解析失败不再静默标 0，改为重试（最多 3 次，复用 step2 已验证模式），重试时追加「严格 JSON」约束；仍失败则显式抛 `LLMCallError` 让流水线 failed（对应既有设计意图注释）。② `llm_client` 新增 `_escape_in_string_quotes` 状态机，在 JSON 兜底修复路径转义字符串内未转义 ASCII 引号（实测今晨失败响应可被直接修复成 6 个带真实分数的片段，无需重试）。③ 保持与 step2 一致，重试时强化提示词而非改基础 prompt。**教训：任何「LLM 解析失败 → 静默标 0/默认值」的降级都会在下游过滤成 0 结果，此类降级必须显式上浮或给中性保底分** | `autoclip/app/pipeline/step3_scoring.py`（`_get_llm_evaluation` 重试+显式上浮）、`autoclip/app/utils/llm_client.py`（`_escape_in_string_quotes` + `fix_common_json_errors` step 8） |
| 本次 | **三端统一（40/163/cnb）+ 40 MinIO presigned 配置修复**：① 把 40 生产 autoclip 容器里的本地定制 `speech_recognizer.py` 合并进 cnb（`3f5b999`）——**MiMo ASR**（`mimo-v2.5-asr`，`tp-` key 走 token-plan-cn / `sk-` 走 api.xiaomimimo.com）+ **FunASR GPU 加速**（cuda 可用则 cuda:0，否则回退 cpu）+ `_strip_funasr_tags` 去语言/情感标签 + `generate_subtitle_file` 全方法映射，消除「容器=定制、磁盘=旧、cnb=标准」三方不一致（重建镜像不再丢功能）；② **40 切片"结束但没出片"根因**：`.env` 的 `MINIO_EXTERNAL_ENDPOINT=localhost:9000`，后端容器内连不上 → presigned URL 生成失败 → 前端拿不到可播放地址（产物其实已上传成功），改为 `192.168.1.40:9000`（compose 已发布 9000，LAN 浏览器可达）后恢复；③ 40/163 均用 `deploy_server.sh` 重建 backend 系 + autoclip，磁盘源码与容器代码全部对齐 cnb（md5 逐一核验）。**坑：40 后端/autoclip 代码烤镜像，改码必须重建或 docker cp；.env 改动须 `up -d --force-recreate`** | `autoclip/app/utils/speech_recognizer.py`（合并 MiMo/GPU 定制）、40 `.env`（`MINIO_EXTERNAL_ENDPOINT=192.168.1.40:9000`）、`scripts/deploy_server.sh`（40 部署用 `DEPLOY_REMOTE_HOST=192.168.1.40 DEPLOY_REMOTE_USER=benny DEPLOY_REMOTE_DIR=/home/benny/clip-workflow DEPLOY_SSH_OPTS="-i ~/.ssh/id_ed25519"`） |

> 注意：短片制作（去水印/提示词/发布素材）演进到 **V14**，`PROJECT.md` 的 `/watermark` 页说明已很臃肿，建议后续拆分独立文档。

---

## 4. 健康度体检（2026-08-12）

### 4.1 已修复（相对 `docs/reviews/CODE_REVIEW_REPORT.md` 08-10 基线）

| 高危项 | 状态 | 证据 |
|--------|------|------|
| **100 端点零鉴权（H2）** | ✅ 已修复 | `main.py:197` 业务路由统一 `dependencies=[Depends(get_current_user)]`；auth/worker 回调走独立 router |
| **运行中任务误认领双副本（P0）** | ✅ 已修复 | `f051235` leaseRenewal 租约续期 |
| **删除剧集资源残留** | ✅ 已修复 | `d2ca901` |

> ⚠️ **审查文档已过时**：`docs/reviews/` 的 `CODE_REVIEW_REPORT.md` / `FIX_PLAN.md` 基于 08-10 基线，其 H2（鉴权）、H1（CDP 9222）、H3（种子弱口令）等项需**复核后再信任**，勿直接照抄。

### 4.2 仍待关注（技术债 / 风险）

| 项 | 说明 | 建议 |
|----|------|------|
| 文档漂移 | `docs/README.md` **已重写**（2026-08-12，AUTH_AUDIT 一并补充）；`PROJECT.md` 的 `/watermark` 页说明臃肿 | 后续可拆分短片制作独立文档 |
| 鉴权覆盖面复核 | **已完成**（2026-08-12）→ `docs/reviews/AUTH_AUDIT.md`：17 业务 router 统一鉴权，worker/auth 独立鉴权，遗留仅 heartbeat/WS 低风险项 | 无需再核，以 AUTH_AUDIT.md 为准 |
| 数据库索引 | 审查曾报「一行 SQL 致全库 0 索引」，`init.sql` 错误已删 + `migrations/fix_missing_indexes.sql` 存量补丁 + alembic 22 个迁移 | 存量库执行补丁脚本 |
| 单 Celery worker 串行 | **已修复**：拆分为 `worker-video`/`worker-publish`/`worker-fast`（分别消费 video_processing/publish/metrics,default） | - |
| 版本管理 | **已补 tag**：`v3.0.0`（三期方案完成里程碑） | 后续里程碑继续递增 |

### 4.3 健康度评分（示意）

- **可维护性** ★★★☆☆：分层清晰，但 `models.py`（36 模型单文件）、`slice-worker/main.go` 多文件 Go、`PROJECT.md` 巨型化是后续痛点
- **安全性** ★★★★☆：鉴权已接线，需复核边缘端点与 CDP 暴露
- **文档一致性** ★★★☆☆：README 已重写对齐真实结构；PROJECT.md 局部臃肿（`/watermark` 页）待后续拆分
- **测试覆盖** ★★☆☆☆→★★☆☆☆：新增 `engines/tests/test_subtitle_mask_regression.py` 源字幕打码回归测试（已在 CI 跑），`eval/` 有 LLM 评测；其余模块仍缺单元/集成测试

---

## 5. 维护机制（如何保持记忆新鲜）

### 5.1 更新契约
- **每次功能落地 / 修复**，同步更新本文件对应小节（时间线 / 健康度 / 架构变化）。
- `PROJECT.md`（详细文档）与 `CLAUDE.md`（Agent 上下文）与本记忆文件**三者同步维护**，避免再次漂移。

### 5.2 建议例行体检（可做成自动化/定时）
1. **文档漂移检查**：比对 `docs/README.md`、`PROJECT.md`、`CLAUDE.md` 与真实目录/路由/服务数。
2. **鉴权盲区扫描**：枚举 `include_router` 与各路由是否被 `get_current_user` 覆盖。
3. **规模健康线**：单文件（如 `models.py`、`main.py`）超阈值提示拆分。
4. **技术债看板**：将 `docs/reviews/FIX_PLAN.md` 12 项转为带状态的 Issue/清单，逐项核销。

### 5.3 约定
- 分支命名：`auto/*`（自动化分支）。主流程走 CNB PR，勿往 GitHub 提 PR。
- 认证：cnb token 必须内联 URL；`.env*` 一律不提交。
- 提交信息：Conventional Commits（`feat:`/`fix:`/`docs:`/`refactor:`）。

---

## 6. 快速定位索引（Agent 速查）

| 想做什么 | 去哪个文件 |
|---------|-----------|
| 理解全貌/功能 | `PROJECT.md` |
| Agent 上下文/约定 | `CLAUDE.md` |
| 业务路由注册/鉴权 | `backend/app/main.py`（L197 鉴权列表） |
| 全部表模型 | `backend/app/models/models.py`（36 模型） |
| Celery 任务 | `backend/app/celery/tasks.py` |
| 分布式切片 Worker | `slice-worker/*.go` |
| 去水印引擎分发 | `backend/app/engines/watermark_runner.py` |
| Seedance/豆包出片 | `backend/app/services/{ark_client,doubao_service}.py` |
| 批量切片工作流 | `backend/app/services/batch_slice_service.py` + `api/batch_slice.py` |
| 已知技术债 | `docs/reviews/CODE_REVIEW_REPORT.md`（需复核）+ 本文件 §4 |

---

> 本文档由 CodeBuddy 于 2026-08-12 首次建立，随项目迭代持续维护。
