# clip-workflow — Agent 指引

本仓库已被 **graft** 索引，代码地图位于 `graft/`（328 文件 / 2920 符号 / 8153 条调用边，覆盖 Python + TypeScript/TSX + Go 三语言）。

**无论任何任务**——理解某个功能、定位代码位置、追踪谁调用某符号、判断一次改动的破坏面、规划一次编辑——都**先查 graft 地图**，再 grep 或读源码。查询一个节点只需几百 token；从头读源码重建这份理解要花几千 token，还会漏掉调用边。

> **代码审查任务（CNB 评审流水线）**：流水线已在 `/workspace/review-context.md` 预生成本次 PR 改动符号的 graft 调用链。启动审查时**必须先读该文件**，以它为准核查破坏面；如流水线未生成（本地手动评审），则自己跑 `graft callers <改动符号> --depth 2`。

---

## 用 graft 而不是裸 grep

graft 每条命令都 `$0`（零成本、本地、无需任何 API key），亚秒级返回。**选最贴合的一个，跑一次就照着答案干，不要连环调用工具。**

| 场景 | 用 graft 命令 |
|---|---|
| 上手/解释代码库 | `graft map`，然后读它点名的 hub 卡片 |
| 理解某个流程（"X 怎么工作的"） | `graft ask "<流程>" --source` |
| 找某改动该落在哪 | `graft ask "where is <行为>" --source` |
| 改一个你能叫出名字的符号 | `graft grep "<符号>"`，在返回的 `file:line` 上编辑 |
| 重命名/删除/改签名（先做） | `graft callers <sym> --depth 2` |
| 重构/多文件改动（先做） | `graft callers <sym> --depth all` |
| 找某模式的所有出现 | `graft grep "<字面量>"` |
| "这个文件对外 API 是什么" | `graft skeleton <文件>` |
| 合并前评估 diff 风险 | `graft callers <改动符号> --depth 2` |

### graft 工具速查

- **`graft ask "<问题>" --source`**：对代码图做排序检索，返回带精确 `file:line` 的 Top 命中；`--source` 把每个命中点的 ≤8 行"要害代码"内联出来。概念型/定位型问题用它。
- **`graft grep "<模式>"`**：对全部索引文件做穷尽匹配，按所属符号分组并按耦合度排序。需要"每一个出现处"时用它；`ask` 是 Top-N 会漏。
- **`graft skeleton <文件>`**：单文件"只看签名"的 API 概览，约 200 token，比读整个文件省 10 倍。
- **`graft callers <符号>`**：预计算的调用/引用边。默认 `--direction in`（谁在调用）；`--direction out`（它依赖谁）；`--depth N`（遍历 N 跳的完整爆炸半径）。
- **`graft map`**：目录热点 / 每目录 hub / 全局热点的 token 预算式导览。
- **`graft build` / `graft check`**：`build` 在编辑后自动刷新图（`--deep` 才接 LLM，非必要不跑）；`check` 供 CI 判断图是否过期。

> 关键：上面所有工具在回答前都会自动刷新图，所以返回的始终是**当前代码**（包括你刚改未提交的内容），编辑后**无需**手动 `build`。但 `graft/` 下的 md 卡片是"投影"、每轮结束才重建——如果你本回合刚编辑过某文件，该文件的卡片 span 可能滞后，优先用上面的工具而非直接 grep 卡片。

### 几条铁律

1. **用最少的调用**。卡片 `covers:` 列表已给出每个符号的精确 `file:line`，直接引用即可；不要为了"复核"重开文件或重 grep。
2. 任务已点名文件/符号时，直接 `graft grep "<符号>"` 拿 `file:line` 就去编辑；只有当你不知道代码在哪时才用 `ask`。
3. 信任答案并行动。只有当第一个工具确实没答上（命中弱、span 截断、需要穷尽）时才换第二个工具。
4. 只在 graft 确实没索引的文件（文档、配置、全新文件）上用裸 `grep -rn`。
5. graft 报出的路径不在磁盘上，说明它的索引超前于你的 checkout。

---

## 通过 MCP 使用（可选）

`.codex/config.toml` 已注册 graft MCP server（`graft mcp`），Codex 会获得 `graft_find_code` / `graft_find_all` / `graft_trace_calls` / `graft_file_api` / `graft_repo_map` 等 MCP 工具。用 MCP 工具与直接跑 `graft` CLI 等价，二选一即可。

---

## 项目背景

- 这是一套**短视频切片 + AI 选点 + 多运营者视频号发布**系统。
- 技术栈：FastAPI 后端 + React(Vite/AntD5/Zustand) 前端 + PostgreSQL/MinIO/Redis + Celery + Go slice-worker 分布式切片。
- 详细约定见 `CLAUDE.md` / `PROJECT.md` / `PROJECT_MEMORY.md`（graft 不管这些，它们与 graft 地图互补）。
- 改动前请先用 graft 定位，避免在上帝类/热点文件里凭直觉乱改。
