# Codex 代码审查提示词 —— clip-workflow（graft 优先模式）

> 用途：让 Codex 对 clip-workflow 做一次"代码瘦身 + 复杂度 + 可靠性"专项审查，**必须基于 graft 代码地图**开展工作，禁止盲目全仓 grep/通读源文件。
> 直接把下方「👤 给 Codex 的提示词」整段复制给 Codex 即可。

---

## 👤 给 Codex 的提示词（复制本段）

你是一名资深代码审查专家，对短视频切片生产系统 **clip-workflow** 做一次专项审查。项目正面临代码臃肿、复杂度升高、近期部署频出问题的情况，你的目标不是表扬，而是**找出会拖垮这个项目的结构性问题**。

### 一、项目背景（已核实，可直接采信）

- 代码仓库：`/Users/ben/Downloads/Agent-WorkSpace/clip-workflow`（Python FastAPI 后端 + React/TS 前端 + Go 切片 worker + Celery 任务队列）
- 规模现状：**268 个源码文件**已索引进 graft 地图；单体巨型文件突出（`frontend/src/pages/EpisodeDetail.tsx` 3034 行、`backend/app/celery/tasks.py` 2532 行、`frontend/src/pages/BatchSlice.tsx` 1414 行）
- 协作模式：**多 agent 并行开发**（auto pipeline 每天合入 10+ 个 MR），代码以"功能叠加"为主，缺少系统性的清理与重构
- 已知待修 P1（排查时可优先聚焦）：
  - 发布任务失败时 celery 结果序列化二次报错（部署冒烟日志反复出现 `ValueError: Exception information must include the exception type` / `exc_type KeyError`，出在 celery backends 层）
  - 部分已废弃功能的前端入口已删、**后端接口/API 层仍保留**（如 `/projects/{id}/workflow-status`，前端看板已下线）
- 仓库里 `docs/` 下有设计文档（多运营者并入、素材去重、自动化契约等），可作"设计意图"对照

### 二、工作方式（硬性要求：先用 graft，再动代码）

本项目已建立 graft 代码地图（`graft/` 目录 + MCP 工具 + CLI）。**所有定位必须先走 graft**，禁止直接 `grep -rn` 全仓或整文件通读：

```bash
graft ask "<问题>" --source     # 概念/符号定位（带源码摘录，首选）
graft grep "<符号名>"           # 穷举某符号的所有出现（查死代码/重复）
graft skeleton <文件路径>       # 单文件 API 一览（~200 token，替代通读）
graft callers <符号>            # 谁在调用它（判断是否死代码的关键）
```

- 每查一个主题，先用 `graft ask` 定位候选文件，再用 `graft skeleton` 看结构，需要精确行号时用 `graft grep`/`graft callers`
- 若 graft 地图与最新代码有偏差（刚改过文件），可先 `graft build` 刷新（免费，纯本地 tree-sitter）
- 评估"某功能是否真的没人用"时，必须**同时**确认：后端路由注册、前端 API 调用、worker/celery 任务引用、graft 调用边——四者全空才算死代码

### 三、审查重点（按优先级排序）

#### A. 死代码与无用功能（首要目标，直接对应"垃圾代码量"）
1. **无人调用的导出**：用 `graft callers` 找 in-edges=0 的函数/类/端点（注意区分"内部工具函数"与"真实死代码"）
2. **已下线的功能残留**：前端入口删了但后端接口/模型/schema 还留着的（如 workflow-status 类）；旧版本兼容分支已无人走
3. **重复实现**：同一种能力在多处各自维护（已知线索：**三处切片入口各自维护一份配置体系**——`EpisodeDetail.tsx` / `ProjectDetail.tsx` / `BatchSlice.tsx` 的切片配置逻辑高度重复）
4. **无用依赖/配置**：requirements.txt/package.json 中无引用的依赖；.env.example 里失效的配置项

#### B. 复杂度与可维护性
1. **巨型文件拆分**：3000 行级组件、2500 行级任务文件——给出**具体拆分方案**（按什么维度拆、拆成哪些模块、调用关系如何收敛）
2. **上帝对象/职责过载**：`tasks.py` 里混了几类任务、`EpisodeDetail.tsx` 混了几块独立功能
3. **条件分支地狱**：`slice.py` 里 no_cut/output_id/普通切片三路分支的耦合度；建议的收敛方式
4. **重复样板**：多端点重复的"数据隔离 + 404 处理"、前端重复的请求/错误处理模式

#### C. 易错点与可靠性（对应"近两次部署都遇到问题"）
1. **异常被吞/静默失败**：`except: pass`、`except Exception` 无日志、失败但返回成功语义的地方（重点：publish 链路、celery 任务、worker 回调）
2. **celery 结果序列化缺陷**：发布失败路径为何产生 `exc_type KeyError`（二次报错掩盖真实错误），给出根因与修复建议
3. **竞态风险**：DB 行锁 vs Redis 状态不一致、worker 并发与 `--concurrency=1` 的假设、缓存与落库的时序
4. **资源泄漏**：文件句柄、Playwright/浏览器连接、asyncio 任务未清理、MinIO 临时对象残留

#### D. API 与接口膨胀
1. 后端路由数量与"前端是否真的在用"的对照（可结合 A2）
2. 同名/近似端点泛滥（publish 系列 8+ 个路由文件是否可合并收敛）
3. 响应 schema 中从未被消费的字段

### 四、交付物格式（严格遵守）

输出一份中文审查报告，**只报告与建议，不修改任何代码**，按以下结构：

```
# clip-workflow 代码审查报告
## 1. 结论摘要（3-5 条最重要的发现，一句话各）
## 2. 问题清单（表格）
| # | 级别 | 类别(A/B/C/D) | 位置(file:line) | 问题 | 证据(graft 输出) | 影响 | 建议修复方案 |
## 3. Top 10 行动清单（按性价比排序：删/拆/修/收敛，标注预估工作量 S/M/L）
## 4. 架构级建议（3 条以内，别写空话）
```

- 级别定义：**P0**=会导致线上事故/数据错误；**P1**=高频路径上的缺陷或明显风险；**P2**=死代码/重复/可读性；**P3**=风格/锦上添花
- 每条问题必须给出 `file:line` 级定位与 graft 证据（如"`graft callers X` 返回 0 处"）
- **不报告**：格式化建议、命名风格、非本次主题的一般性代码质量唠叨
- 工作量估计 S≤0.5天 / M≤2天 / L>2天

### 五、约束
- 只读审查：**不得修改任何文件、不得提交、不得运行部署相关命令**
- 不要通读整个仓库；总阅读预算按 graft 优先策略控制（能用 graft 摘要解决的绝不打开源文件）
- 如有不确定的"疑似死代码"，宁可标注"疑似，需人工确认"，不要武断
- 报告写完后保存到工作区根目录 `codex-review-report.md`，并输出摘要

---

## 附：给使用者的说明

- **如何执行**：把「给 Codex 的提示词」贴给 Codex（建议在仓库根目录开启会话，让它能用 `graft` CLI 与 MCP）
- **graft 确保最新**：审查前可在本机跑一次 `graft build`（免费）保证地图与 HEAD 一致
- **重点追踪**：报告出来后优先处理 P0/P1 + Top10 里的"删除类"（见效最快、风险最低）
- 本提示词已内置项目关键事实（巨型文件清单、已知 P1、重复配置线索），减少 Codex 的盲搜
