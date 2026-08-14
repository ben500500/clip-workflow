# 视频号「多运营者」发布能力 · 并入 clip-workflow · 整体设计方案（v3.1 定稿）

> 版本：v3.1（定稿）| 日期：2026-08-14
> 配套系统：clip-workflow @ 192.168.1.163
> 前置研究：小V猫多运营者机制深挖（实时验证 + 官方文档）
> 评审形式：Part 1 为 5 人圆桌 × 3 轮 + 加权打分；Part 2 为 2 路独立红队 + 6 角色 × 3 轮收敛；v2 为代码核实 + 方案审核修订；v3 为外部评审意见吸收（6 项）；v3.1 为问题 3-7 对应章节修订吸收（5 项）

---

## 修订说明

### v1 → v2（代码核实 + 方案审核）

| # | 修订项 | 类型 |
|---|--------|------|
| R1 | docker-compose 服务数 19 → **17**（实测：postgres/redis/minio/minio_init/autoclip/alembic-migrate/backend/worker-video/worker-publish/worker-fast/beat/rpa_worker/slice-worker/slice-worker-2/frontend/nginx/ollama） | 事实修正 |
| R2 | Redis "namespace+ACL" 澄清：当前**仅 requirepass 口令认证，无 ACL**；落地时需新增 ACL 配置（`--aclfile`）或改用 key 前缀命名空间隔离 | 事实修正 |
| R3 | RBAC 角色为 **4 个**（admin/operator/publisher/**material** 素材专员），非 3 个；`data_scope` 默认按角色推导（operator→own，其余→all） | 事实修正 |
| R4 | `start_chromium.sh` 实际端口为 **9223**（`--remote-debugging-port=9223`），9222 由 cdp_proxy 监听并转发至 9223；端口规划基准以此为准 | 事实修正 |
| R5 | **新增「CDP 端口层安全设计」**：CDP 协议无认证，多端口暴露=任意内网主机可操控浏览器；必须只绑定 127.0.0.1 + cdp_proxy 统一鉴权入口 | 安全补强 |
| R6 | **换 IP 迁移"零停机"修正**：微信登录态对出口 IP 变化敏感，profile 搬迁后大概率触发验证/重登；毕业流程内置"预计需重登"预期与人工介入节点 | 设计修正 |
| R7 | **QR 扫码方案列为 Phase 1 前置 Spike**：headless Chromium 中微信登录二维码渲染未经验证（canvas/GPU 依赖），须先验证再开工 | 风险前置 |
| R8 | **Lua 配额脚本 nil 算术兜底**：`HGET/GET` 返回 nil 时 `nil+1` 直接报错，须 `tonumber(...) or 0` | 技术修正 |
| R9 | **成本重估**：静态住宅/ISP IP 国内市场价 ￥30-50/月/个（非 ￥6），Tier 1 毕业决策按真实成本测算 | 成本修正 |
| R10 | **补充宿主资源评估**：15 个 Chromium profile ≈ 5-8GB 内存 + 基础服务，192.168.1.163 需 16G+ | 补充 |
| R11 | **补充均分策略封面来源**、重试节奏（指数退避）、调度器感知 operator 失效机制 | 补充 |

### v2 → v3（外部评审意见吸收）

| # | 修订项 | 来源 | 类型 |
|---|--------|------|------|
| R12 | **路由表秒级失效闭环**：新增 `last_heartbeat` 字段 + watcher 10s 探测 `/json/version`，失败即秒级置 `expired` 并跳过调度，不等 30min 心跳 | 🔴1 | 健壮性补强 |
| R13 | **cover 回填语义明确**：payload 存「已上传后的 MinIO cover_key」（持久可访问），非待上传源；封面文件保留策略独立定义 | 🔴2 | 设计补全 |
| R14 | **Batch 模型落地任务/批次粒度**：新增 `publish_batches` 表；「任务不迁移」= task 级铁律，「均分/轮询」= batch 级分配逻辑 | 🟠3 | 模型补全 |
| R15 | **存量端口归一迁移**：flag=true 时存量 `chrome_debug_port=9222` 的 profile 显式迁移到端口池（9223+），杜绝"池外裸 Chromium"窗口 | 🟠4 | 迁移补全 |
| R16 | **"单 IP 小时 ≤2 条"口径澄清**：按**出口 IP 汇总**（同 IP 全部 operator 合计），与 operator 级 280-360s 随机延迟是两层约束；IP 级触顶是毕业压力信号而非矛盾 | 🟡5 | 口径澄清 |
| R17 | **actor_id/operator_id 鉴权角色分离**：二次鉴权 token 签给**操作人 actor_id**（含 publisher 代发场景）；operator_id 仅用于审计与配额维度，不承担身份校验 | 🟡6 | 鉴权补全 |

### v3 → v3.1（问题 3-7 对应章节修订吸收）

| # | 修订项 | 来源 | 对应章节 | 类型 |
|---|--------|------|---------|------|
| R18 | **confirm selector 校验失败兜底**：4.4 幂等重填前置校验 `selector_version` 与当前页面匹配，不匹配则冻结该 pending、置 `selector_mismatch` 并人工介入，绝不静默乱填 | 🟠问题3 | 4.4 | 兜底补全 |
| R19 | **cdp_proxy token 注入链路写实**：补全「app 签 token → 随 task payload 下发 → worker 在 CDP 握手前注入 `Authorization` 头 → cdp_proxy 校验后转发」的完整传递链 | 🔴问题4 | 4.5 / 主题7 | 安全补全 |
| R20 | **单 IP 排班节奏示例 + operator 延迟放大**：5.2 补「单 IP 2条/小时 × N operator」可执行排班示例；同 IP 时 operator 级延迟放大到 ≥30min 级，保 NFR「≥5 并行」口径落地 | 🟡问题5 | 5.2 / NFR | 运营补全 |
| R21 | **DoD 增补故障注入联调项**：Part 2 验收表加「混沌演练」行（模拟 Chromium 崩溃 / Redis 重启 / worker 重启，全链路自愈时间 ≤X，且 0 条误发） | 🟡问题6 | Part 2 DoD | 测试补全 |
| R22 | **inflight 跨日边界语义**：4.2 明确 `op_inflight/global_inflight` 计数绑定任务、随任务结束自然释放；跨日归零仅针对 `daily_used`（按当日剩余秒 TTL），避免日切点残留 in-flight 顶到次日上限 | 🟡问题7 | 4.2 / 主题2 | 边界补全 |

---

## 执行摘要（TL;DR）

- **已具备**：一期发布能力 = 插件式 Publisher（`wechat_channel`/`douyin`/`kuaishou`）+ 截图审核 + 配额治理 + Cookie AES-256/Fernet 加密 + RBAC。
- **两大缺口**：① 单浏览器单登录态（`start_chromium.sh` 只起 1 个 Chromium、单 profile、固定端口 9223、`worker-publish --concurrency=1`）；② 账号无归属人（`VideoAccount/PublishProfile` 缺 `created_by/operator_id`，全局共享）。
- **最大杠杆**：`PROJECT.md §8.3` 早把「每 PublishProfile 对应独立 Chrome Profile / 支持同平台多账号并行」写成设计意图，`PublishProfile.chrome_debug_port` 字段与 `chrome_profiles` 卷是现成预留钩子，本期正是落地它。
- **圆桌结论**：不推倒重来，采用 **「演进式收敛」** 路线 —— **Phase 1 用方案 A（单容器多 Profile 端口映射）** 周级上线；同时立下架构契约（账号→端口路由表、每账号并发信号量、状态外移 Redis）；越过阈值时平滑毕业到 **方案 B/C**，并由 **毕业控制器** 自动升 Tier 0→3 的隔离级别。
- **稳固可控铁律（P0 上线阻断项）**：单任务绑定单一 operator 不迁移 / 配额 Lua 原子 / 登录态自服务扫码 / 发布执行点二次鉴权 / 灰度零侵入可回滚 / CDP 端口层收敛 / **路由表秒级失效闭环（R12）**。
- **v3.1 新增收口（对应问题 3-7，R18-R22）**：① confirm 前置 **selector 版本校验**（不匹配即冻结+人工介入，R18）；② **cdp_proxy token 注入链路**全链路写实（app→payload→worker→proxy，R19）；③ **单 IP 排班示例 + operator 延迟放大 ≥30min**，把 NFR「≥5 并行」落到批次日调度（R20）；④ DoD 增补**混沌演练**（故障注入联调，R21）；⑤ **inflight 跨日边界语义**（绑定任务自然释放，不误顶次日配额，R22）。

---

# Part 1 · 需求方案 + 圆桌评审

## 一、需求背景与现状

### 1.1 业务背景：视频号「多运营者」机制（小V猫研究结论）
- 一个视频号**最多 20 个运营者微信号**；运营者权限 = 登录 / 发表 / 互动 / 直播管理（看不到收益）。
- 邀请后 **24 小时内未确认自动撤销**；须先关注对应视频号；状态「待确认 → 已绑定」全自动。
- **关键模型**：小V猫里 1 个「视频号账号」= (视频号 ID, 运营者微信号) 二元组 = 1 个独立沙盒浏览器 profile。管理员微信号 ≠ 视频号显示名。
- **「视频号·加热」是独立子域体系**：普通视频号运营者**暂不支持**电脑端登录加热平台；需「蓝 V 企业认证 → 开通加热企业账户 → 绑定加热运营者（最多 15 个，绑定前须关注对应视频号）」。

> 对 clip-workflow 的含义：同一视频号下用 N 个运营者微信各自登录并发布，必须为每个运营者维护**独立浏览器登录态（profile + cookie）**，且尊重「每个运营者自己的日发上限 / 间隔」。

### 1.2 clip-workflow 发布能力现状（已有一期，代码核实）
真实生产系统在 `/Users/ben/Downloads/Agent-WorkSpace/clip-workflow/`，docker-compose 共 **17 个服务**（非 19）。
- **插件式 Publisher 工厂**：`publish_service.py:502` `get_publisher(platform)` 映射 `wechat_channel/douyin/kuaishou`，`VideoChannelPublisher`（行 87）走 `channels.weixin.qq.com/platform/post/create`（行 101-102）。
- **全链路已通**：`api/publish.py`（938 行）→ `celery/tasks.py::task_publish_video`（行 1046-1143，截图存 MinIO → 前端人工确认 `confirm`）→ Playwright over CDP（`publish_service.py:122` 读全局 `s.CHROME_DEBUG_HOST`）→ 前端 `PublishManagement.tsx`。
- **配额治理**：`PublishProfile.min_interval_seconds=300`、`max_daily_publish=20`（models.py:478-479），实现于 `_check_publish_limits`（publish.py:343-410，`with_for_update()` 行锁）。
- **凭证模型**：`VideoAccount`（models.py:374）、`PublishProfile`（models.py:464，含 `chrome_debug_port` 默认 9222、`cookie_file`、`title_template`）；Cookie 由 `auth.py` Fernet 加密（行 298-316），API 返回脱敏 `****`（publish.py:248）。
- **RBAC**：4 角色 `admin/operator/publisher/material`（models.py:24-37）+ `own/all` 数据范围（`data_scope.py` 以 `projects.created_by` 判断归属）。
- **浏览器层现状**：`rpa/start_chromium.sh` 单 Chromium、`--remote-debugging-port=9223`（行 57）、单 `--user-data-dir=/data/chrome-profiles`（行 62）；`rpa/cdp_proxy.py` 单实例 9222→9223 双向 Host 改写；`worker-publish --concurrency=1`（docker-compose.yml:330）。
- **进程内状态**：`publish_service.py:29-30` `_PENDING_TABS` 进程内字典 + threading.Lock，注释明确依赖单进程串行。

### 1.3 现状缺口（As-Is → To-Be）

| 维度 | 现状 As-Is | 目标 To-Be（本期需求） |
|---|---|---|
| 浏览器登录态 | 1 个 Chromium、单 `--user-data-dir`、固定端口 9223（cdp_proxy 9222 转发）；`worker-publish --concurrency=1` | 每个运营者 = 1 独立 profile + 独立端口，可并行 |
| 待确认 tab 缓存 | 进程内 `_PENDING_TABS` 字典，依赖单进程 | 外移至 Redis，支持多进程/多副本 |
| 账号归属 | `VideoAccount/PublishProfile` 无 `created_by/operator_id`，全局共享 | 账号绑定归属人，运营者只见自己/被授权的号 |
| 配额粒度 | 按整号全局 20 条/天、300s 间隔 | 按「运营者」维度独立限额（均分模式基础） |
| 多运营者选择 | 无；一次发布绑定单一 PublishProfile | 可指定「视频号 + 运营者集合」，支持均分/轮询/指定 |
| CDP 端口暴露 | cdp_proxy 单端口 9222 无鉴权 | 多端口仅绑定 127.0.0.1 + cdp_proxy 统一鉴权入口 |
| 加热运营者 | 无（独立子域体系） | Phase 2 史诗（依赖蓝 V） |

> **最大阻塞点**：§8.3 写的「多账号并行」仍是**设计意图未实现**。`PublishProfile.chrome_debug_port` 与 `chrome_profiles` 卷是预留钩子，本期落地。

## 二、目标、范围与非功能需求

### 2.1 目标
- **GOAL-1**：支持「1 视频号 × N 运营者（N≤20）」各自独立登录态、并行/受控发布，复用一期发布与截图审核链路。
- **GOAL-2**：运营者粒度配额与风控（每运营者独立日上限、间隔、随机延迟），降低微信风控受限。
- **GOAL-3**：账号归属与可见性，运营者只见自己/被授权的号，符合企业协作与审计。
- **GOAL-4**：架构不锁死——本期方案须平滑演进到更大规模（多副本/独立沙盒）。

### 2.2 功能范围

**✅ In Scope（本期）**
- 账号归属：`created_by/operator_id` + RBAC `own/all`（兼容 4 角色）
- 浏览器层：多 profile 端口映射 + 账号→端口路由 + **CDP 端口收敛（127.0.0.1 + 代理鉴权）**
- 发布任务：指定「视频号 + 运营者集合」，支持**均分 / 轮询 / 指定**
- 配额：按运营者维度独立限额（叠加在整号上限之上），Lua 原子 check+扣减
- 状态：`_PENDING_TABS` 外移 Redis（结构化 payload + 幂等重填）
- 可观测：每运营者成功/失败/风控计数、登录态看板

**❌ Out of Scope（本期不做）**
- 加热平台运营者体系（独立子域，依赖蓝 V，单列 Phase 2）
- 合作作者（企业账户专属，依赖蓝 V，Phase 2）
- 24h 自动撤销时间窗的主动管理（微信侧自动处理，仅监控）
- 跨视频号的「矩阵级」统一调度（本期限定单视频号多运营者）
- 自动关注视频号等前置动作

### 2.3 非功能需求

| 类别 | 要求 |
|---|---|
| 并发与性能 | 单宿主下 ≥5 运营者 profile 并行（指**承载登录态与待发队列**并行，R20）；单运营者发布间隔随机 280–360s，**同 IP 共享时放大到 ≥30min**（R20），日上限按运营者配置（默认继承整号 20 条/天，可下探）；**IP 级总量约束（≤2 条/小时/出口 IP，R16）独立于 operator 级节奏，IP 触顶=毕业压力信号**；单 IP 下按小时窗错峰排班（R20） |
| 隔离与风控 | 各运营者 profile 完全独立 cookie/localStorage/UA，禁止串号；随机延迟 + 人工确认 + 限量（沿用一期反封号三件套）；**CDP 端口仅绑定 127.0.0.1** |
| 安全 | Cookie 沿用 AES-256/Fernet；运营者仅能解密/操作自己归属或授权的 profile；**发布执行点二次鉴权 + CDP 代理层鉴权**；审计日志「谁、对哪个运营者、何时发布」 |
| 可观测 | 登录态心跳（沿用 `check_cookie_status`）、每运营者成功率、风控告警 |
| 运维 | 不改 docker-compose 服务数量即可上线 Phase 1（复用单 rpa_worker）；端口/路由配置化，零硬编码 |
| **资源（补充 R10）** | 192.168.1.163 宿主内存需 ≥16G：15 个 Chromium profile ≈ 5-8GB + Postgres/Redis/MinIO/backend 等基础服务 ≈ 6-8GB；部署前须验证 |

### 2.4 约束
- **技术栈**：保持 FastAPI + Celery + Redis + Playwright/CDP + Docker Compose，不引入 K8s/新编排器（除非 Phase 3）。
- **部署**：单生产服务器 192.168.1.163，M3 MacBook 本地开发；沿用 `clip-deploy` 一键同步+重建。
- **合规**：微信风控红线不可触碰（限量 + 人工确认 + 随机延迟是硬性护栏）。

## 三、候选方案 A / B / C / D

四方案都建立在「复用一期 Publisher、复用 PublishProfile、复用截图审核」前提上，分歧只在**浏览器执行层如何 scale 登录态**。

- **方案 A · 单容器多 Profile 端口映射（演进式）**：保持 1 个 `rpa_worker`，`start_chromium.sh` 按 `PublishProfile` 启 N 个 Chromium，各自独立 `--user-data-dir` 与调试端口（9223/9224/…）；新增**账号→端口路由表**；`VideoChannelPublisher(chrome_debug_port=…)` 按账号取端口；`_PENDING_TABS` 外移 Redis；worker 并发提至可配 + 每账号信号量。
  - Pros：改造成本最低、零新增容器、复用预留钩子、最快上线。
  - Cons：单宿主资源争用、故障爆炸半径大、规模受单机约束（约 ≤10–15 profile）。
- **方案 B · rpa_worker 多副本 + 账号分片路由**：起 M 个副本，每副本承载一部分账号的 profile；中央路由做「账号→副本」映射。Pros：隔离好、水平扩展。Cons：路由/端口跨副本管理复杂、cookie/state 需共享卷或每副本持久化。
- **方案 C · 每运营者独立沙盒容器（小V猫式）**：1 运营者 = 1 二元组 = 1 轻量隔离 Chromium 沙盒。Pros：隔离/风控满分、规模化清晰。Cons：资源最重、编排最复杂、成本最高。
- **方案 D · 外接 BrowserGrid 服务**：浏览器层解耦成独立 BrowserGrid，管理持久 profile 池。Pros：关注点分离、动态扩缩。Cons：建设量最大、新增需长期运维的服务、过度设计。

**四方案速览对比**

| 维度 | A 单容器多Profile | B 多副本路由 | C 独立沙盒 | D BrowserGrid |
|---|---|---|---|---|
| 改造成本 | 低 | 中 | 高 | 最高 |
| 扩展性 | 中（单机 ≤15） | 较高 | 高 | 最高 |
| 隔离/风控 | 弱（同机） | 中 | 最强 | 强 |
| 运维复杂度 | 低 | 中 | 高 | 高 |
| 契合现有架构 | 高（复用钩子） | 高 | 中 | 中 |
| 时间到市场 | 快（周级） | 中 | 慢 | 最慢 |

## 四、圆桌评审（5 方 · 3 轮）

评审委员会：架构师(甲)、视频号运营专家(乙)、安全合规专家(丙)、后端工程师(丁)、产品经理(戊)。

**第一轮 · 开题立场与初评**
- **甲（架构）**：主张从 A 起步——把「设计意图」补完而非另起炉灶。但立红线：A 绝不能把端口写死、不能把 `_PENDING_TABS` 留进程内存、**不能把 CDP 端口暴露给非 127.0.0.1**。A 必须做到：路由表配置化、状态外移 Redis、每账号信号量、CDP 代理层鉴权。满足这四点，A 就是可演进的。
- **乙（运营）**：反对直接上 C，警惕 A 的「同机 N 个 Chromium」——微信看设备/网络指纹，同机同 IP 下 15 个号同时发易被判定矩阵搬号。但现有实际运营者就 4 个（flamen/摸鱼/袁皓/Benny），Phase 1 到不了 15。支持 A 起步，但配额必须按运营者维度、随机延迟拉大（280–360s）。C 是规模化后的终极形态，现在上太重。
- **丙（安全）**：无论选哪个，Phase 0 账号归属是硬前置。现在全局共享意味着任意运营者都能操作别人的号（越权漏洞）。必须加 `created_by/operator_id` 接 `own/all`。A 同机多 profile 要确保 cookie 文件按 profile 严格隔离，路由层不能串；**CDP 多端口无认证是新的攻击面，必须收敛**。
- **丁（后端）**：偏 A，但三点必须改：① `_PENDING_TABS` 进程内字典依赖 `concurrency=1`，提并发后丢 tab，必须外移 Redis（`task_id → {结构化 payload}`）；② 每账号信号量用 Redis 分布式锁，不靠进程内计数；③ Lua 配额脚本须处理 nil 兜底。
- **戊（产品）**：老板要「多运营者能发起来」尽快可用，不是完美网格。A 周级、B/C/D 月级。但 A 不能做成死胡同——要写清「什么信号触发毕业到 B/C」（运营者>8 或出现同机风控集中）。加热运营者独立成 Phase 2，别互相阻塞。

**第二轮 · 交叉质询与收敛**
- 乙 → 甲/丁：运维怎么知道哪个端口对应哪个运营者？建议路由表落 Redis Hash `account:<id> → {port, profile_dir, operator_id, daily_used, last_post_at}`，前端直接展示，别让人去翻 `docker exec`。
- 甲 → 乙：完全接住。路由表本就该是 Redis 单一事实源，前端读它渲染「运营者端口矩阵」看板，也顺手解决丙的审计需求（每次发布写 `operator_id + account_id + port + ts`）。
- 丙 → 戊：加一条安全阈值——单宿主同出口 IP 运营者 profile ≥8 且 7 日内 ≥2 次风控受限，强制毕业到 B/C。
- 戊 → 丙：同意，合并成「双触发毕业条件」。
- 丁 → 全体：收敛结论——Phase 0（账号归属）+ Phase 1（A：多 profile 端口、Redis 路由、Redis 状态 + 每账号信号量 + CDP 收敛）。B/C/D 作毕业目标保留。

**第三轮 · 加权评分矩阵与决胜**
权重（基于当前规模小、求快、求可演进）：落地速度 25% / 扩展性隔离 20% / 风控 20% / 运维 15% / 契合 10% / 价值 10%。

| 评分维度（权重） | A | B | C | D |
|---|---|---|---|---|
| 改造成本/落地速度 (25%) | 5 | 3 | 2 | 1 |
| 扩展性与隔离性 (20%) | 3 | 4 | 5 | 5 |
| 风控与反封号 (20%) | 3 | 4 | 5 | 4 |
| 运维复杂度 (15%，越高越省心) | 4 | 3 | 2 | 2 |
| 与现有架构契合 (10%) | 5 | 4 | 3 | 3 |
| 业务价值/时间到市场 (10%) | 4 | 4 | 4 | 5 |
| **加权总分** | **3.95** | **3.60** | **3.50** | **3.15** |

> **决胜解读**：A 以 3.95 居首，赢在低成本+快上线+高契合+可演进；B/C 紧随，代表规模化后正确形态；D 因过度设计垫底。**选 A 作 Phase 1，路线图锁定 B/C 为毕业目标**。

## 五、最终推荐方案与路线图

### 5.1 总体架构（Phase 1）
- 业务层：发布任务 API（指定 视频号+运营者集合）→ Celery publish 队列（每账号信号量 Redis）→ 前端人工确认。
- 路由层（新增）：Redis Hash `pub:route:<account_id>` → `{port, profile_dir, operator_id, daily_used, last_post_at, status}`，提供 `resolve_port(account_id)` 与 `acquire_slot(account_id)`（Redis 分布式信号量）。
- 浏览器宿主层（改造）：`start_chromium.sh` 遍历启用的 `PublishProfile`，按 `chrome_debug_port` 起独立 `--user-data-dir=/data/chrome-profiles/<profile_id>` 的 Chromium；调试端口 9223+N **仅绑定 127.0.0.1**，由 cdp_proxy 统一鉴权转发。
- 发布层（小改）：`get_publisher(platform, chrome_debug_port=resolve_port(acct))`；`_PENDING_TABS` 改 Redis 存结构化 payload；`worker-publish` 并发提至可配（默认 4），配额改「整号上限 AND 运营者上限」双闸门（Lua 原子）。
- 账号归属层（Phase 0）：`created_by/operator_id` + `own/all` 过滤 + 审计表 `publish_audit`。
- 前端：`PublishManagement.tsx` 增「运营者选择 / 均分·轮询·指定 策略」+「运营者端口矩阵」看板（读 Redis 路由）。

### 5.2 落地路线图（含毕业阈值）

| 阶段 | 内容 | 工期 | 毕业/触发条件 |
|---|---|---|---|
| **Phase 0** 账号归属 | `created_by/operator_id` + RBAC `own/all` + 审计表；不改浏览器层 | ~3 天 | 无（硬前置） |
| **Spike 0** QR 渲染验证（新增 R7） | headless Chromium 中微信登录二维码渲染验证（canvas/GPU），验证失败则改用「本机浏览器扫码 + cookie 注入」方案 | ~1 天 | 阻塞 Phase 1 开工 |
| **Phase 1** 方案 A | 多 profile 端口映射 + Redis 路由 + Redis 状态 + 每账号信号量 + 发布策略 + **CDP 端口收敛** | ~1–2 周 | **双触发毕业**：① 单宿主 profile ≥8；或 ② 7 日内 ≥2 次风控受限 → 强制 Phase 2/3 |
| **Phase 2** 加热运营者 + B 分流 | 蓝 V 企业账户开通后接入「加热运营者」（最多 15）；rpa_worker 多副本分片路由 | 视蓝 V 进度 | 依赖蓝 V 认证（真实账号主体变更，需用户操作） |
| **Phase 3** 方案 C/D | 运营者规模化 >15 或风控升级时，演进到独立沙盒 / BrowserGrid | 按需 | 规模或隔离要求越过 Phase 1/2 上限 |

> **毕业阈值（共识）**：Phase 1 不是妥协终点，而是带明确出口的演进路径。规模阈值（≥8 profile）与风控阈值（7 日 ≥2 次受限）**任一触发即强制毕业**。

## 六、风险与缓解（Part 1）

| 风险 | 等级 | 缓解 |
|---|---|---|
| 同机同 IP 多运营者号集中发布被微信风控 | 🔴 高 | 每运营者独立 profile + 随机延迟 280–360s + 人工确认 + 限量；双触发毕业兜底 |
| `_PENDING_TABS` 外移 Redis 后重连失败 | 🟠 中 | 保留现有 fallback（重新打开创作中心尽力点发布）；结构化 payload 冗余存储 |
| 账号越权（运营者操作他人号） | 🔴 高 | Phase 0 归属 + RBAC own/all；Cookie 解密按 operator_id 授权；发布执行点二次鉴权 |
| **CDP 多端口暴露（新增 R5）** | 🔴 高 | 调试端口仅绑定 127.0.0.1；cdp_proxy 统一鉴权入口；按 profile 独立代理实例 |
| 端口/路由硬编码导致无法演进 | 🟡 低 | 路由表 Redis 单一事实源、配置化；架构红线 |
| 单机 Chromium 资源争用（OOM） | 🟠 中 | 宿主内存 ≥16G；profile 数软上限 + 监控；达阈值即毕业 B/C |
| **换 IP 迁移需重登（新增 R6）** | 🟠 中 | 毕业流程内置「预计需重登」预期；人工介入节点；旧环境保留 24h |
| 蓝 V 认证阻塞加热运营者线 | 🟡 低 | 加热独立成 Phase 2，不耦合 |

## 七、附录（Part 1）

**关键代码/文档锚点（clip-workflow，已核实）**
- `backend/app/services/publish_service.py` — 插件式 Publisher（行 502 工厂、行 87 VideoChannelPublisher、行 122 CDP 连接读全局 `CHROME_DEBUG_HOST`、行 29 `_PENDING_TABS` 进程内）。
- `backend/app/api/publish.py` — 发布 + 账号矩阵 + 小程序库 API（938 行）。
- `backend/app/models/models.py` — `VideoAccount`（行 374）/`PublishProfile`（行 464，含 `chrome_debug_port` 默认 9222）/`PlatformProfile`（行 357）；缺 `created_by/operator_id`。
- `rpa/start_chromium.sh` — 单实例单 profile，`--remote-debugging-port=9223`（行 57）、单 user-data-dir（行 62）。
- `rpa/cdp_proxy.py` — 单实例 9222→9223 双向 Host 改写。
- `docker-compose.yml` — rpa_worker（行 370，挂 `chrome_profiles` 卷行 401）、`CHROME_DEBUG_HOST`（行 36-37）、`worker-publish --concurrency=1`（行 330）；**17 个服务**；Redis 仅 requirepass 无 ACL。
- `PROJECT.md §8.3` — 多账号支持（设计意图，未实现）。
- `PROJECT.md §12.4` — RPA Cookie AES-256/Fernet 加密（`auth.py` 行 298-316）。

**圆桌权重**：落地速度 25% / 扩展性隔离 20% / 风控 20% / 运维 15% / 契合 10% / 价值 10%。

---

# Part 2 · 加固设计评审（圆桌多轮收敛）

> 在 Part 1 基础上，对 8 个可细化主题做多角色多轮深挖，目标：把方案抠到「稳固可控」——优先失败模式、竞态、风控、回滚。
> 形式：2 路独立红队（安全/风控 + 后端/SRE）+ 6 角色（架构/运营/安全/后端/产品/测试）× 3 轮。

## 零、独立红队评审结论

**红队 A · 安全合规 / 微信风控**
- **登录态上架**：远程运营者看不到服务端 Chromium 里的二维码，经不安全通道下发会被中间人顶替登录；单号失效若用全局锁会阻塞他人。→ 加固：服务端 CDP 抽真实 QR PNG → 带 operator_id、单次、TTL 90s 加密通道下发；每 profile 独立心跳 30min，失效仅置 NEED_LOGIN 进独立扫码队列。
- **越权与隔离**：publisher 直读 Redis 路由表 resolve_port 会绕过 API 层 RBAC；Fernet 单密钥全局共享，泄露=全量沦陷。→ 加固：发布执行点二次鉴权（短期 token）；Cookie 改 per-operator 派生密钥；profile dir 750 权限/独立 volume；Redis namespace+ACL（落地时新增 `--aclfile` 配置）。
- **微信风控**：同机同出口 IP 多号集中发=矩阵搬号信号；多 profile 默认共享 UA/指纹会被聚类；均分发同视频同 hash 跨号=搬运命中。→ 加固：每 operator 独立出口 IP（毕业触发）；每 profile 绑定固定随机 UA+指纹 seed，禁 WebRTC；均分强制内容变体（封面 3–5 套、文案同义随机化、改 hash）。
- **审计**：仅记「谁发的」缺 IP/指纹/内容 hash，无法定位风控根因。→ 加固：审计表补全 source_ip/egress_ip/ua_seed/content_hash/cover_variant。

**红队 B · 后端 / SRE 稳定性**
- **并发竞态**：DB 行锁只锁单号，整号+运营者双闸门跨号聚合非原子。→ 加固：配额计数迁 Redis + Lua 原子 check+扣减（**nil 兜底**）；per-operator 信号量默认 1、全局并发可配；先抢 op 再抢 global、释放逆序、全带 TTL。
- **_PENDING_TABS 外移**：缓存 Playwright page 对象随连接死即废。→ 加固：只存结构化 payload（account/profile/cdp_url/targetId/表单值/游标），confirm 重连后**全量幂等重填**，杜绝半填；TTL 30min。
- **路由表生命周期**：注册时机不清、重启端口漂移、占坑冲突。→ 加固：Profile enabled 即注册；端口池 Lua SADD 原子分配+记 owner；rpa_worker 启动按表重建；watcher 探 `/json/version`，expired 走关→SREM→重连→ready。
- **灰度与回滚**：flag 侵入旧路径、迁移锁表。→ 加固：flag 走 Redis 热更，false 时 resolve 直取原端口、零侵入；列 ADD COLUMN DEFAULT NULL 瞬时不锁表；回滚关 flag 即可。
- **失败处理**：任务中途跨 operator 迁移致配额错乱。→ 加固：任务创建即绑定 operator 不迁移；失效直入死信不换号；重试分级（CDP 抖动可重试≤2 次指数退避，配额/风控直死信）。

> 两路红队一致结论：**「可控性」命门不在功能能不能做，而在失败/并发/越权时是否优雅降级、可回退、可溯源**。

## 一、圆桌第 1 轮 · 风险认领与优先级

- **丙（安全）**：红队 A 的「发布执行点二次鉴权」和「Cookie per-operator 派生密钥」列为 **P0 必做**——现状 publisher 直读 Redis 路由表等于架空 RBAC，任何能连 Redis 的 worker 都能发到别人号。审计补全 IP/指纹/hash 也是 P0。
- **丁（后端）**：认领并发竞态与路由表生命周期，都是 **P0**。Lua 原子配额（含 nil 兜底）+ 端口池 SADD 硬需求；_PENDING_TABS 幂等重填多花 3–5s/条，值得；回滚/灰度零侵入是 P0 的「安全网」。
- **乙（运营）**：登录态自服务扫码 + 独立心跳是 **P0**（4 个运营者异地，admin 不可能替每个人扫码）；均分强制内容变体、每 operator UA/指纹 seed 也 P0；独立出口 IP 延后到毕业阈值触发（**P2**），Phase 1 同机先跑。
- **甲（架构）**：补一条跨领域铁律 P0：**单条任务创建即绑定单一 operator，全程不迁移**——同时封堵「跨号配额错乱」「同视频多号发风控」「重试换号重复」三处雷。另补 P0：**CDP 端口收敛**——调试端口仅绑定 127.0.0.1，代理层统一鉴权。
- **戊（产品）**：P0 收敛为「上线阻断项」：二次鉴权、Lua 配额、登录态自服务、灰度零侵入回滚、单任务绑定 operator、CDP 端口收敛。P1：内容变体/UA指纹/审计/死信分级。P2：独立 IP/合作作者/加热运营者。
- **己（测试）**：要求每个 P0 配「可证伪」验收标准，否则落不了地。

> **第 1 轮共识**：P0 = 二次鉴权 + Lua 原子配额 + 登录态自服务/心跳 + 灰度零侵入回滚 + 单任务绑定 operator + CDP 端口收敛；P1 = 内容变体/指纹/审计/死信分级；P2 = 独立 IP/加热/合作作者。每个 P0 必须配可证伪验收。

## 二、圆桌第 2 轮 · 八主题逐一拍板

**主题 1 · 登录态生命周期与自服务上架（丁/丙）**
流程：① admin 录入 PublishProfile(operator_id)；② 系统用 CDP 从对应 profile 抽真实登录 QR PNG → 加密存 MinIO，生成带 operator_id、**单次使用、TTL 90s** 的领取链接；③ operator 在 Web/App 内扫码 → 微信确认 → 心跳置 ready；④ 每 profile 独立心跳 **30min** 探创作中心 200+关键 cookie，失效仅置 NEED_LOGIN 进独立扫码队列，**不阻塞**其他 operator；⑤ 每日 ≥1 次静默访问续活。
约束：**operator_id 必须=微信号主人，created_by 仅记操作人**。
⚠️ 前置 Spike（R7）：先验证 headless Chromium 中二维码渲染可行性；失败则退化为「本机浏览器扫码 + cookie 注入回传」方案。

**主题 2 · 配额双闸门 + per-operator 信号量（Lua 原子）（丁）**
配额计数从 DB 行锁迁 Redis，Lua 原子 check+扣减。per-operator 同时发布默认 **1**（防同号并发风控），全局并发默认 **4**（可配）。先抢 op 再抢 global，释放逆序，全带 TTL（daily TTL=当日剩余秒，inflight TTL=任务超时 30min）。

```lua
-- KEYS: acct, op, op_inflight, global_inflight
-- ARGV: al_acct, al_op, op_limit, global_limit, ttl_acct, ttl_inf
local used = tonumber(redis.call('HGET', KEYS[1], 'daily_used')) or 0
local op   = tonumber(redis.call('GET',  KEYS[2])) or 0
local oinf = tonumber(redis.call('GET',  KEYS[3])) or 0
local ginf = tonumber(redis.call('GET',  KEYS[4])) or 0
if (used + 1 > tonumber(ARGV[1])) then return 0 end
if (op   + 1 > tonumber(ARGV[2])) then return 0 end
if (oinf + 1 > tonumber(ARGV[3])) then return 0 end
if (ginf + 1 > tonumber(ARGV[4])) then return 0 end
redis.call('HINCRBY', KEYS[1], 'daily_used', 1); redis.call('EXPIRE', KEYS[1], ARGV[5])
redis.call('INCR', KEYS[2]); redis.call('INCR', KEYS[3]); redis.call('INCR', KEYS[4])
redis.call('EXPIRE', KEYS[3], ARGV[6]); redis.call('EXPIRE', KEYS[4], ARGV[6])
return 1
```

> ⚠️ 修订（R8）：所有 `GET/HGET` 结果先 `tonumber(...) or 0`，杜绝 nil 算术报错。

验收（己）：4 worker、每 operator 上限 5、全局 20，压 24h 断言各 op.daily_used ≤5 且 global ≤20，零超发。

**主题 3 · Redis 路由表 schema + 生命周期 + 端口分配（丁）**
schema：`pub:route:<account_id>` = hash `{port, profile_dir, operator_id, status(ready|logging|expired|disabled), daily_used, last_post_at, ua_seed, proxy(null), egress_ip(null)}`。
注册：Profile **enabled 即写**路由（status=logging）。端口池 `pub:ports` 用 Lua **SADD 原子分配 + 记 owner**，基址 9223（对齐 `start_chromium.sh` 现状），重启不漂移。rpa_worker 启动读 ready/logging 项按 profile_id 重建。watcher 周期探 `/json/version`；expired 流程：关 Chromium → SREM 端口 → 按 profile 起重连 → 健康后置 ready。

**主题 4 · _PENDING_TABS 外移 Redis（幂等重填）（丁/甲）**
Redis 只存结构化 payload：`account_id, profile_id, cdp_url, CDP targetId, 表单字段值(标题/描述/标签/封面key/小程序link), 填表游标, TTL 30min`。
confirm：按 route 重连 CDP → attach targetId（失活则新建 tab）→ **全量幂等重填**（清空再填）→ 点发布。放弃缓存 page 对象，牺牲 3–5s/条换绝不半填/绝不失效。
⚠️ 补充（R11）：填表游标对页面结构敏感，selector 集中管理并带版本号；微信改版时快速热修。
⚠️ 修订（R18）：confirm 重填前先校验 `selector_version` 与当前页面匹配，不匹配即**冻结该 pending + 人工介入**（热修 selector 版本 或 回退截图人工确认），绝不静默乱填（详见 4.4）。

**主题 5 · 发布策略语义（均分/轮询/指定）+ 跨号去重（乙）**
三条策略只在**批次级**决定每条落哪个 operator，落定不迁移。均分**强制内容变体**：封面 3–5 套轮替、文案同义随机化、首帧/码率微调改 hash，**禁止完全相同文件跨号**。轮询：新视频按顺序给下一个可用（未限额/未失效）operator。指定：管理员手动。
⚠️ 补充（R11）：封面来源明确为「运营预置素材库（≥3 套/剧）+ 系统随机轮替」，前端可上传维护；调度器读取路由表 `status=ready` 才参与轮询/均分，`expired/disabled` 自动跳过。
验收（己）：均分模式同批次导出 N 条，断言 N 个 operator 各得 1 条且 content_hash 互不相同。

**主题 6 · 风控护栏量化（指纹 / 节奏 / 独立 IP）（乙）**
每 operator 绑定**固定随机 UA + 指纹 seed**（Canvas/WebGL/audio/字体）防聚类，**禁 WebRTC** 防真实 IP 泄露。节奏：随机延迟 **280–360s** + 跨号抖动，分散早中晚；单 IP 小时 ≤2 条，单宿主留冗余。独立出口 IP 留到毕业阈值触发（路由表 proxy/egress_ip 字段已预留）。
⚠️ 澄清（Part 3 承认真实性）：stock Chromium 的 JS 层指纹随机化对微信 C++ 层检测**基本无效**，Tier 0 指纹工作的定位是「防普通聚类」，不防深度检测；真正隔离靠 IP，别对 Tier 0 期望过高。

**主题 7 · 灰度开关 + 回滚 + 迁移向后兼容（丁/丙）**
flag `MULTI_OPERATOR_ENABLED` 走 Redis 热更，false 时 `resolve_port` 直取 `PublishProfile.chrome_debug_port`、路由表不生效、**零侵入**旧链路。DB：`ADD COLUMN created_by/operator_id DEFAULT NULL`（瞬时、不锁表），旧号 backfill NULL/创建者。回滚：关 flag 即可；route 表保留不清。
丙补：resolve 前 app 层签**短期 token(operator_id+account_id+单次 scope)**，worker 校验通过才连 CDP，防绕过 API RBAC 直读 Redis。

**主题 8 · 审计与可观测（丙）**
`publish_audit` 记：account_id / operator_id(号主) / actor_id(操作人) / profile_id / content_hash / cover_variant / copy_template / source_ip / egress_ip / ua_seed / port / action / result / risk_flag / request_id / ts。
另立 `login_audit`（QR 领取人/扫码人/TTL）、`cookie_access_log`（读时间/者/用途）、`risk_event`（受限类型/处置）驱动毕业统计。全链路 trace_id 串联审核→确认→发布→风控回执。
验收（己）：任一发布事件可凭 request_id 拉出完整链路，含 operator/actor/IP/hash。

## 三、圆桌第 3 轮 · 决策清单与验收

**稳固可控设计决策清单（摘要）**

| # | 决策 | 优先级 | 关键规格 | 验收（可证伪） |
|---|---|---|---|---|
| 1 | 登录态自服务 + 异步心跳 | **P0** | QR TTL 90s、独立心跳 30min、失效仅置 NEED_LOGIN 不阻塞、每日静默续活；**前置 QR 渲染 Spike** | 1 operator 过期，其余 3 个发布成功率 100% 不受影响 |
| 2 | 配额双闸门 Lua 原子 + 信号量 | **P0** | Lua check+扣减（nil 兜底）、per-op 并发 1、全局 4、全 TTL、**inflight 绑定任务自然释放（R22）** | 4 worker 24h 压测零超发（op≤上限 & global≤上限）；日切点 in-flight 不误顶次日配额 |
| 3 | 单任务绑定 operator 不迁移 | **P0** | 创建即定 operator，重试不换号 | 同批次导出 N 条，每 operator 各 1 条，无跨号重发 |
| 4 | 发布执行点二次鉴权 | **P0** | resolve 前签短期 token(actor+account+单次 scope)，**经 task payload 下发、worker 握手前注入 Authorization 头（R19）** | 直读 Redis 伪造请求被拒，RBAC 不可绕过；无/过期/scope 不符 token 被 401 |
| 5 | 灰度零侵入 + 一键回滚 | **P0** | flag Redis 热更、false 直取原端口、路由表留不清 | 关 flag 5min 内旧链路行为零变化 |
| 6 | **CDP 端口收敛** | **P0** | 调试端口仅绑定 127.0.0.1；cdp_proxy 按 profile 多实例 + 鉴权 | 内网其他主机无法直连任何调试端口 |
| 6b | **路由表秒级失效闭环** | **P0** | watcher 10s 探 `/json/version`，连续 2 次失败置 expired 跳过调度；30min 心跳仅管登录态 | 模拟 Chromium 崩溃 ≤30s 路由表置 expired（R12） |
| 7 | 路由表 schema + 端口池 | **P1** | enabled 即注册、SADD 原子分配、重启不漂移、watcher 重建、存量 9222 归一（R15） | rpa_worker 重启后端口映射与重启前一致 |
| 8 | _PENDING_TABS 幂等重填 | **P1** | 结构化 payload、TTL 30min、confirm 全量重填、selector 版本化 + **前置校验（R18）** | worker 重启后 confirm 仍可成功；selector 不匹配时冻结+人工介入 0 误发 |
| 9 | 风控指纹/节奏/变体 | **P1** | UA+指纹 seed、禁 WebRTC、280–360s、单 IP≤2/h（**同 IP operator 延迟放大 ≥30min + 排班错峰，R20**）、均分强制变体 | 同机 4 号连发 7 日风控受限 ≤1 次；单 IP 任一小时窗全 IP ≤2 条 |
| 10 | 审计 + 可观测 | **P1** | publish/login/cookie/risk 四类日志 + trace_id | 任意 request_id 可溯源 operator/actor/IP/hash |
| 11 | 独立 IP / 加热 / 合作作者 | **P2** | 路由表预留 proxy/egress_ip，毕业阈值触发（成本按 ￥30-50/月/个 测算） | Phase 2 范围，本期不验收 |

> 甲（主席）：8 主题全部拍板，无遗留分歧。Part 1 的演进式路线（Phase 0→1→毕业）不变，但 Phase 1 落地**必须**携带本 Part 全部 P0 护栏，否则宁可不上。

## 四、最终加固规格（主题 1–4，可执行）

**4.1 登录态生命周期**
```
状态机: disabled → logging(已录入待扫) → ready(心跳OK) → expired(心跳失败)
                                          ↘ NEED_LOGIN(扫码队列)
- admin 录入 PublishProfile(operator_id, video_account_id)
- 系统: CDP 抽 QR PNG → 加密存 MinIO → 生成 领取链接(operator_id, single-use, TTL=90s)
- operator: Web/App 内扫码 → 微信确认 → 心跳置 ready
- watcher: 每 profile 独立 30min 探 /platform 200 + 关键 cookie
   ├ 成功 → ready（每日≥1次静默访问续活）
   └ 失败 → expired/NEED_LOGIN（仅该 operator 进扫码队列，不阻塞他人）
约束: operator_id == 微信号主人; created_by == 操作人(仅审计)
前置: QR 渲染 Spike（R7）验证通过后实施
```

**4.2 配额双闸门（Lua，见主题2 伪代码，含 nil 兜底）**
- 计数存储：`pub:acct_used:<acct>`（hash daily_used，TTL=当日剩余秒）、`pub:op_used:<op>`、`pub:op_inflight:<op>`（默认上限1）、`pub:global_inflight`（默认4）。
- 获取顺序：先 op 信号量 → 再 global；释放逆序；inflight TTL=任务超时（30min），防崩溃泄漏。
- **inflight 跨日边界语义（R22）**：`op_inflight/global_inflight` 是**任务级并发闸门**，只约束「同一时刻进行中的发布数」，与日累计配额无关——因此**不设跨日归零**，而是**绑定任务生命周期随任务结束自然释放**（成功/失败/超时/死信均 release）。
  - `daily_used`（整号）与 `op_used`（运营者）才是日累计配额，其归零靠 TTL=当日剩余秒自然过期（跨日即失效重建）；
  - 日切点（00:00）有 in-flight 任务属正常并发，其 `inflight` 计数会跨日残留到该任务结束/超时（≤30min）才释放，**不会**顶到次日 `daily_used` 配额（两者是不同 key 维度）；
  - 若期望「次日配额严格从 0 起算」，仅需保证 `daily_used`/`op_used` 的 TTL 按自然日对齐（写入时即设当日剩余秒），inflight 无需也不应清零，避免把进行中任务误判为配额。
  - 运维提示：Lua 中 `daily_used` 用「当日剩余秒」作 TTL，跨日自动重建为 0；`op_used` 同理由 `op_limit` 对应 TTL 兜底，二者均不依赖 cron 手动清零。
- 双闸门：整号上限（沿用 20/天）AND 运营者上限（可下探，默认继承或更低）。

**4.3 Redis 路由表**
```
pub:route:<account_id> (hash):
  port          int        # 持久化，重启不漂移（端口池分配后写回，基址 9223）
  profile_dir   str        # /data/chrome-profiles/<profile_id>
  operator_id   str        # 微信号主人
  status        enum       # ready | logging | expired | disabled
  daily_used    int        # TTL=当日剩余秒
  last_post_at  ts
  last_heartbeat ts       # R12: Chromium 进程级心跳，watcher 探测更新时间
  ua_seed       str        # 指纹种子
  proxy         str|null    # 预留出口代理（Phase 2）
  egress_ip     str|null    # 预留独立 IP（毕业触发）

pub:ports (set): 已分配端口池，Lua SADD 原子分配 + 记 owner 防重复，基址 9223
注册: PublishProfile enabled → 写路由(status=logging)
启动: rpa_worker 读 ready/logging 项 → 按 profile_id 起 Chromium(端口取表值，--remote-debugging-address=127.0.0.1)
expired: 关 Chromium → SREM 端口 → 按 profile 起重连 → 健康后置 ready

失效检测闭环（R12）:
  - watcher 每 10s 对每条 ready 路由探 http://127.0.0.1:<port>/json/version
  - 探活成功 → 更新 last_heartbeat；连续 2 次失败（≈20s）→ 置 expired + 通知调度跳过
  - 30min 心跳仅用于「登录态」级别（cookie 有效性），与进程级 10s 探活解耦，两层互不替代
```

**4.4 _PENDING_TABS 幂等重填**
```
Redis 存 (key=pub:pending:<task_id>, TTL=30min):
  {account_id, profile_id, cdp_url, target_id, title, desc, tags[], cover_key, miniprogram_link, cursor, selector_version}
confirm(task_id):
  route = resolve(account_id); browser = connect_cdp(route.cdp_url)
  page = attach(target_id) or browser.new_page()
  if not selector_ok(page, payload.selector_version):  # R18 前置校验
      freeze(pending); risk_event('selector_mismatch'); manual_intervene(); return
  fill_clear_then_set(title, desc, tags, cover, miniprogram)  # 全量幂等
  click_publish(); wait_success()

selector 版本兜底（R18）:
  - confirm 重填前先校验当前页面结构是否匹配 payload.selector_version（以页面关键 DOM 哨兵/表单控件存在性为判据）
  - 匹配 → 继续全量幂等重填；不匹配（微信改版/页面异常）→ 立即冻结该 pending（置 selector_mismatch），不改写任何表单，通知人工介入
  - 人工介入两选一：① 升级 selector 版本并热修复 → 解冻重试；② 回退到一期「截图+人工确认」兜底 → 手动完成或置 failed
  - 铁律：selector 校验失败时**绝不静默跳过字段或乱填**，避免半填发布到错误账号；该 pending 冻结期间调度不重试、不换 operator

cover_key 语义（R13）:
  - payload 中的 cover_key 必须是「已上传到 MinIO 后的持久 object key」（如 covers/<batch_id>/<variant>.jpg）
  - 重填时从 MinIO 取 presigned URL 回填封面选择器，不依赖任何临时本地文件
  - 封面 object 保留策略与切片成品一致（任务确认后按全局清理策略，默认 90 天），不随 pending 记录 TTL 删除
  - 若 cover_key 已失效（对象不存在）→ confirm 阶段直接置任务 failed 并人工介入，不静默跳过封面
```

**4.5 CDP 端口层安全设计（新增 R5）**
```
问题: CDP 协议无认证，任何能访问调试端口的主机都能操控浏览器
方案:
  1. 所有 Chromium 启动参数加 --remote-debugging-address=127.0.0.1（仅本机可连）
  2. cdp_proxy 按 profile 起多实例，各监听不同外露端口（9222+profile 序号）
  3. cdp_proxy 增加鉴权中间件: 请求头携带短期 token（由 app 层签发，actor+account+scope，R17）
  4. 端口分配表与代理实例一一对应，路由表 port 字段指向 cdp_proxy 鉴权口而非 Chromium 原生口
验收: 内网其他主机直连调试端口被拒；经代理携带有效 token 才可连接

token 注入链路（R19，R17 的落地点）:
  端到端传递链: app 层签发 token → 随 task payload 下发 → worker 在 CDP 握手前注入 → cdp_proxy 校验 → 转发到 Chromium
  1) 签发: app 层在确认发布/创建任务时，为本次操作签短期 token，载荷含 actor_id + account_id + 单次 scope（一次会话，防重放），TTL 建议 60s
  2) 下发: token 写入 task payload（与 Redis `pub:pending:<task_id>` 一并落库/下发，随 Celery 消息与 Redis 状态传递，不单独明文暴露）
  3) 注入: worker 在 `VideoChannelPublisher.connect_over_cdp(route.cdp_url)` 建立 CDP 连接前，通过 HTTP 头（`Authorization: Bearer <token>`）注入到对 cdp_proxy 的请求中
  4) 校验: cdp_proxy 鉴权中间件解析并校验 token（签名、过期、scope 与目标 account 匹配），通过则转发到 `127.0.0.1:<port>` 的 Chromium 原生口，失败返回 401 并记审计
  5) 落地改动: `connect_over_cdp`（publish_service.py:122）增加 token 注入参数；cdp_proxy 增加鉴权中间件；token 校验用共享密钥（与 cookie 派生密钥同源但独立用途）
```

## 五、最终加固规格（主题 5–8，可执行）

**5.1 发布策略语义（含 Batch 模型，R14）**
```
模型分层（R14）:
  publish_batches (批次表): id, created_by(操作人), strategy(均分|轮询|指定),
    account_id, total_items, status, created_at
  publish_tasks (任务表): id, batch_id FK, operator_id(号主), account_id,
    content_hash, cover_variant, copy_template, status,  -- 每 task 绑定单一 operator

铁律细化:
  - 「单任务绑定单一 operator 不迁移」= publish_tasks.operator_id 创建后不可变（task 级）
  - 「均分/轮询/指定」= 仅在创建 batch 时决定每条 task 的 operator_id（batch 级分配逻辑）
  - 一次 API 请求 = 1 个 batch；batch 下 N 个 task；重试/死信均在原 task 内，不跨号
```
- **均分**：batch 级轮转分配，每条 task 落一个 operator；**强制内容变体**——封面 3–5 套轮替（来源：运营预置素材库 + 系统随机轮替）、文案同义随机化、首帧/码率微调改 hash；禁止完全相同文件跨号。
- **轮询**：新 batch 按顺序给下一个可用（未限额/未失效，读取路由表 status=ready）operator。
- **指定**：管理员手动指定 operator。
- **失败分级**：CDP 抖动可重试（重连同 operator Chromium ≤2 次，指数退避 30s/120s）；配额/风控不可重试，直入死信不换号。

**5.2 风控护栏**
- 每 operator 绑定固定随机 UA + 指纹 seed（Canvas/WebGL/audio/字体）防聚类（定位：防普通聚类，非防深度检测）。
- 禁用 WebRTC（防真实 IP 泄露）。
- 节奏：随机延迟 280–360s + 跨号抖动，分散早中晚；单 IP 小时 ≤2 条，单宿主总产出留冗余。
- **"单 IP 小时 ≤2 条"口径（R16）**：按**出口 IP 汇总**（同一出口 IP 下全部 operator 合计 ≤2 条/小时），与 operator 级 280–360s 随机延迟是**两层独立约束**（operator 内节奏 + IP 级总量）；当 4+ 个 operator 同机并行触发 IP 级触顶时，**这恰是毕业压力信号**（触发独立 IP），不是设计矛盾——NFR 中"≥5 运营者并行"以"多 IP/毕业承接"为前提。
- **单 IP 可执行排班示例（R20）**：单 IP 容量 = 2 条/小时（R16），因此「≥5 运营者并行」在**单 IP 下物理不可达**，必须把「并行」落到**批次日调度**而非「同一分钟并发」。以下为 1 个出口 IP + N 个 operator 的排班模板（每小时整窗 2 条）：
  ```
  小时窗 0-30min : 允许 2 个 operator（A 槽、B 槽）各发 1 条，时间点随机错峰（如 A@:05、B@:22）
  小时窗 30-60min: 空置（留给下一小时窗起始 & 抖动余量），避免窗口边界叠发
  operator 级节奏: 同 IP 下 operator 级随机延迟从 280-360s 放大到 ≥30min（见下）
  单 operator 天配额: 按 2条/小时÷N 均摊给 N 个 operator（如 N=4 → 每 op 约 12条/天 上限）
  ```
  - **同 IP operator 级延迟放大规则（R20）**：当多个 operator 共享同一出口 IP 时，单个 operator 的最小发布间隔**从 280–360s 放大到 ≥30min**（同号防风控），配合 IP 级「每小时 ≤2 条」双闸门；调度器按 IP 分组做时间窗错峰切分，确保任一小时窗内全 IP 合计 ≤2 条。
  - **NFR"≥5 运营者并行"落地口径（R20）**：该 NFR 指「系统能同时承载 ≥5 个运营者的登录态与待发布队列」，而非「同一分钟并发发布 ≥5 条」；真正的高并发发布须由毕业到多 IP（Tier 1+，每 IP 独立 ≤2条/时）承接——单 IP 下按上表错峰排班，N 个 operator 的吞吐由「小时窗 × 天窗口」分摊。
- 独立出口 IP：Phase 1 同机（成本），路由表 proxy/egress_ip 已预留；毕业阈值（profile≥8 或 7日≥2 次受限）触发强制独立 IP/沙盒。

**5.3 灰度 / 回滚 / 迁移**
- flag `MULTI_OPERATOR_ENABLED` 走 Redis 热更；false 时 resolve 直取原端口、路由表不生效、零侵入旧链路。
- DB：`ADD COLUMN created_by/operator_id DEFAULT NULL`（瞬时、不锁表）；旧号 backfill NULL/创建者。
- **存量端口归一（R15）**：flag=true 时，迁移脚本把存量 `chrome_debug_port=9222` 的 profile 显式归一进端口池（9223+，SADD 分配 + 写回路由表），原 9222 端口不再由任何 profile 使用；迁移完成前新调度跳过这些 profile，杜绝"池外裸 Chromium"窗口。
- 回滚：关 flag 即可；route 表保留不清，旧链路口令单端口脚本共存。
- 发布执行点二次鉴权：resolve 前 app 层签短期 token(**actor_id**+account_id+单次 scope)（R17），worker 校验通过才连 CDP。
- **actor/operator 分离（R17）**：token 身份 = 操作人 actor_id（发起的 user，含 publisher 代发 operator 号的场景）；operator_id 仅用于审计与配额维度，不做身份校验。鉴权链 = RBAC 数据范围判 actor 有无权操作该号 → token 签 actor → worker 校验 token。
- **CDP 层**：Chromium 仅绑定 127.0.0.1；cdp_proxy 鉴权转发（见 4.5）。

**5.4 审计与可观测**
```
publish_audit: id, task_id, account_id, operator_id(号主), actor_id(操作人),
  profile_id, content_hash, cover_variant, copy_template, source_ip,
  egress_ip, ua_seed, port, action(publish|confirm|fail|reauth),
  result, risk_flag, request_id, ts
login_audit: qr领取人, 扫码人, ttl
cookie_access_log: 读时间, 者, 用途
risk_event: 受限类型, 处置        # 驱动毕业统计
全链路 trace_id 串联 审核→确认→发布→风控回执
```
看板建议：① 运营者端口矩阵（读 pub:route 渲染 port/status/operator/限额消耗）；② 每 operator 成功率/风控计数/inflight；③ 告警：operator 失效、配额≥90%、pending 超时、Chromium OOM。

## 六、稳固可控验收标准（Definition of Done）

| 维度 | 可证伪验收 |
|---|---|
| 向后兼容 | flag=false 时单运营者旧链路行为零变化（回归测试全绿） |
| 隔离不阻塞 | 任 1 operator 过期/失效，其余 operator 发布成功率 100% 不受影响 |
| 配额精确 | 4 worker 并发 24h 压测，各 op.daily_used ≤ 上限 且 global ≤ 上限，零超发 |
| 可回退 | 关 flag 后 5 分钟内旧链路恢复，路由表留而不清无副作用 |
| 可溯源 | 任意 request_id 可拉出 operator/actor/IP/content_hash 完整链路 |
| 可恢复 | worker 重启后 confirm 仍成功（不依赖进程内 _PENDING_TABS） |
| 抗越权 | 直读 Redis 伪造发布请求被二次鉴权拒绝，RBAC 不可绕过；publisher 代发 operator 号时 token 以 actor 身份校验（R17） |
| **CDP 收敛** | 内网其他主机无法直连任何调试端口；仅经 cdp_proxy 携带有效 token 可连 |
| **失效秒级感知** | 模拟 Chromium 崩溃，路由表 ≤30s 内置 expired，调度跳过该 operator（R12） |
| **cover 重填** | 上传封面 → 任务重启 → confirm 仍能回填封面成功（R13） |
| **selector 兜底** | 注入 selector_version 不匹配场景，confirm 应冻结该 pending 且不改写表单、置 selector_mismatch 并触发人工介入，0 条误发/半填（R18） |
| **token 注入链路** | 无 token / 过期 token / scope 不匹配的 CDP 请求一律被 cdp_proxy 401 拒绝，合法 token 可正常发布（R19） |
| **同 IP 排班** | 单 IP 下模拟 4 operator 排班，任一小时窗全 IP 发布合计 ≤2 条，operator 级间隔 ≥30min（R20） |
| 抗风控 | 同机 4 号连发 7 日，风控受限 ≤1 次（配合变体+指纹+节奏） |
| **混沌演练（故障注入联调）** | 上线前强制演练：依次注入「Chromium 崩溃 / Redis 重启 / worker 重启」，全链路自愈（路由 expired→调度跳过→重连→ready）时间 ≤ X 且 **0 条误发、0 条重复**（R21） |

## 七、落地优先级与残余风险（Part 2）

- **P0 ×7**：二次鉴权（含 token 注入链路 R19）/ Lua 配额（含 inflight 跨日边界 R22）/ 登录态自服务 / 灰度回滚 / 单任务绑定 / CDP 端口收敛 / **路由表秒级失效闭环（R12）**
- **P1 ×5**：路由表 / 幂等重填（含 cover 语义 R13 + **selector 兜底 R18**）/ Batch 模型（R14）/ 风控变体（含**同 IP 排班 R20**）/ 审计
- **P2 ×2**：独立 IP / 加热 / 合作作者（Phase 2）+ 存量端口归一迁移（R15，Phase 1 内完成）
- **上线前强制演练 ×1**：混沌演练（Chromium 崩溃 / Redis 重启 / worker 重启全链路自愈，0 误发 0 重复，R21）

| 残余风险 | 等级 | 处置 |
|---|---|---|
| 微信改版导致 CDP 选择器失效 | 🟠 中 | 沿用一期「截图+人工确认」兜底；选择器集中管理+版本化；**confirm 前置 selector 校验（R18）→ 不匹配即冻结 + 人工介入，绝不乱填** |
| 同机同 IP 规模化后被限流 | 🟠 中 | 双触发毕业阈值（profile≥8 或 7日≥2 次受限）强制独立 IP/沙盒 |
| 运营者微信退出/解绑 | 🟡 低 | 心跳检测 NEED_LOGIN + 通知对应 operator 重新扫码；不阻塞他人 |
| Redis 路由表单点 | 🟡 低 | Redis 本身高可用；路由表可重建（Profile enabled 即重注册），丢失可恢复 |
| Cookie 密钥泄露 | 🔴 高 | per-operator 派生密钥 + KMS 按需拉取不落盘 + cookie_access_log 审计 |
| **换 IP 后登录态失效** | 🟠 中 | 毕业迁移内置「预计需重登」预期；人工介入节点；旧环境保留 24h 可回滚 |

> 本 Part 2 是 Part 1「演进式收敛路线（Phase 0→1→毕业）」的**强制补充规格**。Phase 1 交付物 = Part 1 功能范围 + 本 Part 全部 P0 与 P1。未携带 P0 护栏的 Phase 1 一律不准 release。

---

# Part 3 · 毕业到独立 IP / 沙盒（实现设计）

> 把 Part 1/2 的「Tier 0 同机多 profile」出口，收敛成可自动升级的隔离分级体系。

## 1 · 概念澄清：什么叫「毕业」

一个运营者账号的「运行环境」是一个三元组：

```
Env = {
  profile_dir : "/data/chrome-profiles/<profile_id>"   # cookie/localStorage/登录态
  egress_ip   : "192.168.1.163"                        # 出口 IP（微信看到的是这个）
  device_fp   : "{ua, tz, webgl, canvas, audio, fonts}" # 设备指纹
}
```

**毕业 = 在风控压力到达前/时，把这个三元组从「共享」升到「独占」。**
- **Tier 0（未毕业）**：所有运营者共享同一台宿主机、同一出口 IP、同一套设备指纹。便宜简单，但微信看来是「一台机器上一批号」。
- **毕业**：让该账号获得**独立出口 IP** ± **独立设备指纹** ± **独立容器/网络栈**，在微信风控眼里「像另一台电脑、另一个人在另一个地方上网」。

毕业不是「多开几个浏览器」，而是**隔离维度的升级**：**网络层（IP）** / **设备层（指纹）** / **进程容器层**。

## 2 · 为什么要毕业：微信视频号的风控判定向量

| 向量 | 微信采集的具体信号 | 可控性 | 毕业应对 |
|---|---|---|---|
| **网络层**（权重最高） | 出口 IP / ASN / 归属地 / DNS 一致性 / WebRTC 真实 IP 泄漏；同 IP 下登录≥3 账号直接打「弱关联」 | 强可控 | 独立住宅/ISP 静态 IP + DNS-over-proxy + 关 WebRTC |
| **设备指纹层**（最难骗） | Canvas / WebGL（含 C++ 层渲染哈希）/ AudioContext / 字体栈 / UA / Client Hints / 屏幕 / 硬件并发 | 部分可控 | Tier 2+ 用反检测内核；Tier 1 仅 JS 层随机化（对微信弱） |
| **行为层** | 登录时间差≤1min、发布时间差≤5min、操作路径完全一致、无浏览/点赞 | 强可控 | 随机延迟（280–360s）、错峰登录、内容变体（Part 2 已定） |
| **账号图谱层** | 互相关注、内容相似度（特征点提取）、社交图谱、同支付/同实名 | 基本不可控 | 内容差异化 + 号间互不直接互关 + 不共用素材 |

> **硬约束（决定 Tier 选型）**：微信会读取浏览器 **C++ 层**渲染数据（Canvas/WebGL 真实哈希），仅靠 JS 改 UA、注入 `navigator.webdriver=false` 在微信侧**基本无效**。所以「指纹隔离」想做扎实，必须用**反检测内核**（商业或自建 CDP 层伪造）或**真机/云手机**——纯 stock Chromium + Playwright 只能覆盖网络层和行为层。

## 3 · 隔离分级模型（核心设计）

毕业按压力**逐级升级**，四个 Tier 构成平滑、可回退的演进链：

| | 网络 | 指纹 | 隔离 | 成本 | 适用 |
|---|---|---|---|---|---|
| **Tier 0** 同机多 profile | 共享宿主 IP 192.168.1.163 | stock Chromium 默认 | 仅 user-data-dir 分离 | ￥0 增量 | ≤8 运营者、低风险内容 |
| **Tier 1** 独立住宅 IP | 每账号独享住宅/ISP 静态 IP | UA/时区/视口随机化（JS 层，对微信弱） | 同宿主多 Chromium + --proxy-server | ≈￥30–50/账号/月 | 同 IP 关联风险触发时首选 |
| **Tier 2** 独立容器 + 反检测内核 | 独立容器网络栈 + 独立 egress IP | 反检测内核（C++ 层伪造 canvas/webgl） | 独立进程/容器，可跨主机 | 容器/VM 资源 + IP，运维负担上升 | ≥15 运营者 或 持续风控 |
| **Tier 3** 云手机 | 物理级隔离 | 物理机 | 每账号一台云端 Android | ≈￥30–80/账号/月 | 紧急/高价值号 |

> ⚠️ 成本修订（R9）：Tier 1 静态住宅 IP 国内市场价 **￥30–50/月/个**（原方案 ￥6 严重低估）。毕业决策按真实成本测算：20 运营者全升 Tier 1 ≈ ￥600–1000/月，需与封号损失对比评估。

## 4 · 毕业触发器：毕业控制器

毕业由 **毕业控制器（Graduation Controller）** 驱动，常驻监控 + 决策模块（放 `worker-fast` 或独立 beat，每 5 分钟扫一次）。输入来自 Redis 路由表 + 发布审计 + 风控事件流。

| 触发条件 | 信号来源 | 动作 | 升到 |
|---|---|---|---|
| 单宿主 profile 数 ≥ 8 | Redis `pub:route:*` 按 host 聚合 | 新账号默认 Tier 1；存量分批灰度升 | Tier 1 |
| 7 日内 ≥ 1 次风控受限 | 发布任务返回 429/验证码/限流标记 | 该账号立即升 Tier 1（换独立 IP） | Tier 1 |
| 单宿主 profile 数 ≥ 15 | 同上聚合 | 容量压力，启动 Tier 2 容器分片 | Tier 2 |
| 7 日内 ≥ 2 次风控受限（同账号） | 审计表 `risk_event` | 升 Tier 2 + 换反检测内核 | Tier 2 |
| 账号被标记「设备关联」/ 批量限流 | 微信后台反馈 / 运营上报 | 紧急升 Tier 3（云手机）或人工介入 | Tier 3 |

> 与 Part 1 阈值对齐：Part 1 的「毕业双触发」= 本表「≥8 或 7日≥2 风控」。本篇拆细成 5 级，区分**容量驱动**（升 Tier 1/2 治同 IP 关联）与**风险驱动**（升 Tier 2/3 治设备/行为关联），避免一刀切过度升级烧钱。

## 5 · 毕业编排：怎么「搬」而不丢登录态

毕业本质是**迁移**：把账号的 `Env` 三元组从旧位置换到新位置，且 cookie/localStorage（登录态核心）零丢失、对外发布不中断、可回滚。登录态在 `/data/chrome-profiles/<profile_id>/` 目录里——所以迁移 = 搬这个目录 + 换路由。

> ⚠️ 关键修正（R6）：**微信登录态对出口 IP 变化高度敏感**，profile 目录搬迁 + 换 IP 后**大概率触发验证/重登**（短信或扫码）。因此「零停机迁移」是理想态，实际执行需内置「预计需重登」预期，并设人工介入节点。

**迁移 7 步（含重登处理）**
```bash
# 1. 冻结：路由表把该 profile 置 GRADUATING（发布调度跳过，进行中任务跑完）
SET pub:route:<acct_id> "{...,status:'GRADUATING'}"  EX 600

# 2. 拉起新环境：Tier1=同宿主新 Chromium+proxy；Tier2=新容器/VM（自带独立 IP）
launch_chromium(profile_id, proxy="socks5://<dedicated_ip>:port", fp=fingerprint_profile)

# 3. 搬运登录态：cp -R 整个 profile 目录（cookie+localStorage+IndexedDB 全带走）
#    Tier1 同宿主直接 mv；Tier2 跨机经对象存储/rsync 中转，再落到新容器卷
rsync -a /data/chrome-profiles/<pid>/  newhost:/data/chrome-profiles/<pid>/

# 4. 注册新路由（host/port/proxy/fingerprint/tier 全更新，不再用全局 CHROME_DEBUG_HOST）
SET pub:route:<acct_id> "{host:'rpa_worker_<pid>', port:9222, proxy:'...', fp:'...', tier:2, status:'READY'}"

# 5. 心跳验证：新环境连微信创作中心，确认登录态有效（读 /json/version + 访问 post/create）
#    ⚠️ 换 IP 后大概率失败（微信要求验证/重登）
if new_browser.logged_in():
    # 6a. 登录态有效 → 解冻，状态 READY，发布调度恢复命中
    SET pub:route:<acct_id> "{...,status:'READY'}"
else:
    # 6b. 登录态失效 → 置 NEED_LOGIN，通知对应 operator 重新扫码（自服务流程）
    #     期间旧环境保持运行可回滚；operator 重登成功后置 READY
    SET pub:route:<acct_id> "{...,status:'NEED_LOGIN'}"
    notify_operator(acct_id)  # 复用 Part 2 登录态自服务通道

# 7. 旧环境保留 24h 后回收（期间确认新环境稳定）
```

> **回滚**：第 5 步心跳失败且 operator 无法立即重登时，把路由回置旧 host/port（旧环境一直保留到确认成功才下线），状态回 `READY(Tier0)`。旧 profile 目录保留 24h 才回收，确保「搬砸了能瞬间回去」。

## 6 · 独立 IP 层设计

**6.1 代理类型选择**

| 类型 | 微信可信度 | 结论 |
|---|---|---|
| 数据中心 IP | ❌ 低（ASN 一眼机房） | 禁用 |
| 动态住宅（频繁切） | ⚠️ 中（异地乱跳反而高危） | 仅注册期用 |
| **静态住宅/ISP** | ✅ 高（家庭宽带，地域稳定） | **毕业首选**（成本 ￥30–50/月/个） |

原则：**一账号一 IP、长期固定、地域匹配账号注册地**（北京号配北京 IP）。绝不今天 A 明天 B。

**6.2 防泄漏与防串**
- **DNS 泄漏**：应用走代理但 DNS 本地解析会暴露真实网络 → DNS 必须经代理或 DoH。
- **WebRTC 泄漏**：浏览器默认 WebRTC 会泄露真实 IP → 关 WebRTC 或在反检测内核里伪装。
- **IP 防串**：维护分配表 `container ↔ IP`，容器起停更新；绝不让两个容器指向同一 socks5。
- **一致性**：IP 地域 = 时区 = locale = 字体栈 必须自洽，矛盾信号秒被风控打标。

## 7 · 指纹隔离层设计

| 路径 | 做法 | 对微信有效度 | 适用 Tier |
|---|---|---|---|
| **A. Playwright context 随机化** | UA/时区/视口/字体 + stealth init script + canvas 噪声注入 | 弱（JS 层，C++ 层哈希仍相同） | Tier 1（够用治 IP 关联） |
| **B. 反检测内核替换** | BotBrowser / AdsPower 引擎 / undetected-chromium 替换 stock Chromium，CDP 层伪造 canvas/webgl/audio | 强 | Tier 2（治设备关联） |
| **C. 云手机 / 真机** | 每账号一台云端 Android，物理级隔离 | 最强 | Tier 3（紧急/高价值号） |

> 工程现实建议：clip-workflow 现用 stock Chromium + CDP。Tier 1 阶段先用**路径 A + 独立 IP** 拿到 80% 收益（网络层隔离已解决最致命的「同 IP 关联」）；真要做设备层隔离时，再在 Tier 2 把内核换成反检测版，**接口不变**（仍走 CDP，只是底层 Chromium 换了），避免一开始就被反检测内核的授权/稳定性绑死。

## 8 · 与现有代码的接入点（精确到行，已核实）

| 现有位置 | 现状 | 毕业需要的改动 |
|---|---|---|
| `models.py:464 PublishProfile` | 有 `chrome_debug_port`(默认9222)、`cookie_file`、`title_template` | 加 `tier`、`proxy_url`、`fingerprint_profile(JSON)`、`egress_ip`、`chrome_debug_host`、`grad_status` |
| `publish_service.py:122` | `connect_over_cdp(f"http://{s.CHROME_DEBUG_HOST}:{port}")` —— host 是全局配置 | 改用路由表 `route[host]:route[port]`，不再读全局 `CHROME_DEBUG_HOST`；port 指向 cdp_proxy 鉴权口 |
| `rpa/start_chromium.sh:56-62` | 单 Chromium，固定 9223，单 `--user-data-dir=/data/chrome-profiles` | 支持 `--proxy-server`、`--remote-debugging-address=127.0.0.1` 与 `--user-data-dir=/data/chrome-profiles/<id>` 参数化；Tier2 由 per-profile 容器各自启动 |
| `rpa/cdp_proxy.py` | 单实例 9222→9223，Host 改写 | 每个 Tier2 容器自带 cdp_proxy；或改为按 profile 多实例监听不同端口 + 鉴权中间件 |
| `docker-compose.yml:370 rpa_worker` | 单 rpa_worker，挂 `chrome_profiles` 卷（行 401），出口=宿主 IP | Tier2 起 `rpa_worker_<id>` 服务，各自网络 + 独立 egress；Redis 路由表指向新 host |
| `docker-compose.yml:36 CHROME_DEBUG_HOST` | 全局 `rpa_worker` | 降级为「默认 host」，逐 profile 被 `PublishProfile.chrome_debug_host` 覆盖 |

> **最小侵入原则**：毕业能力全部通过 **Redis 路由表 + PublishProfile 新字段** 承载，**不改**发布主链路（`VideoChannelPublisher` 只多读一个 host 参数）。关掉毕业（feature flag）时，路由表不填 host，代码回退读全局配置，与 Part 2 灰度开关一致。

## 9 · 成本与可控性评估（修订 R9）

| 维度 | Tier 0 | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|
| 每账号月成本 | ￥0 | ≈￥30–50（静态住宅 IP） | ≈￥30–50 + 容器资源 | ≈￥30–80（云手机） |
| 隔离强度 | 低 | 中（网络） | 高（网络+设备） | 最高 |
| 运维复杂度 | 极低 | 低 | 中（编排） | 高 |
| 升级平滑度 | — | 热升级（换代理） | 迁移（搬目录+可能重登） | 迁移+重登 |
| 回滚难度 | — | 易 | 易（旧环境保留） | 难（需重新登录） |

> **规模测算（真实成本）**：若 20 个运营者全升 Tier 1 ≈ **￥600–1000/月**（非原方案 ￥120）；全升 Tier 2 ≈ ￥600–1000 + 一台 2C4G 云主机。对比「矩阵号批量限流/封号」的流量损失，毕业 IP 成本仍可接受，但**决策门槛显著高于原方案**——建议先升风控压力最大的账号（分级灰度），不全量一刀切。

## 10 · 风险、残余风险与合规

**残余风险（毕业也兜不住的）**
- **账号图谱关联**：多个号互相关注 / 发同一批素材 → 平台从社交图谱判关联，IP/指纹隔离无效。对策：内容差异化 + 号间不互关（Part 2 均分模式强制变体）。
- **反检测内核被攻破**：微信升级检测算法可能识破某版伪造 → 需持续跟进内核版本。
- **代理 IP 被污染**：住宅 IP 也可能被前人用黑进黑名单 → 上线前用 ipinfo.io / scamalytics 验纯度。
- **换 IP 重登成本**：每次 Tier 升级可能要求运营者重新扫码（R6），批量升级时运营负担集中 → 分批灰度 + 自服务扫码通道。

> **合规红线**：本设计用于**自有、实名、合规的视频号矩阵账号**的运营环境隔离与风控规避（降低误伤），**严禁**用于批量注册违规小号、刷量、绕过平台规则的欺诈行为。务必遵守《网络安全法》《个人信息保护法》及微信平台规则。

## 11 · 与 Part 1/2 的关系 & 最终验收

**演进式收敛总图景**
```
Phase 0  账号归属(RBAC)        ── 地基，已设计（Part 2）
Spike 0  QR 渲染验证           ── Phase 1 前置（R7）
Phase 1  方案A 单容器多profile  ── Tier 0，上线拿价值（Part 1/2）
   └─ 毕业双触发 ─► 毕业控制器
Phase 2  Tier 1 独立IP ─► Tier 2 独立容器+反检测内核 ─► Tier 3 云手机
         （本篇 Part 3 完整定义）
加热运营者（需蓝V）── 独立史诗，不与此耦合（Part 1 已定）
```

**毕业子系统 DoD（验收口径）**
- ✅ 毕业控制器能按 5 级条件自动触发升级，无需人工介入；
- ✅ 迁移 7 步可脚本化、可幂等重跑、失败可 5 分钟内回滚；
- ✅ 迁移后登录态保留策略明确：换 IP 失效即触发自服务重登（R6），不静默丢号；
- ✅ Redis 路由表含 host/port/proxy/fingerprint/tier，`CHROME_DEBUG_HOST` 全局配置可被子项覆盖；
- ✅ 独立 IP 经 DNS-over-proxy + WebRTC 关闭，无真实 IP 泄漏；
- ✅ feature flag 关闭时，毕业能力整体隐身，旧链路零变化（与 Part 2 一致）。

---

## 附：三篇总览与下一步

| 文档 | 解决的核心问题 | 关键产出 |
|---|---|---|
| Part 1 需求+圆桌 | 「并入」意味着什么、选哪个方案 | 演进式收敛路线（Phase 0→1→毕业）、方案 A 胜出（3.95） |
| Part 2 加固评审 | 方案怎么才「稳固可控」 | 8 主题规格 + 6 条 P0 铁律 + 9 条 DoD 验收 |
| Part 3 毕业机制 | 「毕业到独立 IP/沙盒」到底是什么 | 4 级 Tier 模型 + 毕业控制器 5 级触发 + 迁移 7 步（含重登处理） |

**建议落地顺序**：Phase 0（DB 迁移 + `created_by/operator_id` + RBAC 过滤，无浏览器层改动，最稳）→ **Spike 0（QR 渲染验证，1 天）** → 路由表 schema + Lua 原子配额 + **Batch 模型（R14）**（纯后端，配单测）→ Tier 0 多 profile 端口映射（含 CDP 收敛 + **失效检测闭环 R12** + **存量端口归一 R15**）→ 登录态自服务/灰度回滚 → 毕业控制器（按 Part 3 触发阈值自动升 Tier）。

---

## 修订记录

| 版本 | 日期 | 修订内容 |
|---|---|---|
| v1.0 | 2026-08-14 | 初版（需求+圆桌 → 加固评审 → Part 3 毕业机制） |
| v2.0 | 2026-08-14 | 代码核实 + 方案审核修订：服务数 19→17、Redis ACL 澄清、RBAC 4 角色、端口 9223、CDP 端口收敛（R5）、迁移重登预期（R6）、QR Spike（R7）、Lua nil 兜底（R8）、成本重估（R9）、资源评估（R10）、封面来源/重试节奏/失效感知（R11） |
| v3.0 | 2026-08-14 | 外部评审意见吸收（6 项）：路由表秒级失效闭环（R12）、cover 回填语义（R13）、Batch 模型（R14）、存量端口归一（R15）、单 IP 口径澄清（R16）、actor/operator 鉴权分离（R17）；P0 6→7，DoD 9→11 |
| v3.1 | 2026-08-14 | **问题 3-7 对应章节修订吸收（5 项）**：confirm selector 失败兜底（R18）、cdp_proxy token 注入链路写实（R19）、单 IP 排班示例 + operator 延迟放大（R20）、DoD 故障注入混沌演练（R21）、inflight 跨日边界语义（R22）；DoD 11→15，新增上线前混沌演练 |

*—— 本文件由三份 HTML 评审文档整合 + 代码核实修订 + 外部评审意见吸收（v3）+ 问题 3-7 章节修订吸收（v3.1）而成，2026-08-14，单 Markdown 零依赖交付。*
