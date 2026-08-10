# 区间检测进度条 Bug 分析与切片功能系统测试方案

> 关联 Issue：#1「进度问题」
> 整理：CodeBuddy | 日期：2026-08-10
> 范围：通用区间检测进度条异常 + 切片相关功能（界面展示 + 功能流程）系统性测试

---

## 一、问题描述

**Issue #1 原始反馈：**

> 通用区间检测启动后，进度条会动一下然后就消失了，帮我查下什么原因。另外切片相关的功能都走一遍，包括界面展示和功能流程，都做个系统性的测试。

即两个诉求：

1. 定位并解释「区间检测进度条动一下然后消失」的根因。
2. 对切片相关功能做一次系统性测试（含界面与流程）。

---

## 二、进度条「动一下然后消失」根因分析

### 2.1 涉及的关键代码路径

| 层级 | 文件 | 说明 |
|------|------|------|
| 前端（触发） | `frontend/src/pages/EpisodeDetail.tsx` | `runDetect` 启动检测并开启 3s 轮询 |
| 前端（进度展示） | `frontend/src/pages/IntervalDetection.tsx` | 轮询 `/progress` 并渲染 `Progress` |
| 前端 API | `frontend/src/api/intervals.ts` | `detect` / `progress` 封装 |
| 后端（调度） | `backend/app/api/intervals.py` | `/detect` 落库 + 派发 Celery；`/progress` 查询 |
| 后端（执行） | `backend/app/celery/tasks.py` | `detect_task` 更新 `slice_tasks` 表进度 |
| 后端（引擎） | `backend/app/services/interval_service.py` | 调用 `detect_intervals.py` 引擎 |

### 2.2 数据模型

区间检测任务**复用 `slice_tasks` 表**，用 `mode` 前缀 `detect_` 区分（如 `detect_credits`、`detect_static`、`detect_watermark`）。前端 `/progress` 接口按 `episode_id` + `mode like 'detect_%'` 取**最新一条**。

### 2.3 正常流程（预期行为）

```
用户点「开始检测」
   │
   ├─ POST /episodes/{id}/intervals/detect
   │    1. 落库一条 SliceTask(mode='detect_xxx', status='pending', progress=10) 并立即 commit
   │    2. 派发 celery_detect_task
   │    3. 更新 celery_task_id，状态置 running
   │
   ├─ 前端轮询 GET /episodes/{id}/intervals/progress（每 3s）
   │    - pending/running → 渲染进度条（active）
   │    - completed → 渲染成功态 + 结果条数
   │    - failed → 渲染异常态 + 错误信息
   │    - unknown（无记录）→ 进度条隐藏
   │
   └─ worker 执行 detect_task：
       progress=20 (running) → detect_intervals() 运行 → 落库区间 →
       progress=100 (completed) → 前端刷新列表
```

### 2.4 根因判断（关键结论）

**「动一下然后消失」＝ 进度接口短时间内返回 `unknown`，前端据此把进度条 `setDetectStatus(null)` 隐藏了。**

触发条件主要来自以下几个层面，按可能性排序：

#### 原因 A：进度查询命中「旧的已结束任务」后无新任务在跑（最常见）

- `/progress` 取的是该剧集**最新一条** `detect_%` 记录。
- 若上一次检测已完成/失败，而新任务尚未在表中落库（例如调度刚提交、但 API 落库失败或 worker 未创建新记录），接口会返回旧记录的 `completed/failed`；前端收到后判定结束、停止轮询、**清除进度条**。
- 于是用户看到进度条「动一下（本地 setProgress 20）→ 随后因 completed/failed 或 unknown 而消失」。

#### 原因 B：任务秒完成/失败（引擎异常或空结果）

- `detect_intervals.py` 若抛错（引擎未挂载、ffmpeg 缺失、视频路径不存在、超时等），worker 会 `_fail_detect_task` 置为 `failed`。
- 前端轮询到 `failed` 后**立即清除进度条**并停止轮询——进度条看似「一闪而过」。
- 尤其 **watermark 模式无自动检测器**：代码注释已明确「该模式无自动检测器，需手动添加」，若用户选了水印模式，流程不会产生自动进度，最终返回「completed 但 0 个区间」或直接失败，进度条同样会快速消失。

#### 原因 C：落库与派发的竞态（已缓解但仍需验证）

- API 层 `detect` 已做改进：先落库 `progress=10` 并 `commit`，再派发 Celery，正是为了**避免提交后轮询窗口内查不到进度**（对应注释）。
- 但 worker 内 `_ensure_source_video` 下载大文件耗时较长，期间记录停留在 `pending/running`，若此时进度接口未返回，前端会出现「长时间 10% 不动」或偶尔被覆盖。
- 若 worker 从未启动（Celery 未运行、Redis 未连通、队列 worker 离线），任务永远不会推进，前端停留在初始 20%，随后可能因心跳异常而清除。

#### 原因 D：前端轮询生命周期问题

- `EpisodeDetail.tsx` 与 `IntervalDetection.tsx` 各有**独立的轮询**，二者共享同一个 `/progress` 接口。
- 若在 `EpisodeDetail` 启动检测后，用户导航到 `IntervalDetection` 页，两个轮询并存，可能互相覆盖 `setDetectProgress` / `setDetectStatus` 状态，造成进度条抖动或消失。

### 2.5 建议排查步骤（按顺序）

1. **查后端日志**：确认 celery worker 是否在运行、`detect_task` 是否被消费、`_fail_detect_task` 是否被触发及错误信息。
2. **直接调接口验证**：
   ```bash
   # 触发检测
   curl -X POST "http://<host>/api/episodes/<episode_id>/intervals/detect" \
     -H "Authorization: Bearer <token>" -d '{"mode":"credits"}'
   # 观察进度
   curl "http://<host>/api/episodes/<episode_id>/intervals/progress" \
     -H "Authorization: Bearer <token>"
   ```
   重点观察返回的 `status` 是否出现 `unknown`、是否从 `pending` 直接跳到 `failed`。
3. **确认引擎与依赖**：`engines/detect_intervals.py` 是否存在、`ffmpeg` 是否可用、MinIO 视频路径是否可下载。
4. **确认选用模式**：若用户使用 `watermark` 模式，预期本就没有自动进度，需前端引导「手动添加」，避免误判为 Bug。

### 2.6 建议修复方向（供后续迭代）

- **前端区分「无任务」与「任务异常」**：`unknown` 不应直接清空进度条，可保留「上次状态」或显示「暂无运行任务」空态，而非闪没。
- **统一轮询**：`EpisodeDetail` 与 `IntervalDetection` 共享同一进度源，避免双轮询互相覆盖；建议把进度状态提升到全局 store（Zustand）或 Context。
- **失败可观测**：前端在 `failed` 时展示 `error_message`（现有 `ErrorHint` 组件），避免用户只看到进度条消失而不知原因。
- **增加超时/心跳**：worker 长时间无进度更新时给用户提示「任务可能卡住，可重试」，并暴露「重试」入口。

---

## 三、切片功能系统性测试方案

### 3.1 切片功能地图（界面 + 流程）

依据代码，切片链路涉及以下页面/接口：

| 模块 | 前端页面 | 后端接口 |
|------|----------|----------|
| 切片任务列表/执行 | `SliceTasks.tsx` | `/episodes/{id}/slice/run`、`/slice-tasks` |
| 选点/片段审核 | `ClipReview.tsx` | autoclip 相关 |
| 输出预览 | `OutputPreview.tsx` | `/slice-tasks/{id}/outputs`（presigned_url）|
| 成品库 | `Projects/ProjectDetail/OutputPreview` | 成品查询 |
| 区间检测联动 | `EpisodeDetail` / `IntervalDetection` | `/intervals/*` |

**切片模式（`SLICE_MODE_HELP`）：**
- `fast` 快速模式：按选点结果直接切割，不去重。
- `dedupe` 去重模式：画面相似度检测去重。
- `scrub` 挖洞模式：去重 + 随机挖洞，指纹更独特。

**切片高级参数（`sliceApi.run`）：**
- 文字水印：`watermark_enabled/text/font_size/opacity/position`
- 竖屏转横屏智能裁切：`vert2horiz_enabled/mode/ratio/output_size/detect_interval/smooth_window`
- 成品重新剪辑：`output_id/cut_start/cut_end`

**任务操作：** 查看输出、取消、重试、删除。

### 3.2 测试用例清单

#### A. 界面展示（UI）测试

| # | 场景 | 预期 | 通过 |
|---|------|------|------|
| A1 | 进入切片任务页，无任务 | 空态提示正常，无报错 | ☐ |
| A2 | 切片模式选择（fast/dedupe/scrub） | 选项齐全，Tooltip 说明正确 | ☐ |
| A3 | 高级参数（水印/竖转横）开关与参数联动 | 开启后显示对应参数项，关闭则隐藏 | ☐ |
| A4 | 任务列表列展示（模式/状态/输出数/节点/错误/时间） | 字段齐全，状态 Tag 颜色正确 | ☐ |
| A5 | 运行中任务进度条 | 显示 active 进度条，百分比随轮询更新 | ☐ |
| A6 | 查看输出弹窗 | 输出文件列表 + presigned_url 可播放 | ☐ |
| A7 | 空/异常输出 | 给出友好提示，不白屏 | ☐ |

#### B. 功能流程测试

| # | 场景 | 预期 | 通过 |
|---|------|------|------|
| B1 | fast 模式切片 | 成功生成切片输出，任务 completed，输出数正确 | ☐ |
| B2 | dedupe 模式切片 | 去重逻辑生效，输出片段数符合预期 | ☐ |
| B3 | scrub 挖洞模式切片 | 生成挖洞片段，指纹差异化 | ☐ |
| B4 | 取消运行中任务 | 任务置 cancelled，进度停止 | ☐ |
| B5 | 重试失败任务 | 重新调度，成功完成 | ☐ |
| B6 | 删除任务 | 任务与 MinIO 输出一并删除 | ☐ |
| B7 | 文字水印开关 | 输出片段含指定水印（文本/字号/透明度/位置） | ☐ |
| B8 | 竖屏转横屏裁切 | 输出为设定尺寸（如 1920x1080），fixed/dynamic 模式均验证 | ☐ |
| B9 | 成品重新剪辑（output_id + cut） | 按新起点/终点裁剪出新片段 | ☐ |
| B10 | 分布式 worker 执行 | 任务落到指定 node_id，worker 心跳/进度回调正常 | ☐ |
| B11 | worker 掉线/未注册 | 调度失败有明确错误，任务标记 failed | ☐ |
| B12 | 数据隔离（多项目） | 不同项目/剧集的切片任务互不可见 | ☐ |

#### C. 区间检测联动（回归 Issue #1）

| # | 场景 | 预期 | 通过 |
|---|------|------|------|
| C1 | credits 模式区间检测 | 进度条持续更新至 100%，区间落库并可查看 | ☐ |
| C2 | static 模式区间检测 | 同上，区间类型为静止画面 | ☐ |
| C3 | watermark 模式 | 明确提示无自动检测器，引导手动添加（非 Bug） | ☐ |
| C4 | 检测完成后刷新列表 | completed 后自动 fetch，列表出现 auto 区间 | ☐ |
| C5 | 检测失败 | 进度条显示异常 + 错误信息，不闪没 | ☐ |
| C6 | 手动添加/启用/停用/删除区间 | 各操作生效并刷新 | ☐ |
| C7 | 检测历史 | `/intervals/history` 倒序展示，含 interval_count | ☐ |

### 3.3 建议测试环境与前置条件

- 准备**竖屏 + 横屏**各一段素材，覆盖竖转横裁切场景。
- 准备**含重复片段、片尾字幕**的视频，覆盖 dedupe/credits 检测。
- 至少 1 台可用 worker 节点（或本地 Celery worker）验证分布式执行。
- 确认 MinIO / Redis / PostgreSQL 连通，`engines/` 目录已挂载。

### 3.4 回归优先级

- **P0**：B1（fast 切片）、C1（credits 检测）、A5（进度条）——主链路必须通过。
- **P1**：B2、B3、B7、B8、C2、C4——核心增强功能。
- **P2**：B4/B5/B6（任务管理）、B9、B10/B11、C3/C5/C6/C7——次要但需回归。

---

## 四、结论摘要

1. **进度条消失的根因**：前端在 `/progress` 返回 `unknown` 或快速到达 `completed/failed` 时清空进度条；叠加「最新一条 detect 记录被旧任务占用」「watermark 模式无自动检测器」「Celery 未消费」「双页面轮询互相覆盖」等多重因素，表现为「动一下然后消失」。
2. **最优先修复**：让前端在 `unknown/无任务` 时保留可读空态而非直接清空；统一两处轮询；失败时展示 `error_message`。
3. **切片系统测试**：按第三节用例清单执行，优先覆盖 P0 主链路。
