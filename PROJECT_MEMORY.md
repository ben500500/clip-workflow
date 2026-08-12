# 项目记忆 · clip-workflow

> 用途：作为 **主 Agent / 开发 / 审阅** 的**单一事实记忆源**，记录项目当前真实状态、演进轨迹、健康度与技术债。
> 定位：**精简 · 高频更新 · 供 Agent 快速对齐**。详细功能描述请参考 `PROJECT.md`（大而全），本文件负责「现在是什么样、哪里在烂、下一步改哪里」。
>
> 记忆基线：`34a88cd`（2026-08-12，main）｜ 最近一次梳理：2026-08-12

---

## 0. 一句话认知

**短剧切片分发自动化平台**：覆盖「上传 → AI 选点(AutoClip) → 通用区间检测 → 多平台去重切片 → RPA 自动发布 → IAA 数据看板」全链路，外加 **短片制作**（去水印 / Seedance 提示词 / 豆包出片 / 发布素材）与 **分布式切片 Worker（Go）** 扩展。

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
- **测试覆盖** ★★☆☆☆：仅 `eval/` 有 LLM 评测，缺单元/集成测试

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
