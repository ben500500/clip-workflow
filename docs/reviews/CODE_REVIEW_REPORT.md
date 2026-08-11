# clip-workflow 代码审查报告与修复方案

> 审查对象：`/Users/ben/Downloads/Agent-WorkSpace/clip-workflow`（短剧切片投放工作流）
> 审查方式：只读静态审查，**未改动任何代码**。6 个代理并行核实，结论均带 `file:line` 证据。
> 审查角色：① 代码臃肿/架构审查员 ② 安全审计员 ③ 性能工程师
> 审查基线：`git 67dad00`（fix: 豆包生成登录弹窗拦截处理 + 前端刷新后恢复任务轮询）
> 日期：2026-08-10

---

## 0. 总览

| 维度 | 数据 |
|---|---|
| 代码规模 | Python 29,137 行 / TS+TSX 13,992 行 / Go 3,250 行 ≈ **4.6 万行** |
| 服务编排 | docker-compose **14 个服务**（其中 4 个共用 `clip-backend:latest` 镜像） |
| API 路由 | **175 个**，其中 **100 个零鉴权**（扣除 login/refresh 后 **98 个真实缺口**） |
| 可清理代码 | 约 **5,600 行**（12%）+ 70 KB 文档 |
| 高危问题 | 安全 6 条 / 性能 5 条 / 架构 1 条 |

**一句话结论**：架构分层本身是清晰的（比同类项目干净），真正的问题集中在三处 —— **① 鉴权几乎没接上**（100 个裸奔端点 + CDP 9222 暴露公网）、**② 一行 SQL 错误导致全库 0 索引**、**③ 单 Celery worker 串行吞 4 个队列**。这三条都不是"重构"级问题，而是**改几行就能止血**的配置/接线缺失。

---

## 1. 架构测绘

### 1.1 服务编排（14 个）

| 层 | 服务 | 端口绑定 | 说明 |
|---|---|---|---|
| 入口 | `nginx` | **0.0.0.0**:80 | 唯一对外入口，无鉴权无限流 |
| 应用 | `frontend` | 127.0.0.1:3000 | React 18 + AntD，28 页 |
| 应用 | `backend` | 127.0.0.1:8001→8080 | FastAPI，17 个 API 模块 |
| 应用 | `autoclip` | 127.0.0.1:8000 | 独立 FastAPI，AI 选点 pipeline |
| 异步 | `worker` | — | **唯一 Celery 消费者**，独吞 4 队列 |
| 异步 | `beat` | — | 4 个定时任务 |
| 异步 | `slice-worker` ×2 | — | **Go** 程序，消费 Redis Stream |
| 异步 | `rpa_worker` | **0.0.0.0**:9222 | Xvfb + Chromium + CDP 反代 |
| 数据 | `postgres` | 127.0.0.1:15432 | PG 15，24 张业务表 |
| 数据 | `redis` | **0.0.0.0**:16379 | Broker + Stream 任务队列 |
| 数据 | `minio` | **0.0.0.0**:9000/9001 | 8 个桶 |
| 一次性 | `minio_init` / `alembic-migrate` | — | 建桶 / 迁移 |

> `rpa_worker` **不是** Celery worker（supervisord 托管的浏览器基座）；`slice-worker` 是 Go 程序消费 Redis Stream，**不走 Celery**。

### 1.2 四条端到端链路

**(a) 导入→切片→预览**
`POST /api/upload`(分片) → `minio:raw-footage` → `POST /api/slice-tasks` → `redis_stream` Stream `slice:tasks:{high,normal,low}` → **Go slice-worker** `XReadGroup` → 申请 upload-url(`X-Worker-Token`) → `exec python engines/slice.py` → 直传 `minio:sliced` → `POST /callback` → 前端 presigned 播放

**(b) 去水印**
`POST /api/watermark/run` → `watermark_task`(video_processing) → `backend/app/engines/watermark_runner.py` **四路分发**（`remove_ai` / `seedance` / `seedance_wm` / `remove_mask`）→ subprocess 解析 `PROGRESS:` → `minio:watermark-output`

**(c) autoclip AI 选点**
`autoclip_task` → worker 下载源片 → `POST autoclip:8000/pipeline/run` → ASR(faster-whisper) → step1 大纲 → step2 时间线 → step3 打分 → step4 标题 → **worker 每 5s 同步轮询 `/progress`** → 写 `clip_candidates`

**(d) 发布**
`task_publish_video`(publish 队列) → `publish_service` → Playwright **CDP 连 `rpa_worker:9222`** → 填表 → 截图 → `pending_confirm` → 人工确认 → `confirm_publish_worker` 复用同 tab 发布

---

## 2. 角色① 代码臃肿 / 架构

### 2.1 已证实的零引用死代码

| 文件 / 符号 | 行数 | 引用 | 证据 |
|---|---|---|---|
| `autoclip/app/celery_app.py` | 17 | **0** | 定义了 Celery 但零 `@task`；`compose:293/324` 的 worker+beat 均挂 `app.celery.tasks.celery_app` |
| `backend/app/services/slice_service.py:171-185` `run_preview()` | 15 | **0** | 全项目仅定义处 1 行 |
| `engines/preview.py` | 59 | **0（有效）** | 唯一入口是上面那个无调用者的 `run_preview` → **整条链死** |
| MinIO `previews` 桶 | — | 只读不写 | 读：`api/preview.py:84,88`；建桶：`maintenance_service.py:114`；**全项目无 put/upload** |
| `autoclip/requirements.txt` 未用依赖 | 12 项 | **0** | sqlalchemy / asyncpg / alembic / celery / redis / httpx / python-jose / passlib / prometheus-client / structlog / orjson / python-dotenv |

> ⚠️ `python-multipart` grep=0 但为 `UploadFile=File(...)` 的隐式运行时依赖，**不可删**。

### 2.2 重复 / 职责重叠

**① 去水印实为 4 套引擎并存**（`watermark_runner.py:365-390` 分发，UI 全暴露于 `Watermark.tsx:759-762`）

- `engines/seedance_watermark_remover.py`(555) 是**承重件** —— `remove_ai` 在 `watermark_runner.py:186` 与 `:213` 两条路径回退调用它，**不可删**。
- **唯一可废分支** = `engines/seedance_wm/`(2123) + `seedance_wm_runner.py`(206) = **2,329 行**，无其他模块依赖。
- **顺带发现 bug**：前端默认引擎 `remove_mask`（`Watermark.tsx:99`），API 默认 `remove_ai`（`api/watermark.py:90`）—— 默认值不一致。

**② 三处裸 httpx 绕过 service 层**（现役封装是 `services/autoclip_service.py` 的 8 个函数）
`api/shortdrama.py:278-305`、`api/shortdrama.py:377-399`、`api/publish_material.py:123-151` —— 各自复刻 `httpx.AsyncClient(timeout=180)` + 异常处理，**可收敛约 60 行**。

**③ LLM provider 三个零配置**
`llm_providers.py` 的 4 个 provider 中，OpenAI / Gemini / SiliconFlow **在 `.env.example` 与 compose 中均无对应 KEY**，默认恒为 dashscope（`llm_manager.py:48/94/207`、`api/config.py:79`）→ **可删 `llm_providers.py:248-508` 约 260 行**。另有循环导入：`llm_manager.py:244` 反向 import `LLMClient`。

**④ 双后端状态双份**
`autoclip/app/main.py:57` `projects: dict[str,dict]={}` 纯内存 vs backend `models.py:164 autoclip_projects` + `:187 autoclip_runs` → **autoclip 容器重启即丢进度**。

**⑤ 建表机制实为 5 套并存**（不是 3 套）

| # | 机制 | 位置 | 问题 |
|---|---|---|---|
| 1 | `init.sql` | 15 张扩展表 + 28 条索引 | **第 273 行必失败，见 §4.1** |
| 2 | alembic | 15 个迁移 | `compose:184` 用 `\|\| echo` **静默吞掉失败** |
| 3 | `create_all` | `main.py:118` | 表已存在则 checkfirst 跳过 |
| 4 | `_apply_compat_migrations` | `database.py:129-210` | 82 行 / **40 条**硬编码 ADD COLUMN |
| 5 | `_ensure_autoclip_runs_table` | `database.py:85-127` | 43 行手写 DDL |

**⑥ Go 桌面代码被编进容器**
`tui.go`(528) / `tray.go`(93) / `tray_common.go`(190) **无 build tag**（只有 `exec_*` / `tray_darwin` / `tray_windows` / `tray_other` 5 个有）→ `Dockerfile` 的 `GOOS=linux go build .` 把 **843 行 / 25.9%** 桌面代码编进容器镜像，而 CMD 固定 `--no-tui` 走 `runDaemon`，`main.go:60-68` 分支**永不可达**。

### 2.3 胖 API 层（service 层形同虚设）

API 文件内**直接 select/execute 的次数**：

| 文件 | DB 操作次数 | 行数 |
|---|---|---|
| `api/slice.py` | **60** | 1291 |
| `api/publish.py` | **60** | 937 |
| `api/dashboard.py` | **50** | 1088 |
| `api/projects.py` | 47 | 529 |
| `api/intervals.py` | 36 | 520 |

而 `services/slice_service.py` 仅 185 行、**零 DB 逻辑**（只封装 subprocess）。

### 2.4 God 文件拆分建议

**`backend/app/celery/tasks.py` (2390 行) → 9 个文件**

| 行段 | 职责 | 目标文件 |
|---|---|---|
| 1-122 | Celery 配置 / `run_async` / `_ensure_source_video` | `celery/app.py` + `_base.py` |
| 123-361 | `autoclip_task`、`detect_task` | `tasks/autoclip.py` |
| 362-513 | `slice_task` | `tasks/slice.py` |
| 514-872 | 持久化 helper（`_save_autoclip_results:534` / `_save_detected_intervals:671` / `_save_slice_outputs:775`） | `tasks/_persistence.py` |
| 873-1330 | 发布 + 指标（`:874/:975/:1016/:1069`、`_compute_funnel_snapshot:1231`） | `tasks/publish.py` + `metrics.py` |
| 1320-1360 | 告警 / 日常运维 | `tasks/ops.py` |
| 1361-1686 | 去水印（`watermark_task:1466`） | `tasks/watermark.py` |
| 1687-2043 | 豆包 RPA（`doubao_generate_task:1853`） | `tasks/doubao.py` |
| 2044-2390 | Seedance 直连（`seedance_generate_task:2185`） | `tasks/seedance.py` |

**`api/slice.py` (1291)**：`66-165` Schema→`schemas/slice.py`；`167-513` 私有逻辑（`_acquire_concurrency_slot:307` / `_publish_to_worker:386` / `_dispatch_celery:467`）→**下沉** `services/slice_dispatch_service.py`；`863-1042` Worker 回调（`_verify_worker_token:863`）→ `api/slice_worker_callback.py`

**`api/dashboard.py` (1088)**：`136-186` 概览 / `187-311` 视频指标 / `312-448` 小程序+广告+剧集 / `449-507` 漏斗 / `508-1088` 导入+模板 → 拆 4 文件

**`api/shortdrama.py` (1137)**：`82-257` 模板+序列化 / `258-472` 提示词 / `493-646` 上传 / `647-711` 模板 CRUD / `712-1000` 豆包 / `1000-1137` Seedance → 拆 4 文件

**`ShortDrama.tsx` (1819)**：`25-107` 常量→`constants.ts`；`190-338` 数据拉取→`useShortdramaRecords.ts`；`542-727` 豆包 / `650-727` Seedance→`useDoubao.ts` / `useSeedance.ts`；`1785-1819` `PromptResultBlock`→独立组件

**`Watermark.tsx` (1225)**：拆 `ENGINE_HELP` 常量 + `useWatermarkTasks` + `778-1000` 的 4 个引擎参数表单子组件

**`EpisodeDetail.tsx` (1198)**：按 `WORKFLOW_STEPS`(41) 拆 4 个 Tab 子组件

---

## 3. 角色② 安全审计

### 3.1 未鉴权端点统计（175 路由 / 100 裸奔）

| 模块 | 路由 | 已鉴权 | **裸奔** | 高危裸奔举例 |
|---|---:|---:|---:|---|
| `dashboard.py` | 32 | 0 | **32** | `:588 PUT /dashboard/config`、`:635 POST /dashboard/import/confirm` |
| `shortdrama.py` | 24 | 8 | **16** | `:669 PUT /shortdrama/prompt/templates`、`:592 DELETE` |
| `publish.py` | 19 | 0 | **19** | `:263 POST /publish/tasks`、`:765 POST /publish/video-accounts/batch`、`:597 POST /publish/profiles` |
| `config.py` | 9 | 0 | **9** | `:322 PUT /config`、`:351 POST /config/reset-default` |
| `watermark.py` | 9 | 0 | **9** | `:276 POST /watermark/run`、`:554 POST /watermark/tasks/batch-delete` |
| `upload.py` | 6 | 2 | **4** | `:133 POST /upload/resume`、`:181 PATCH /upload/{id}` |
| `publish_material.py` | 4 | 0 | **4** | `:110 POST .../generate`、`:224 DELETE` |
| `monitor.py` | 9 | 6 | 3 | `:142 GET /monitor/metrics`（泄露内部拓扑） |
| `workers.py` | 7 | 6 | 1 | `:100 POST /workers/heartbeat`（可伪造节点） |
| `slice.py` | 10 | 7 | 3 | 均由 Worker Token 保护 ✔ |
| `auth.py` | 10 | 8 | 2 | login / refresh，设计如此 ✔ |
| 其余 6 模块 | 36 | 36 | 0 | ✔ |
| **合计** | **175** | **75** | **100** | 真实缺口 **98** |

根因：`main.py:172-188` 所有 `include_router` **无 `dependencies=`**，各 `api/*.py` 全是裸 `APIRouter()`。

### 3.2 高危漏洞（6 条）

**H1 · CDP 9222 无鉴权暴露 + 主动拆除浏览器防线** — 全项目最致命
`docker-compose.yml:369`（`"${RPA_DEBUG_PORT:-9222}:9222"` **无 127.0.0.1 前缀**）、`rpa/cdp_proxy.py:18`（`LISTEN_HOST="0.0.0.0"`）、`cdp_proxy.py:60-70`（`_rewrite_request_host` 把任意 Host 强改 `localhost`，**主动绕过 Chromium 的 DNS-rebinding 防护**）、`cdp_proxy.py:73-77`（响应体改写为可回连地址）、`start_chromium.sh:56-63`（`--no-sandbox`）。

> 攻击链：直连 `IP:9222/json/list` → 代理替攻击者绕过 Host 校验 → 拿 `webSocketDebuggerUrl` → WS 接管浏览器 → `Network.getAllCookies` **导出豆包/视频号持久登录态**（`chrome_profiles` 卷，`compose:363`）→ 任意 JS 执行 → **以你的身份发布内容**。**零凭据，一次 HTTP 请求即完成侦察。**

修复：容器间本就走 `clip-network`（backend 用 `CHROME_DEBUG_HOST=rpa_worker`，`compose:218/274`）→ **直接删除 `ports` 整段即可**，根本不需要发布到宿主机。

**H2 · 100 个端点完全无鉴权** — 见 §3.1。Nginx（`nginx.conf:75-95`）对 `/api/` 无鉴权、无 `limit_req`、无 IP 白名单，且 `nginx:80` 绑 0.0.0.0（`compose:475`）→ **网络可达即可全量调用，无门槛。**

**H3 · 种子用户明文默认口令，生产同样执行**
`main.py:57-62` 4 个种子账号密码为硬编码明文弱口令（规律为用户名+固定数字），`main.py:65-83` `_create_seed_users()` 在 `lifespan`（`main.py:120`）**无条件执行**，无 DEBUG 判断。admin 可经 `api/auth.py:197 POST /api/auth/login` 直接登录，**无验证码、无失败锁定、无限流**。

**H4 · JWT / Cookie 密钥有不安全默认值**
`config.py:111 JWT_SECRET` 带占位符默认值 → 部署者不改 = 公开密钥，可离线伪造任意用户 token（HS256，`auth.py:56/103`）。`config.py:116 COOKIE_ENCRYPT_KEY=""` 默认空 → `auth.py:311/320` 回退 JWT_SECRET，**两套密钥同源，一破全破**（可解密库中平台登录 Cookie）。

**H5 · MinIO 数据面 + 控制台暴露公网，默认 AK 为公开值**
`compose:83-84`（9000/9001 均绑 0.0.0.0）、`config.py:24` 的 `MINIO_ACCESS_KEY` 默认值是众所周知的默认账号名。9001 控制台对外可达 = 可爆破 root 凭据 → 拿到全部原片/切片/成品。

**H6 · Redis 暴露公网**
`compose:61`（`"${REDIS_PORT:-16379}:6379"`，仅 `--requirepass`）。Redis 承载切片 Stream，payload 含 `callback_token`（`api/slice.py:415/444`）→ 密码泄露后可读全部任务 token、伪造回调、投递恶意任务 payload 给 Go worker。

### 3.3 中危（8 条）

| # | 位置 | 问题 |
|---|---|---|
| M1 | `api/upload.py:132-158,180-210,333` + `services/upload_service.py:128-136` | 未鉴权分片上传（上限 50GB）+ **每写一片重新 MD5 全部已落盘分片**（O(n²)）→ 上传 1GB 产生 **约 100GB 磁盘读**，匿名即可打满 IO |
| M2 | `api/slice.py:238` + `engines/slice.py:271,274` | ffmpeg `drawtext` filtergraph 注入：转义链最终产出「偶数反斜杠+单引号」，ffmpeg 单引号段内不识别反斜杠转义，**引号照常闭合** → 可注入 `textfile=` 读容器内文件并渲染进视频（需登录） |
| M3 | `config.py:52` → `main.py:140-147` | `CORS_ORIGINS="*"` 默认放行全站，配合 H2 → **任意网站 JS 都能跨域读写你的账号库/配置** |
| M4 | `main.py:158-168` + `nginx.conf:119-136` | WebSocket `/ws/progress/{task_id}` 无任何鉴权 |
| M5 | `nginx.conf:139-156` | `/minio/` 暴露 MinIO **admin 命名空间**（`/minio/admin/v3/*`）与版本指纹。**部分推翻**：因 `proxy_pass` 无 URI 部分且 S3 路径是 `/{bucket}/{key}`，**无法列桶或下载对象** |
| M6 | `engines/watermark_runner.py:242/245/289/291/341/344/356/358` | 全程 `create_subprocess_exec`，**无命令注入**；但 `region`/`source_name`/`detector`/`inpainter` 无格式校验，可注入 `-`/`--` 开头**参数**污染下游 argparse（`backend`/`mode`/`scope` 等已正确白名单，见 `:247/292/296/302/353`） |
| M7 | `rpa/Dockerfile`、`slice-worker/Dockerfile` | 无 `USER` 指令，容器以 root 运行（backend/autoclip 已正确降权，见 `backend/Dockerfile:35,55`） |
| M8 | `slice-worker/worker.go:281-286` | `filepath.Join(TempDir, task.TaskID)` —— `Join` 会 `Clean` 掉 `..` 从而**逃出基目录**；TaskID 来自 Redis payload，与 H6 组合可写任意路径 |

### 3.4 低危（4 条）

- **L1** `deploy_remote_worker.sh:30-31` 硬编码内网 IP/SSH 用户名；更值得注意的是 `:91-94` 把 Redis 密码**明文落盘到 `/tmp/redis-pass.tmp`**，`:135/:171` 写入 `docker run -e` 与 `worker.json`（进程列表可见）
- **L2** `database.py:206` DDL 用 f-string，但表/列名来自 `:188-193` 静态元组 → 非注入，仅卫生问题
- **L3** 全站无限流、无登录失败锁定
- **L4** `api/monitor.py:136/142/167` 三个未鉴权端点泄露 DB/Redis/MinIO/磁盘健康指标

---

## 4. 角色③ 性能工程

### 4.1 【最高优先级】一行 SQL 导致全库 0 索引

`init.sql:273` = `CREATE INDEX idx_users_email ON users(email)`，但 `users` 表（`init.sql:17-30`）**无 `email` 字段**（`models.py` 与全部 alembic 迁移 grep `email` 零结果）。

它是全文件 **28 条 `CREATE INDEX` 中的第 1 条**。`postgres:15-alpine` 的 entrypoint 以 `psql -v ON_ERROR_STOP=1` + `set -e` 执行 → **该语句报错即中止，后续 27 条索引全部不执行**。

连锁失效（四重）：

1. 容器退出 → `compose:30 restart: unless-stopped` 拉起 → PGDATA 已非空 → **initdb 脚本永久跳过**
2. `database.py:54 create_all` 因表已存在（checkfirst）跳过整表 → **14 个 `index=True` 也不建**
3. `compose:184` 的 alembic 带 `|| echo` 吞掉失败 → 其 **16 条 `create_index` 同样不执行**
4. `models.py` 15 个 `ForeignKey` 中仅 4 个显式 `index=True`（`:103/190/698/882`），其余 11 个 ORM 层本就缺索引

**净结果：生产库仅有主键/唯一约束索引，业务索引 0/28。** `dashboard.py` 全部按 `created_at`/`status`/`platform` 过滤排序的查询退化为全表扫描，配合 `database.py:22 statement_timeout=30s`，**数据量上万后看板直接 30s 超时**。

### 4.2 其余高影响（4 条）

**P2 · 单 Celery worker 独吞 4 队列** — `compose:293`
`command: [... "worker", "--loglevel=info", "--concurrency=1"]`，**无 `-Q`** → 消费 `tasks.py:41-46` 声明的 `video_processing` / `publish` / `metrics` / `default` 全部 4 队列。配合 `tasks.py:34-36`（`task_acks_late=True`、`prefetch_multiplier=1`、`task_time_limit=7200`）。
→ **全局严格串行，并发度 = 1**。一个 2h 上限的切片/去水印任务运行时，beat 仍在投递（告警检查 `config.py:125 = 300s` → 2h 积压 **24 个**），**所有发布任务、指标采集被完全饿死**。这是"点了发布没反应"的直接来源。

**P3 · `_rewrite_cb` 死等 10 分钟** — `tasks.py:1935-1949`
`deadline = time.time() + 600`(1935)，循环内 `await asyncio.sleep(3)`(1937) + `_load_shortdrama_prompt`(1938)。运行在 `run_async(...)`(1957) 内，**占据唯一 worker 槽位**。
→ 单轮最长 **600s / 200 次 SELECT**；豆包支持多轮改写可叠加 N×10min。concurrency=1 下**整站异步任务停摆 10 分钟**。

**P4 · fast 模式重编码两次** — `engines/slice.py:381,383`
`slice_segment`(189-202) 恒走 `build_encoder_args`(186: `libx264 -preset veryfast -crf 23`) + `-c:a aac`，**全文件无 `-c copy`**。fast 模式 `vf/af` 均为 `None`（346-350 仅 dedupe 赋值）却仍重编码；随后 `concat_segments`(383→205-225) **再编码一遍**。
→ 1080p：`-c copy` 约 50-100× 实时，`veryfast crf23` 约 2-5× 实时 → **fast 模式被拖慢约 20-40 倍**。

**P5 · 全帧一次性载入内存** — `engines/seedance_wm/inpaint.py:243`
`raw_imgs = [cv2.imread(...) for f in files]` 把整个帧目录读进 list，`259-264` 再构造 `smoothed` 全量副本。
→ 15s@30fps 1080p = 450 帧 × 1920×1080×3B ≈ **2.8 GB**，加 float32 缓冲峰值 **>4 GB**。另 `140-159` 逐帧 `imread→推理→imwrite PNG`（PNG 编码成本是 JPEG 的 5-10×）。

### 4.3 中影响（6 条）

| # | 位置 | 问题与量化 |
|---|---|---|
| P6 | `compose:399/434` + `engines/slice.py:32-46` | **CPU 超卖 4×**：2 实例 × `MAX_CONCURRENT=2` = 4 个 ffmpeg；`cpu_threads_for_percent` 用 `os.cpu_count()`(43) 读**宿主机核数而非 cgroup 配额**，且 compose 未设 `cpus:` → 8 核机上 4×(8×50%) = **32 线程争抢 8 核** |
| P7 | `autoclip/app/utils/speech_recognizer.py:292` | `WhisperModel(...)` 是函数内**局部变量**，无单例 → 每次任务冷加载 **3-10s**，反复申请/释放约 500MB |
| P8 | `tasks.py:163-191` | autoclip 在 worker 内同步轮询：`max_polls=120`(160) × `time.sleep(5)`(191) = 最长 **600s 独占槽位**（`consecutive_failures>=6`(181) 早退是已有缓解） |
| P9 | `api/preview.py:177` + `tasks.py:1178` → `minio_service.py:169-178` | `response.read()` 视频**整包进内存**：单个 200MB 成片 → backend +200MB；`compose:233 --workers 1`，并发 3 个即 600MB，易 OOM |
| P10 | 前端 8 处轮询 | **WS 建成未接线已证实**：`main.py:158 @app.websocket("/ws/progress/{task_id}")` 与 `nginx.conf:119` 均就绪，但前端 grep `WebSocket\|EventSource` **零结果**。轮询点：`EpisodeDetail.tsx:198/239/291`(恢复态) + `:360/410/456`(触发态) 各 3000ms、`IntervalDetection.tsx:41` 3000ms（**无条件常轮询，无门控**）、`SliceTasks.tsx:68` 5000ms、`Watermark.tsx:175/191` 5000ms、`ShortDrama.tsx:257/300` 5000ms、`Workers.tsx:109` 10000ms、`AppLayout.tsx:130` 15000ms。→ 单用户三任务齐跑 ≈ **1.07 req/s**；10 人在线 ≈ **10.7 req/s 全打到 `--workers 1` 的单 uvicorn**，且每请求命中无索引的表 |
| P11 | `vert2horiz_crop.py:267,309`；`remove_mask_remover.py:567,622,670,726` | **8 处 `subprocess.run(cmd, check=True)`，`timeout=` 出现 0 次**（对比 `slice.py:131/142/158` 均带）→ ffmpeg 卡死则挂到 `task_time_limit=7200` 才被斩，**占槽位 2 小时** |

### 4.4 低影响（4 条）

- **P12** 4 个临时目录漏清理：`/tmp/publish_videos`(tasks.py:1182)、`/tmp/watermark`(1524)、`/tmp/doubao_videos`(1761)、`/tmp/generated_videos`(2118) —— `maintenance_service.py:76-80` 清理列表未覆盖
- **P13** `database.py:195-210` 启动期 44 次 `has_column` 逐项往返探测
- **P14** `worker.go:154-156` 并发打满后 500ms 忙等 + `:146 IsNodeEnabled` Redis GET **2 次/秒/实例**
- **P15** `EpisodeDetail.tsx:198/239` 赋值前**未先 clear 旧句柄**（`:290` 有 clear）→ 重复调用产生孤儿定时器

---

## 5. 被推翻 / 修正的初步信号（体现审查严谨性）

| 初步信号 | 结论 |
|---|---|
| `engines/remove_mask_rois.py` 是死代码 | **推翻** —— 被 4 处动态导入（`watermark_runner.py:153`、`seedance_wm_runner.py:154`、`remove_mask_remover.py:59`、`seedance_watermark_remover.py:342`） |
| `scripts/server-setup.sh` 近死代码 | **推翻** —— 是 `curl\|bash` 引导入口（脚本第 6 行自述） |
| LLM 客户端三处重复实现 | **推翻** —— 实为三层调用链（`llm_client`→`llm_manager`→`llm_providers`）。真问题是循环导入 + 3 个 provider 零配置 |
| `ark_client.py` 与 LLM 栈重复 | **推翻** —— 它是火山方舟 **Seedance 视频生成**客户端（`ARK_BASE:33`、`SeedanceClient:185`），零重叠 |
| `seedance_watermark_remover.py` 可废 | **推翻** —— 是 `remove_ai` 的回退承重件。可废的是 `seedance_wm/` 包 |
| 上传路径穿越 | **推翻** —— `upload_service.py:239-248 validate_file_name` 做了 `basename` + 扩展名白名单，三处调用点齐全 |
| `minio_service.py` key 拼接不安全 | **推翻** —— 该文件只接收上层构造好的 key，自身无拼接 |
| Worker token 全局共享 | **推翻** —— `api/slice.py:415` 每任务 `secrets.token_hex(16)`，`:451` 带 TTL，`:866-873` `compare_digest`，`:901-905` 强制 `basename` 且 key 前缀锁定 `slices/{episode}/{task}/` → **设计正确** |
| `api/maintenance.py` 可未授权删数据 | **推翻** —— 4/4 端点均 `require_roles(admin)`（`:42/54/65/76`） |
| `/docs`、`/openapi.json` 对外可达 | **推翻** —— nginx 仅代理 4 条 location，`/docs` 落到 frontend；backend 绑 127.0.0.1 |
| SQL 裸拼接注入 | **推翻** —— 全仓无 f-string SQL（唯一 `text(f...)` 为静态元组），统一 SQLAlchemy 参数化 |
| `.env` 进 git / 镜像 | **推翻** —— `.gitignore:2-5` 已忽略，`git log --all -- .env` 无历史；各 Dockerfile 无 `COPY .env`，走 `env_file` |
| `dashboard.py` 有 N+1 | **推翻** —— `:949-968` 与 `:1067-1084` 已用 `.in_()` + dict map 批量预加载。其慢源自**缺索引**而非查询写法 |
| MinIO 双 client 重复连接 | **推翻** —— `minio_service.py:33/49` 均为模块级单例懒加载 |
| `file_transfer.go` 非流式 | **推翻** —— `:61 os.Create` + `:159 progressReader` 为流式落盘 |
| 连接池配置不合理 | **推翻** —— `database.py:20-24` 30s 超时 + pool 20+10 + pre_ping + recycle 3600，配置合理 |
| Go worker 临时目录泄漏 | **推翻** —— `worker.go:283 defer os.RemoveAll(taskDir)` 清理完备 |
| `nginx /minio/` 可列桶下载 | **部分推翻** —— 无法列桶或下载对象；暴露的是 admin 命名空间与版本指纹 |
| Go 桌面代码占 37% | **修正** —— 实为 **843 行 / 25.9%** |
| `api/upload.py` 7 路由/3 鉴权 | **修正** —— 实为 **6 路由 / 2 鉴权** |
| 建表 3 套机制 | **修正** —— 实为 **5 套** |
| 去水印 2 套实现 | **修正** —— 实为 **4 套引擎并存** |
| （测绘漏报） | `api/shortdrama.py` 有 **16 个**未鉴权路由，风险等同 H2 |

---

## 6. 修复路线图

### 第一批 · 今天就该做（改动极小，收益极大）

| 序 | 项 | 改动 | 等级 | 工作量 |
|---|---|---|---|---|
| **1** | **删 `init.sql:273`** + 存量库用 `CREATE INDEX CONCURRENTLY IF NOT EXISTS` 手工补 28+16 条索引 | 1 行 + 1 个补丁脚本 | 性能·高 | 1h |
| **2** | **删 `compose:369` rpa_worker 的 `ports` 整段** | 3 行 | 安全·高 | 10min |
| **3** | Redis `compose:61` / MinIO `compose:83-84` 改绑 `127.0.0.1`，9001 直接删映射 | 3 行 | 安全·高 | 20min |
| **4** | `main.py:172-188` 所有业务 router 加 `dependencies=[Depends(get_current_user)]`；健康检查与 3 个 Worker Token 端点拆到独立 router | ~20 行 | 安全·高 | 0.5-1d |
| **5** | `config.py:111/116/24` 密钥改**必填无默认**；`main.py:120` 种子用户加 `if settings.DEBUG` 守卫 | ~10 行 | 安全·高 | 0.5d |
| **6** | `config.py:52` CORS 默认改显式域名列表 | 1 行 | 安全·中 | 10min |

> 序 1 与序 2 合计**改动不到 5 行**，分别解决"全库 0 索引"和"浏览器可被任意接管"两个最致命问题。

### 第二批 · 本周（性能止血）

| 序 | 项 | 等级 | 工作量 |
|---|---|---|---|
| 7 | Celery 拆 3 个 worker 容器：`worker-video`(`-Q video_processing -c 1`) / `worker-publish`(`-Q publish -c 1`) / `worker-fast`(`-Q metrics,default -c 4`) | 性能·高 | 0.5d |
| 8 | `engines/slice.py` 加 `fast + 无水印` → `-ss/-to -c copy` + concat demuxer 分支；单 part 时跳过二次 concat 编码 | 性能·高 | 1d |
| 9 | `_rewrite_cb`(`tasks.py:1912-1949`) 改状态机：写 `awaiting_rewrite` 后 return，前端确认触发 `doubao_resume_task` | 性能·高 | 1d |
| 10 | 8 处 `subprocess.run` 补 `timeout=` + `TimeoutExpired: proc.kill()` | 性能·中 | 2h |
| 11 | `speech_recognizer.py:292` whisper 提为模块级单例 | 性能·中 | 1h |
| 12 | CPU 闸门：compose 加 `cpus:` 限额；`slice.py:43` 换 `len(os.sched_getaffinity(0))`；`MAX_CONCURRENT` 2→1 | 性能·中 | 2h |

### 第三批 · 死代码清理（零风险，随时可做）

| 序 | 项 | 减少行数 | 等级 |
|---|---|---:|---|
| 13 | 删 `autoclip/app/celery_app.py` + `run_preview` + `engines/preview.py` + `previews` 桶配置 + 12 项未用依赖 | ~91 | 低 |
| 14 | 废 `engines/seedance_wm/` + `seedance_wm_runner.py` 分支 | **2,329** | 中 |
| 15 | 删 `llm_providers.py:248-508` 三个零配置 provider；修 `llm_manager.py:244` 循环导入 | ~260 | 低 |
| 16 | 三处裸 httpx 收敛到 `autoclip_service` | ~60 | 低 |
| 17 | Go：给 `tui.go`/`tray.go`/`tray_common.go` 加 `//go:build desktop` | 隔离 843 | 低 |
| 18 | 删 `docs/deployment-guide.html`(61KB) + 7 个 ttf(1.5MB)，`docs/README.md` 改索引页 | 70KB | 低 |

### 第四批 · 结构治理（需回归测试）

| 序 | 项 | 等级 |
|---|---|---|
| 19 | 前端接线现有 WS（`main.py:158` + `nginx.conf:119` 已就绪，只需补 Celery 侧广播）；`EpisodeDetail` 三定时器合并为单 tick 调聚合接口 | 中 |
| 20 | 建表机制 5 套 → 1 套：alembic 为唯一权威，去掉 `\|\| echo`，40 条 ADD COLUMN 固化为 squash 迁移 | **高** |
| 21 | 双后端收敛：autoclip 退化为无状态计算服务，状态统一落 backend `autoclip_runs` | 中 |
| 22 | `tasks.py`(2390) 拆 9 文件；`api/slice.py`/`dashboard.py`/`shortdrama.py` 下沉 service | 中 |
| 23 | 前端 3 个 God 组件拆分 | 中 |
| 24 | M1/M2/M6/M8 修复：上传鉴权+增量哈希、drawtext 白名单、subprocess 参数校验、TaskID UUID 校验 | 中 |
| 25 | M7/L1 部署加固：rpa 与 slice-worker Dockerfile 加 `USER`；`deploy_remote_worker.sh` 去掉密码明文落盘 | 中 |

---

## 7. 三个"一行改动"快赢项

1. **`init.sql:273`** —— 删掉这一行 + 补索引脚本，看板从"30s 超时"回到毫秒级。
2. **`docker-compose.yml:369`** —— 删掉 rpa_worker 的 `ports` 段（容器间已通网），关掉全项目唯一一条"零凭据接管浏览器"的攻击链。
3. **`docker-compose.yml:293`** —— 加 `-Q video_processing`（再补两个 worker 容器），发布任务不再排在别人 1 小时的切片后面。

---

*本次审查为纯只读，未修改任何代码。涉及凭据处仅标注行号，未输出任何明文。*
