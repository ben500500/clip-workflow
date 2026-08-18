# clip-workflow 代码审查报告

> 审查方式：graft 代码地图优先（graft build 刷新至 HEAD 3d807d1，2724 节点 / 6646 边 / 269 卡片），只读审查，未修改任何业务代码。

## 1. 结论摘要

1. **P1：Celery 失败序列化二次异常是"真 bug 假日志"**——`tasks.py` 至少 7 个任务在 `update_state(state="FAILURE")` 后 `raise`/`return`，与 `shortdrama_tasks.py` 里已注释确认的 Celery 6 缺陷完全同款，部署日志反复出现 `ValueError: Exception information must include the exception type` / `exc_type KeyError`，真实错误被掩盖。
2. **P1：`tasks.py` 已是上帝对象**（2532 行，20+ 任务混 5 类职责），`slice_task` 签名膨胀到 20+ 参数，是本次部署连环出问题的结构性来源。
3. **P2：`workflow-status` 是确凿死代码**——后端 184 行端点（`projects.py` L607-791）与前端 API 封装（`projects.ts` L52）均为 0 调用，四类引用（路由/前端页面/celery/调用边）全空。
4. **P2：切片配置体系三处各维护一套**（`EpisodeDetail.tsx` / `BatchSlice.tsx` / `ProjectDetail.tsx`），预设、持久化、payload 组装各自实现，改一处漏两处。
5. **P2：巨型文件集中**——`EpisodeDetail.tsx` 3034 行、`BatchSlice.tsx` 1414 行（单组件 1200 行）、`slice.py` 1245 行（单端点 400 行）、`projects.py` 980 行，多 agent 并行叠加后无人收敛。

## 2. 问题清单

| # | 级别 | 类别 | 位置 (file:line) | 问题 | 证据 (graft 输出) | 影响 | 建议修复方案 |
|---|---|---|---|---|---|---|---|
| 1 | P1 | C2 | `backend/app/celery/tasks.py` L259/L464/L795/L1303/L1341/L1555/L1634/L1703/L1724/L1745 | 失败路径 `update_state(FAILURE)` 后 raise/return dict，触发 Celery 结果后端二次序列化异常 | `graft grep FAILURE` 22 处；对照 `shortdrama_tasks.py` L369-372 注释：*"不能 update_state(FAILURE) 后再 return dict——Celery mark_as_done 读旧 FAILURE meta 把 result 当异常解析"* | 真实错误被 `exc_type KeyError` 掩盖，排障困难；部署日志噪音 | 对齐 shortdrama 模式：失败只写 DB 状态并 `return`（前端依赖 DB 轮询），或直接 `raise` 不先置 FAILURE meta |
| 2 | P1 | B2 | `backend/app/celery/tasks.py`（全文件 2532 行；`slice_task` L543-819 签名 20+ 参数；`task_publish_video` L1265-1506 242 行） | 单文件混选点/检测/切片/批量切片/发布/指标/运维/多运营者 5+ 类职责 | `graft skeleton tasks.py`：20+ 个 `@celery` 任务与 30+ 辅助函数 | 改一处牵连全局；单 worker 串行时任一长任务阻塞全部队列 | 按领域拆 `celery/`：`selection.py`（autoclip/detect）、`slice_tasks.py`、`batch_tasks.py`、`publish_tasks.py`、`ops_tasks.py`（metrics/alert/maintenance）；`slice_task` 参数收敛为单一 `SliceRequest` 配置对象 |
| 3 | P2 | A2 | `backend/app/api/projects.py` L607-791（`project_workflow_status` + `_stage_status`）；`frontend/src/api/projects.ts` L52-54 | 前端入口已删，后端 184 行端点与前端 API 封装均无人调用 | `graft grep "workflow-status"`：2 处，均 0 in-edges；`graft callers getWorkflowStatus`：无调用方 | 垃圾代码量 + 误导后续 agent | 删除端点与前端封装；保留 `project_stats`（L253-310，仍在用） |
| 4 | P2 | A3 | `frontend/src/pages/EpisodeDetail.tsx` L115-168/L492-635/L1264-1392；`frontend/src/pages/BatchSlice.tsx` L46-83/L240-281/L396-436；`frontend/src/pages/ProjectDetail.tsx` L19-33/L458-506 | 切片配置/预设/payload 组装三处各自实现 | graft skeleton 三页面：各自有独立 `SlicePreset`/`SliceConfigState`/`BatchSliceConfig` + 独立 build 函数 | 参数口径漂移（如 badge/subtitle/watermark 新增字段漏同步），改配置一处生效一处不生效 | 抽公共 `frontend/src/utils/sliceConfig.ts`：单一配置模型 + 序列化/反序列化 + 预设存取，三页面引用 |
| 5 | P1 | C1/C4 | `backend/app/services/publish_service.py` L83-92（全局 `_shared_playwright` 单例）、L469-481（`_close_connection`）；`backend/app/services/doubao_service.py` L72-83；`backend/wechat_download/preview_client.py` L45-54 | Playwright 生命周期三处各自管理：全局单例复用 vs 每次 start 无 stop，清理时机不一致 | `graft grep playwright`：39 处，3 个模块各自 `_connect`/`_playwright` | 连接泄漏、CDP 端口冲突、发布长稳后浏览器句柄堆积 | 统一 `playwright_manager.py`：进程级单例 + 引用计数 + 空闲回收，三模块共用 |
| 6 | P1 | C3 | `docker-compose.yml` worker `--concurrency=1`；`tasks.py` 队列路由 | 单 worker 串行消费 video_processing 队列，长切片任务阻塞选点/检测；并发假设散落注释中 | graft 概念节点 "Celery Task Layer"：显式队列路由隔离 workload | 任务排队饥饿（此前已发生过选点被卡 10 分钟） | 按队列分 worker 进程：`video_processing`（切片/检测）与 `selection`（选点）独立容器；或 concurrency 调 2-3 + prefetch 控制 |
| 7 | P2 | B1 | `frontend/src/pages/EpisodeDetail.tsx`（3034 行）、`frontend/src/pages/BatchSlice.tsx`（1414 行，`BatchSlicePage` L218-1412）、`backend/app/api/slice.py`（1245 行，`run_slice` L265-662 400 行） | 巨型文件/巨型端点 | graft skeleton 各文件 | 可读性差、diff 冲突率高（多 agent 并行） | EpisodeDetail 按「切片配置面板/任务列表/进度轮询」拆 3 组件；slice.py `run_slice` 拆 config 构造器 + 引擎分发器 + 落库器 |
| 8 | P2 | D2 | `backend/app/api/publish*.py` 11 文件（`publish.py` 37 行聚合 + 8 子路由；`publish_tasks.py` 621 行） | 发布路由碎片化，同名域分散 | `ls backend/app/api/publish*.py` 11 个；`graft grep include_router` publish.py 聚合 8 个 router | 路由查找成本高、schema 重复 | 保留聚合入口，但把 `publish_tasks.py` 内部按 handler/service 分层；短期不强制合并文件数 |
| 9 | P2 | D1/A2 | `backend/app/api/` 32 个路由文件 | 路由总量膨胀，部分端点与前端使用率低（除 workflow-status 外需逐个核对） | 文件清单 32 个 | 维护面大 | 用 graft callers 对每个路由做 in-edges 普查，输出"0 调用端点清单"后批量确认删除 |
| 10 | P3 | A4 | `.gitignore`（graft build 自动追加 `graft/`）；`graft/` 已入库 383 文件 | graft 0.10.1 默认把 `graft/` 加入 gitignore，与"随代码提交"决策冲突，后续地图刷新不再入版本库 | `graft build` 输出 *"graft/ is git-ignored (added automatically)"*；`git status` 显示 `.gitignore` 与 `graft/*.md` 被改 | 队友 clone 后地图不一致；CI 无法 diff 地图 | 决策二选一：保留随库提交 → 从 `.gitignore` 移除 graft 条目并重新 add；改为本地缓存 → 删除库内 graft/ 并接受 gitignore |
| 11 | P3 | C1 | `graft grep "except Exception"` 300 处/53 文件（含 `_write_audit` L171、`_probe_duration` L71、`_current_llm_model` L457 等） | 宽泛异常吞没普遍，部分无日志 | graft grep 命中 300 处 | 失败静默、难定位（与 #1 叠加） | 抽查 publish/worker 链路，宽 except 至少 `logger.exception`；数据写路径禁止吞错 |

## 3. Top 10 行动清单（按性价比排序）

| 优先级 | 行动 | 工作量 | 说明 |
|---|---|---|---|
| 1 | 删除 `workflow-status` 死代码（后端端点 + 前端封装） | S | 184 行白送，四类引用全空，删完跑 graft build 验证 in-edges |
| 2 | 修复 Celery 失败序列化（7+ 任务对齐 shortdrama 模式） | S | 消除部署日志二次异常，真实错误可见 |
| 3 | 抽公共 `sliceConfig.ts`，三处切片配置收敛为单一模型 | M | 消除参数口径漂移的最大重复源 |
| 4 | 拆分 `tasks.py` 为 5 个领域模块 | L | 上帝对象拆分，配合 #2 一起做 |
| 5 | `slice_task` 签名收敛为配置对象 | M | 20+ 参数 → 1 个 `SliceRequest`，为 #4 铺路 |
| 6 | 队列分 worker：selection 与 video_processing 独立容器 | M | 消除单 worker 饥饿，部署稳定性直接受益 |
| 7 | 统一 Playwright 生命周期管理 | M | 三模块共用单例 + 回收，发布链路长稳 |
| 8 | `run_slice` 400 行端点拆 3 个内部服务函数 | M | 降低改切片逻辑的爆炸半径 |
| 9 | graft 路由 0 调用普查并批量确认删除 | M | 输出完整"死端点清单"再删，防漏 |
| 10 | 决策并落实 `graft/` 的 git 策略（随库 or 本地缓存） | S | 避免团队地图不一致 |

## 4. 架构级建议

1. **任务层按领域边界拆模块，队列按领域隔离。** 单 worker + 单文件承担全链路是本次部署连环故障的结构根因；把选点/切片/发布/运维拆成独立任务模块与独立队列容器，长任务不再互相阻塞。
2. **前端切片配置收敛为单一领域模型。** 三页面各自维护配置是"改一处漏两处"的温床；以 `sliceConfig` 单一来源 + 序列化协议替换三套实现，后续 badge/subtitle/watermark 等新字段只改一处。
3. **把"失败路径"做成约定而非注释。** `shortdrama_tasks.py` 已经用注释记录 Celery 缺陷，但同类代码仍在新增——在 `celery/` 加一个共享 `task_base`（统一失败处理：DB 状态优先、禁止 FAILURE+return 组合），让约定被代码强制。

## 5. 修改方案建议（按问题编号）

> 以下方案均为"改动建议"，未在本轮审查中实施。标注 ✅ 的表示已在报告后落地。

### #1 Celery 失败序列化二次异常（P1，S）

目标：失败路径不再产生 `exc_type KeyError`，让真实错误进日志。

1. 新建 `backend/app/celery/base.py`，提供统一失败出口：
   ```python
   def fail_with_db_state(db_writer, task_id, *, status="failed", **meta):
       # 1) 只写业务库（如 publish_tasks.status / autoclip_runs.status）
       # 2) return {"success": False, "status": "failed", **meta}
       # 绝不调用 self.update_state(state="FAILURE", ...) 后再 raise/return
   ```
2. 逐个改造失败分支（对照 `grep FAILURE` 的 22 处）：
   - `autoclip_task`（L259）、`detect_task`（L464）、`slice_task`（L795）、`task_publish_video`（L1303/L1341）、`confirm_publish_worker`（L1555/L1634）、`check_cookie_status`（L1703）、`sync_multi_operator_profiles`（L1724）、`watch_multi_operator_routes`（L1745）：删除 `update_state(FAILURE)` + `raise`，改为"写 DB 状态 + `return` 失败 dict"。
   - 前端状态展示依赖 DB 轮询（`doubao_status` 已证明可行），无需 celery FAILURE。
3. 验收：部署冒烟日志不再出现 `ValueError: Exception information must include the exception type`；人为制造一次失败，确认 DB 状态 = failed 且真实异常出现在 worker 日志。

### #2 tasks.py 上帝对象拆分（P1，L）

目标：2532 行按领域拆 5 个模块，任务名/路由保持兼容。

1. 新建文件与迁移清单：
   | 新文件 | 迁入内容（按现有行号） |
   |---|---|
   | `celery/common.py` | `run_async`（L130）、`_ensure_source_video`（L146）、共享 DB 工具 |
   | `celery/selection_tasks.py` | `autoclip_task`（L163）、`detect_task`（L412）+ `_save_autoclip_results`/`_save_detected_intervals`/`_mark_autoclip_failed`/`_update_autoclip_run`/`_update_episode_status`/`_create_detect_task`/`_update_detect_task_progress`/`_fail_detect_task` |
   | `celery/slice_tasks.py` | `slice_task`（L543）、`batch_slice_task`（L273）、`batch_selection_consumer`（L291）、`batch_slice_dispatch`（L308）、`batch_slice_finalize`（L323）、`batch_aggregate`（L338）+ manifest/outputs/progress 辅助 |
   | `celery/publish_tasks.py` | `publish_schedule_dispatcher`（L350）、`task_publish_video`（L1265）、`confirm_publish_worker`（L1529）、`check_cookie_status`（L1639）+ 全部 `_*publish*` 辅助与 `gen_publish_trace_id` |
   | `celery/ops_tasks.py` | `task_collect_metrics`（L1750）、`_compute_funnel_snapshot`（L2045）、`run_alert_check_task`（L2135）、`maintenance_daily_task`（L2150）、`sync_multi_operator_profiles`（L1708）、`watch_multi_operator_routes`（L1729） |
2. `celery/tasks.py` 保留 Celery app 定义、队列路由与 beat 配置，末尾聚合导入：
   ```python
   from .selection_tasks import autoclip_task, detect_task
   from .slice_tasks import slice_task, batch_slice_task, ...
   ```
   保证 `task_routes` 里 `app.celery.tasks.X` 完整名不变，避免 broker 中 in-flight 任务失效。
3. `slice_task` 签名收敛：新建 `SliceRequest`（dataclass/pydantic），把 20+ 参数（dedupe/watermark/vert2horiz/badges/subtitle/text_overlays/subtitle_mask/cover 等）收进一个 dict 字段；任务签名改为 `slice_task(self, task_id, request: dict)`，内部 `SliceRequest(**request)` 反序列化。
4. 验收：`graft build` 后 `graft skeleton tasks.py` 应只剩 app/路由/聚合；`graft callers` 各任务 in-edges 恢复正常；队列里新老任务都能被消费。

### #3 workflow-status 死代码删除（P2，S）

1. 删 `backend/app/api/projects.py` L607-791：`project_workflow_status` 端点 + `_stage_status` 辅助（若 `ProjectOutputItem` 等 schema 仅被该端点使用则一并删）。
2. 删 `frontend/src/api/projects.ts` L52-54 的 `getWorkflowStatus` 及 `ProjectWorkflowStatus` 类型。
3. 验收：`graft grep "workflow-status"` 返回 0 处；前端 tsc 通过（确认无页面引用）。

### #4 切片配置三处收敛（P2，M）

1. 新建 `frontend/src/utils/sliceConfig.ts`：
   - 统一 `SliceConfig` 类型（合并 `SlicePreset`/`SliceConfigState`/`BatchSliceConfig` 字段，含 autoclip/interval/dedupe/watermark/vert2horiz/subtitle/text_overlay/badge/cover）。
   - `buildSlicePayload(cfg): ApiSliceRequest`——唯一 payload 组装入口。
   - `presetStore`：`loadPresets()/savePresets(list)/applyPreset(cfg, preset)`，localStorage key 统一。
2. `EpisodeDetail.tsx`（L492-635 的 persist/apply 逻辑 + L1264-1392 的 runSlice/oneClickSlice）、`BatchSlice.tsx`（L240-436 的 applySlicePreset/buildPayload）、`ProjectDetail.tsx`（L458-506 的 runOneClickSlice/runBatchSlice）改为调用该模块，删除各自配置模型。
3. 验收：三页面切片参数行为一致（badge/subtitle 等新字段一处改全局生效）；`graft grep "SlicePreset|SliceConfigState|BatchSliceConfig"` 只命中 `sliceConfig.ts`。

### #5 Playwright 生命周期统一（P1，M）

1. 新建 `backend/app/services/playwright_manager.py`：进程级单例（asyncio 锁 + 引用计数 + 空闲超时回收），提供 `acquire()/release()`。
2. `publish_service.py`（L83-92 全局 `_shared_playwright`、L469-481 `_close_connection`）、`doubao_service.py`（L72-83 每次 start）、`wechat_download/preview_client.py`（L45-54）改用该管理器，统一 stop/关闭语义。
3. 验收：长跑发布任务后浏览器句柄数不增长；`graft grep "async_playwright"` 只剩管理器一处创建。

### #6 队列分 worker（P1，M）

1. `docker-compose.yml` worker 增加 `--concurrency=2`（或拆两个容器）：
   - `worker`（video_processing：切片/检测/批量）
   - `selection_worker`（selection：autoclip 选点）
   - `publish_worker`（publish：发布/确认/定时派发）
2. `celery_app.conf.task_routes` 把 `autoclip_task` 路由到 `selection` 队列（当前与 detect/slice 同队列）。
3. 验收：同时跑一个长切片 + 一个选点任务，选点不被阻塞；graft 概念节点 "Celery Task Layer" 的队列说明与实际一致。

### #7 slice.py run_slice 拆分（P2，M）

1. `backend/app/api/slice.py` 内新增 3 个内部服务函数：
   - `_build_slice_request(data) -> SliceRunRequest`：配置解析/校验（含 no_cut/output_id/普通三路的判定）。
   - `_resolve_engine(request) -> EngineSpec`：根据 cutlist/模式选 engine（ffmpeg 直切 / Go worker / scrub）。
   - `_dispatch_slice(request, episode) -> (celery_task_id, slice_task_id)`：落库 + 派发。
2. `run_slice`（L265-662，400 行）只保留编排：调上述三函数 + 权限/数据隔离。
3. 验收：`graft skeleton slice.py` 显示 run_slice 缩到 <120 行；`graft callers` 三函数各自职责单一。

### #8 巨型前端拆分（P2，M）

1. `EpisodeDetail.tsx`（3034 行）抽 3 个组件到 `frontend/src/components/episode/`：
   - `SliceConfigPanel.tsx`（配置表单 + 预设，迁 L115-635 相关）
   - `SliceTaskList.tsx`（任务列表 + 进度，迁 L837-1063）
   - `SliceRunActions.tsx`（oneClickSlice/runSlice，迁 L1121-1392）
2. `BatchSlice.tsx`（1414 行）`BatchSlicePage` 组件内抽 `BatchConfigForm`/`BatchItemTable`/`OutputTrimModal`。
3. 验收：graft skeleton 各新组件职责单一；diff 冲突概率下降。

### #10 graft 入库策略（P3，S）✅ 已落地

已执行：从 `.gitignore` 移除 graft 0.10.1 自动追加的整目录忽略，保留 `graft/.cache/`、`graft/.graph/` 精细忽略；刷新后的地图已提交（`a7013bb`）。后续 `graft build` 的 md 变更正常随代码入库。

---

## 6. 主 Agent 复核意见（2026-08-18 追加）

> 复核人：DSH 主控 agent（本仓库当日全部改动的执行者）。基于当天亲手改动与部署日志交叉验证。

### 6.1 事实核验（与当日运维记录对照）

| 报告条目 | 核验结论 |
|---|---|
| #1 Celery 失败序列化二次异常 | ✅ **实锤**。当日 12:51/17:49 两次部署冒烟日志均现 `ValueError: Exception information must include the exception type`（worker-publish），与报告描述完全一致；修复后应能从部署日志中消失，可作为验收信号 |
| #3 workflow-status 死代码 | ✅ 确凿。当日 17:12 由本 agent 移除前端工作流看板（commit `08505ef`），后端端点 `projects.py` L607-791 确实遗留未删，四类引用全空 |
| #4 切片配置三处各维护 | ✅ 属实且**当日被加深**：`5f3db62`（EpisodeDetail 去重档位）、`08505ef`（ProjectDetail 预设选择器）、`27be218`（BatchSlice 预设选择器）各加了一套预设逻辑，参数口径漂移风险真实存在 |
| #5 Playwright 生命周期 | ✅ 结构性风险成立（publish/doubao/wechat_download 三模块各自管理） |
| #6 单 worker 队列饥饿 | ✅ 与历史事故吻合（选点曾被长任务阻塞约 10 分钟） |
| #10 graft 入库策略 | ✅ 已按报告建议落地（`a7013bb`，已推送 cnb+origin） |

### 6.2 对报告的修正与补充

1. **Codex 违反"只读审查"约束**：报告声明"未修改任何代码"，但 #10 实际已由 Codex 提交（`a7013bb`）。方向正确、影响无害，但说明 Codex 有自行越权的倾向——后续让它执行"只读任务"时需在会话内明确禁止 git 写操作。
2. **#2 拆分 tasks.py 的迁移清单行号已过时**：报告基于 `3d807d1`（HEAD 快照），其中 `slice_task` L543-819、`task_publish_video` L1265-1506 等行号在并行 pipeline 持续合入后会漂移——执行时以 `graft skeleton tasks.py` 实时定位为准，不要照抄行号。
3. **#1 的"22 处 FAILURE 分支"需先分级**：其中 `autoclip_task`/`detect_task`/`slice_task`/`task_publish_video`/`confirm_publish_worker` 是核心链路（改完必须全流程部署冒烟）；`check_cookie_status`/`sync_multi_operator_profiles`/`watch_multi_operator_routes` 属运维辅助（可同批但风险低）。建议一次合入、一次部署、一次验证。
4. **遗漏项补充**：报告未覆盖当日新增的 `auto_autoclip_if_empty` 后端兜底链路（`slice.py` run_slice 内 10 分钟轮询等待）——该轮询在请求线程内 sleep，若未来改多 worker 需警惕；建议列入后续 M 级优化观察。

### 6.3 执行排序调整（考虑多 agent 并行合入的冲突风险）

并行 pipeline 每日合入 10+ MR，与任何重构的 diff 冲突概率高。建议执行顺序按"**先删后拆、S 级先行、L 级错峰**"：

| 阶段 | 动作 | 理由 |
|---|---|---|
| **Phase 1（本周，S）** | #3 删 workflow-status（后端+前端封装）→ 部署 | 零风险、立刻减 184 行 |
| **Phase 1（本周，S）** | #1 修 Celery 失败序列化（22 处统一走 `fail_with_db_state`）→ 部署+冒烟验证"日志噪音消失" | 直接改善部署可靠性，是我们反复踩的点 |
| **Phase 2（下周，M）** | #4 抽公共 `sliceConfig.ts`（三页面收敛） | 需要在"并行 pipeline 改配置页"的窗口期外执行；动前端三页，冲突面大，先约时间窗口 |
| **Phase 2（下周，M）** | #6 队列分 worker（selection 独立容器） | 改 docker-compose + task_routes，与代码重构隔离，风险可控 |
| **Phase 3（两周内，M）** | #7 run_slice 拆分 / #5 Playwright 统一 | 纯后端内部重构，影响面可控 |
| **Phase 4（排期，L）** | #2 tasks.py 拆 5 模块 + #8 巨型前端拆分 | 大重构，建议挑并行 pipeline 低活跃时段（如深夜）执行，且分两次合入（先 celery 后前端） |

### 6.4 风险提示

- **#2 拆分时不能改任务完整名**（`app.celery.tasks.X`），否则 broker 中 in-flight 任务丢失——报告已注意，复核确认此为硬约束。
- **#4 抽 sliceConfig.ts 前**先与并行 pipeline 对齐"配置字段清单"，避免它正在加新字段时我们重构旧模型。
- 所有重构合入后必须跑 `graft build` 刷新地图并提交（防地图漂移，参考 #10 决策）。
- 建议为每次 Phase 建立验收信号（如 #1 的"部署日志无 exc_type"、#3 的"graft grep 0 命中"），避免"改完没验证"。
