# Clip Workflow

AI 驱动的**短剧切片分发自动化平台**：覆盖「上传 → AI 选点(AutoClip) → 通用区间检测 → 多平台去重切片 → RPA 自动发布 → IAA 数据看板」全链路，另含**短片制作**（去水印 / Seedance 提示词 / 豆包出片 / 发布素材）与**分布式切片 Worker（Go）** 扩展。

> 项目详细功能与演进见 [`PROJECT.md`](../PROJECT.md)，本项目记忆见 [`PROJECT_MEMORY.md`](../PROJECT_MEMORY.md)，Agent 约定见 [`CLAUDE.md`](../CLAUDE.md)。

---

## 目录

- [核心能力](#核心能力)
- [系统架构](#系统架构)
- [服务清单](#服务清单)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 说明](#api-说明)
- [前端页面](#前端页面)
- [项目结构](#项目结构)
- [开发指南](#开发指南)
- [部署说明](#部署说明)
- [运维管理](#运维管理)
- [安全与鉴权](#安全与鉴权)

---

## 核心能力

| 链路 | 说明 |
|------|------|
| **导入 → 切片 → 预览** | 上传源视频 → `slice:outputs` 队列 → **Go slice-worker**（Redis Stream `XReadGroup`）→ 直传 MinIO → presigned 播放 |
| **去水印** | `POST /api/watermark/run` → Celery 四路分发（remove_mask / seedance / seedance_wm / RAiW） |
| **AI 选点** | `autoclip_task` → `autoclip:8000/pipeline/run` → ASR + LLM → 写 `clip_candidates` |
| **通用区间检测** | `detect_intervals` → 片尾字幕 / 静止画面 / 水印模式区间检测 |
| **发布** | `task_publish_video` → Playwright CDP 连 `rpa_worker:9222` → 截图审核 → 确认发布 |
| **短片制作** | 去水印 / Seedance 提示词 / 豆包出片 / 发布素材生成 |

**批量切片工作流**：上传源视频 → AI 智能选点 → 自动审核 → 通用区间检测 → 一键切片 → 删除源视频（支持切片配置预设）。

**批量切片解耦模式（可选）**：通过 `slice_config.pipeline_mode="decoupled"` 开启，将「AI 选点」与「切片」解耦为两条独立流水线并行推进（选点完成入「已选点池」，切片投递守护轮询池子并投递到 Go slice-worker），不再逐集串行等待。默认 `serial` 串行模式，行为与历史完全一致。

> **解耦收益定位（重要）**：本模式的价值主要在于「选点」与「切片」**两阶段重叠**（batch A 切片进行时，batch B 的选点已在跑），而非同批次内的选点并行。autoclip 是**单并发服务**，选点阶段天然批内串行（一个 item 的选点即占满该服务）；**autoclip 单并发是解耦提速的上限**。若要进一步提升同批选点并行，需在 autoclip 侧开启 `--concurrency=2~3`，但这会放大 autoclip 服务端单点资源压力。若团队对 autoclip 并发没有资源余量，**保持单并发也能拿到两阶段重叠的解耦收益**，只是上限受限。

---

## 系统架构

```
┌─────────────┐        ┌──────────┐        ┌─────────────┐
│   Frontend  │───────▶│  Nginx   │───────▶│   Backend   │
│ (React/Vite)│ /api/  │ 反代 :80 │ /api/   │ (FastAPI)   │
└─────────────┘        └────┬─────┘        └──────┬──────┘
                            │                     │
                            │ /autoclip/          │
                            ▼                     ▼
                     ┌──────────────┐      ┌──────────────────────┐
                     │   AutoClip   │      │ Redis (Stream/Queue) │
                     │ (AI 剪辑 :8000)│     │ PostgreSQL(主库)     │
                     └──────┬───────┘      └────┬──────┬──────────┘
                            │ ollama            │      │
                            ▼                   ▼      ▼
                     ┌──────────────┐    ┌────────┐ ┌──────────────┐
                     │    Ollama    │    │  MinIO │ │ Go slice-    │
                     │ (MiniCPM-V)  │    │(对象存储)│ │ worker(分布式)│
                     └──────────────┘    └────────┘ └──────────────┘
                                                         │
                                              RPA 发布 ──┘ (rpa_worker:9222)
```

### 数据流要点

- **切片**：上传 → Redis Stream `slice:tasks:{high,normal,low}` → Go slice-worker `XReadGroup` → 申请 upload-url（`X-Worker-Token`）→ `exec engines/slice.py` → 直传 `minio:sliced` → `POST /callback` → 前端 presigned 播放。
- **发布**：`publish` 队列 → `publish_service` → Playwright **CDP 连 `rpa_worker:9222`** → 填表 → 截图 → `pending_confirm` → 人工确认 → 复用同 tab 发布。

---

## 服务清单

| 服务 | 镜像/说明 | 对外端口 | 备注 |
|------|----------|---------|------|
| **nginx** | nginx:1.28-alpine，统一入口 | `${NGINX_PORT:-80}:80` | 反代前端/后端/autoclip/minio/ws |
| **frontend** | React+Vite 静态站 | `127.0.0.1:${FRONTEND_PORT:-3000}:80` | 生产构建后由 nginx 提供 |
| **backend** | FastAPI (uvicorn, --workers 1) | `127.0.0.1:${BACKEND_PORT:-8001}:8080` | 主业务 API |
| **postgres** | postgres:15-alpine | `127.0.0.1:${POSTGRES_PORT:-15432}:5432` | 主数据库 |
| **redis** | redis:7-alpine | `${REDIS_PORT:-16379}:6379` | Stream + Celery broker，需密码 |
| **minio** | minio/minio | `${MINIO_PORT:-9000}:9000` / `9001` | 对象存储（源片/成片/素材） |
| **autoclip** | AI 剪辑服务 | `127.0.0.1:${AUTOCLIP_PORT:-8000}:8000` | ASR + LLM 选点 |
| **ollama** | ollama (MiniCPM-V) | 内网 `11434` | 画面理解模型，不暴露宿主机 |
| **alembic-migrate** | clip-backend | — | 启动时 `alembic upgrade head` |
| **worker-video** | Celery `-Q video_processing` | — | 视频处理任务 |
| **worker-publish** | Celery `-Q publish` | — | 发布任务 |
| **worker-fast** | Celery `-Q metrics,default` | — | 轻量任务 |
| **beat** | Celery beat | — | 定时调度 |
| **rpa_worker** | Xvfb+Chromium+CDP | 内网 `9222` | 发布浏览器基座，**不再对外暴露** |
| **slice-worker** | Go 分布式切片 Worker | — | 消费 Redis Stream，可选多实例 |

> **注意**：`rpa_worker` 不是 Celery worker，是 supervisord 托管的浏览器基座；`slice-worker` 是 Go 程序消费 Redis Stream，**不走 Celery**。

---

## 快速开始

### 前置条件

- Docker >= 24.0
- Docker Compose >= 2.20
- Git

### 部署步骤

```bash
# 克隆项目
git clone <repository-url> clip-workflow
cd clip-workflow

# 复制环境变量并修改（务必设置 JWT_SECRET 等强密钥）
cp .env.example .env
vim .env

# 一键部署（构建镜像 + 启动 + 初始化）
bash deploy.sh
```

访问入口：
- 前端应用: http://localhost
- API 文档(Swagger): http://localhost/api/docs
- MinIO 控制台: http://localhost:9001

### 快速验证

```bash
bash scripts/status.sh          # 查看服务状态
bash scripts/logs.sh            # 所有日志
bash scripts/logs.sh backend    # 特定服务
```

---

## 配置说明

项目使用 `.env` 管理配置，从 `.env.example` 复制后修改。

### 关键配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `JWT_SECRET` | 应用密钥（**必填**，拒绝占位/默认值） | - |
| `COOKIE_ENCRYPT_KEY` | RPA Cookie 加密密钥（与 JWT 分离） | 自动生成 |
| `POSTGRES_PASSWORD` | 数据库密码 | - |
| `REDIS_PASSWORD` | Redis 密码 | - |
| `MINIO_ROOT_PASSWORD` | MinIO 管理员密码 | - |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key | - |
| `SEED_USERS_JSON` | DEBUG 下种子用户 JSON | - |
| `NGINX_PORT` | Nginx 对外端口 | 80 |
| `APP_ENV` | 运行环境 | development |

### 端口映射

| 端口 | 服务 | 说明 |
|------|------|------|
| 80 | Nginx | 统一入口（可用 NGINX_PORT 修改） |
| 15432 | PostgreSQL | 仅内网回环 |
| 16379 | Redis | 供远程 slice-worker 访问（需密码） |
| 9000/9001 | MinIO | 对象存储 / 控制台 |
| 8001 | Backend | 仅内网回环 |

### 批量切片解耦模式（`pipeline_mode=decoupled`）

通过 `slice_config.pipeline_mode="decoupled"` 开启解耦流水线：AI 选点与切片并行推进，不再逐集串行等待。
开启后由三个 Celery beat 任务协同驱动：

| beat 任务 | 职责 | 队列 |
|-----------|------|------|
| `batch_slice_dispatch` | 扫描「已选点池」投递切片到 Go slice-worker | default |
| `batch_slice_finalize` | **终态回收器**：按 `slice_task_id` 查 SliceTask 终态回填 item（成功才删源视频） | default |
| `batch_aggregate` | 按批次聚合 done/failed/output_count，判定批次终态 | default |

选点消费者 `batch_selection_consumer` 路由到独立 **`selection` 队列**（`worker-fast` 已并入消费），
避免重计算 + 长轮询选点抢占串行批处理的 `default` 队列。

> ⚠️ **P0 前提**：终态回收器（`batch_slice_finalize`）是解耦模式批次能完成的必要条件。
> 若未启用该 beat，item 会永久卡在 `slicing`、批次永不完成、源视频不删除，请勿在缺此 beat 时开启解耦模式。

#### 选点并发提升（autoclip）

解耦模式提速上限受 autoclip 单进程并发约束。默认 autoclip 以单进程（`--workers 1`）运行，
并行价值有限。要发挥并行价值，把 autoclip 提到 **2~3 个并发进程**：

```bash
# .env 中配置（重启 autoclip 生效）：
WORKER_CONCURRENCY=2   # 或 3，需 GPU/内存足够
```

docker-compose 已把 `WORKER_CONCURRENCY` 透传给 autoclip 服务，由 uvicorn `--workers` 多进程并行选点。

> 注意：多进程各自持有 LLM / Whisper 实例，需确认显存/内存足够；若开启画面理解（frame analysis）
> 等有状态缓存，多进程下需评估进程间竞争，必要时降低并发。

### 选点结尾优化（`boundary_refine="silence"`）

LLM 选点（step2）产出的 `start_time`/`end_time` 是**裸时间戳**，可能落在句子中间、或把高光剧情
之后的反应/过渡/无关镜头硬收进结尾，导致切片**突然中断**或**高光之后拖尾几秒**。

开启后，生成 cutlist 前用 ffmpeg `silencedetect` 检测源视频的**自然停顿（静音）**，把每个片段的
`start`/`end` 吸附到最近停顿处：

- **end**：吸附到窗口内最近的**静音起点**（上一句讲完处）→ 解决“句子中间硬切”与“高光后拖尾”
- **start**：吸附到窗口内最近的**静音终点**（下一句说话开始处）→ 解决“开头截在半句话里”

开启方式（二选一，默认关闭、对历史行为零影响）：

```bash
# 1) 单个切片请求透传
curl -X POST .../api/slice/... \
  -H 'Content-Type: application/json' \
  -d '{"boundary_refine": "silence"}'

# 2) 批量切片（串行/解耦模式）在 slice_config 里开启
slice_config: { "pipeline_mode": "serial", "boundary_refine": "silence" }
```

- 静音检测失败、窗口内无自然停顿、或源视频不可达时，**自动回退原边界**，不影响主流程。
- 仅当 `end`/`start` 附近 1.5s 窗口内有静音才吸附，保证只做“把切点挪到自然停顿”这类无损精修。

---

## API 说明

启动后 API 文档可访问：
- **Swagger UI**: http://localhost/api/docs
- **ReDoc**: http://localhost/api/redoc
- **OpenAPI JSON**: http://localhost/api/openapi.json

### 主要 API 模块（`backend/app/api/`）

| 模块 | 前缀 | 说明 |
|------|------|------|
| `auth.py` | `/api/auth` | 登录/刷新/登出/用户管理 |
| `projects.py` | `/api/...` | 剧集/项目 |
| `upload.py` | `/api/...` | 分片上传 |
| `autoclip.py` | `/api/...` | AI 智能选点 |
| `intervals.py` | `/api/...` | 通用区间检测 |
| `slice.py` | `/api/...` | 切片任务 + Worker 回调（X-Worker-Token） |
| `preview.py` | `/api/...` | 成品预览 |
| `publications.py` / `publish.py` | `/api/...` | 发布管理 |
| `dashboard.py` | `/api/...` | IAA 数据看板 |
| `workers.py` | `/api/...` | 分布式 Worker 节点管理/心跳 |
| `monitor.py` | `/api/...` | 监控告警 |
| `maintenance.py` | `/api/...` | 运维优化（归档/清理/生命周期） |
| `watermark.py` | `/api/...` | 去水印 |
| `shortdrama.py` | `/api/...` | 短片制作（Seedance/豆包） |
| `publish_material.py` | `/api/...` | 发布素材 |
| `batch_slice.py` | `/api/...` | 批量切片工作流 |
| `config.py` | `/api/...` | 平台去重配置 |

---

## 前端页面

| 路由 | 页面 | 说明 |
|------|------|------|
| `/login` | Login | 登录 |
| `/dashboard` | Dashboard | 总览 |
| `/projects`、`/projects/:id` | Projects / ProjectDetail | 项目/剧集 |
| `/episodes/:id` | EpisodeDetail | 剧集详情 |
| `/episodes/:id/clips` | ClipReview | 片段审核 |
| `/episodes/:id/intervals` | IntervalDetection | 区间检测 |
| `/episodes/:id/slice` | SliceTasks | 切片执行 |
| `/episodes/:id/preview` | OutputPreview | 成品预览 |
| `/publish` | PublishManagement | 发布管理 |
| `/analytics/*` | 看板系列 | overview/shortdrama/content/monetization/funnel/ecosystem/import/settings |
| `/profile` | Profile | 个人资料 |
| `/user-management` | UserManagement | 用户管理 |
| `/workers` | Workers | Worker 节点 |
| `/monitor` | Monitor | 监控告警 |
| `/maintenance` | Maintenance | 运维优化 |
| `/watermark` | ShortDrama | 短片制作 |
| `/batch-slice` | BatchSlice | 批量切片 |
| `/settings` | Settings | 系统设置 |

---

## 项目结构

```
clip-workflow/
├── backend/              # 后端 FastAPI 应用
│   ├── app/
│   │   ├── api/         # 19 个 API 模块
│   │   ├── models/      # SQLAlchemy 模型（models.py，36 个）
│   │   ├── services/    # 17 个业务服务
│   │   ├── celery/      # Celery 任务
│   │   ├── engines/     # 引擎调用
│   │   ├── auth.py      # JWT/会话/鉴权
│   │   ├── config.py    # 配置
│   │   ├── database.py  # 数据库
│   │   └── main.py      # 应用入口 + 路由注册/鉴权接线
│   └── Dockerfile
├── frontend/             # 前端 React + Vite
│   ├── src/pages/       # 29 个页面
│   └── Dockerfile
├── autoclip/             # AI 剪辑服务
├── engines/              # 引擎脚本（slice / detect_intervals / 去水印 / vert2horiz）
├── slice-worker/         # Go 分布式切片 Worker
├── rpa/                  # RPA 发布浏览器基座（CDP）
├── alembic/              # 数据库迁移（22 个版本）
├── migrations/           # 存量库补丁（fix_missing_indexes.sql）
├── scripts/              # 运维脚本
├── docs/                 # 文档
├── docker-compose.yml
├── nginx.conf
├── init.sql
├── .env.example
└── deploy.sh
```

---

## 开发指南

### 本地开发

```bash
# 启动基础设施（数据库、缓存、对象存储）
docker compose up -d postgres redis minio

# 后端开发
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080

# 前端开发
cd frontend
npm install
npm run dev
```

### 数据库迁移

```bash
# 生成迁移
alembic -c alembic/alembic.ini revision --autogenerate -m "描述"
# 应用迁移
alembic -c alembic/alembic.ini upgrade head
```

### 代码规范

- **Python**：PEP 8 + Black 格式化 + Ruff 检查
- **TypeScript**：ESLint + Prettier
- **提交信息**：Conventional Commits（`feat:`/`fix:`/`docs:`/`refactor:`）

---

## 部署说明

### 生产环境

```bash
cp .env.example .env
# 设置 APP_ENV=production，并配置 JWT_SECRET / 各类密码
bash deploy.sh
```

### 关键注意事项

1. **密钥安全**：`JWT_SECRET` 为必填，后端启动即校验，拒绝占位/默认值；`COOKIE_ENCRYPT_KEY` 自动生成并与 JWT 分离。生成强密钥：
   ```bash
   openssl rand -hex 32
   ```
2. **密码安全**：修改 PostgreSQL / Redis / MinIO 默认密码。
3. **数据持久化**：数据存 Docker 卷（`postgres_data` / `redis_data` / `minio_data` / `media_data` / `chrome_profiles` / `ollama_data`）。
4. **远程 Worker**：如需远程 slice-worker，参考 `deploy_remote_worker.sh` 与 `docs/remote-worker-部署说明.md`。
5. **代码同步**：CNB 主仓 + GitHub 备份仓，`scripts/sync_remotes.sh`；cnb remote URL 必须内联 access token。

### 初始化首个管理员账号

部署完成后必须先初始化第一个管理员账号才能登录系统：生产模式（`DEBUG=false`）启动不自动建账号，且注册接口要求调用者已是管理员，因此首个 admin 需通过「临时开启 `DEBUG` + 种子账号」通道创建。项目已内置 `scripts/init_admin.sh` 自动完成该流程（创建成功后自动还原 `DEBUG` 并清除明文密码）：

```bash
# 交互输入账号密码
bash scripts/init_admin.sh

# 或非交互（适合一键部署 / CI）
INIT_ADMIN_USER=admin INIT_ADMIN_PASS='你的强口令' bash scripts/init_admin.sh
```

脚本会临时把 `DEBUG` 改为 `true` 并写入 `SEED_USERS_JSON` → 重启 backend 自动创建管理员 → 轮询 `/api/v1/auth/login` 验证登录成功 → 还原 `DEBUG` 并删除临时配置。成功后用该账号登录，在「用户管理」创建 operator 等其他成员。

> 用 `scripts/server-setup.sh` 一键部署时，可传 `--admin-user=xxx --admin-pass=xxx`（或部署前 `export INIT_ADMIN_USER / INIT_ADMIN_PASS`）实现部署即自动初始化；否则部署完成提示会引导手动运行上述命令。

---

## 运维管理

```bash
bash scripts/start.sh     # 启动
bash scripts/stop.sh      # 停止
bash scripts/restart.sh   # 重启
bash scripts/logs.sh      # 日志
bash scripts/status.sh    # 状态
bash scripts/server-setup.sh  # 服务器初始化
```

### 故障排查

1. **服务无法启动**：`docker compose logs <service>`
2. **数据库连接失败**：`docker compose exec postgres pg_isready -U <user>`
3. **存量库缺索引**：执行 `psql -f migrations/fix_missing_indexes.sql`（`CREATE INDEX CONCURRENTLY` 需在事务外运行）

---

## 安全与鉴权

详见 [`docs/reviews/AUTH_AUDIT.md`](reviews/AUTH_AUDIT.md) 的完整复核报告。要点：

- **17 个业务 router 统一 `Depends(get_current_user)`**（`main.py:197`），全端点 JWT 鉴权。
- `auth`（login/refresh 开放）、`slice.worker_router`（X-Worker-Token）、`workers.internal_router`（管理端点 admin）走独立鉴权。
- 08-10 审查报告中的高危项（100 端点零鉴权、CDP 9222 暴露、种子弱口令、密钥默认值、全库 0 索引）**均已修复**。
- 低风险遗留：`POST /api/workers/heartbeat` 无 Token、WebSocket 进度无鉴权（仅进度/状态，不涉数据操作），可后续按需优化。

---

## 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE](../LICENSE)

## 素材库相关文档（补充索引）
- `docs/项目进度总览-20261109.md` §四·乙 —— 11-13 批（试产/钱面下架/三席评审/163 事故）
- `docs/项目进度总览-20261109.md` §四·丙 —— **11-23 S0' 拆包收口**（包级 patch 静默失效修复、测试基线 138/160 红→668 绿、`assets.py` 壳化；11-24 复核：**已推 cnb、已随极简批在现网**，判据见 §四·丁 部署实录）
- `docs/项目进度总览-20261109.md` §四·丁 —— **11-23 深夜极简模式 S1＋S2**（脚本库＋轻量过审＋脚本直投＋ui_config 开关）＋当晚**已推 cnb／已上 163 现网**的部署实录
- `docs/项目进度总览-20261109.md` §四·戊 —— **11-24 需求三 S3＋S4**（组合导出矩阵＋叠加预设＋屏 3＋批量出包）：三道门＋**163 真数据本机实测 13/13**，含两条误报撤回与一条命名新问题；**未推、未上现网**
- `docs/项目进度总览-20261109.md` §四·己 —— **11-24 下午极简改版**（用户判「过度简化」→ 四步页签改回＋素材首帧预览点开即播＋组合出片矩阵卡从界面撤下、后端零改动）；`tsc` 干净＋CDP **27/27**；**已随批 T 提交推齐并开 PR #403，未上现网**
- `docs/项目进度总览-20261109.md` §四·庚 —— **11-24 傍晚批 T 素材隔离**（一颗「仅看自己」全局开关，缺省关＝看全部＋脚本库收藏列：「仅看自己」＝我写的 ∪ 我收藏的、收藏**只改可见范围不改归属**；推掉 A′ 按角色默认）：全量 **710 passed**／`tsc` 干净／CDP **58/58**（网络层判据抓出顶栏「待投」角标不跟开关走，已修）；**已推齐双远端、PR #403、未上现网**
- `docs/1124-极简模式改版-四步页签与素材预览.md` —— 用户「过度简化」这条原话拆成的四条要求、四步页签与共用预览组件（`SimplePreviewBits.tsx`）的落法、组合出片从界面撤下但后端一行未动、CDP 门自身修的三个坑
- `docs/1124-素材隔离-仅看自己开关与脚本收藏.md` —— 批 T 全口径：三条硬约束→判据、后端收藏表与 `owner` 四口、**收藏改可见范围不改归属**、推掉 A′ 按角色默认的后果、`useOwnerView` 一座桥喂五处、门禁四条假红与那条真缺口
- `docs/1123-素材库全景与极简模式施工方案.md` —— 素材库全景（代码/数据/链路/闸门/现网实数）＋极简模式 S0'–S4 施工方案；§9.4b 记拆包 patch 坑、§9.5b 记 4 个开工前必定的设计缺口、**§12 记 S3＋S4 落地实录与上现网前清单**
- `docs/1123-素材库极简模式-需求评审与实现方案.md` —— 两条需求的评审纪要（六问拍板原文、S1–S4 定稿）；§8b 是 S3＋S4 补记（mock 门 vs 真站点门两套判据）
- `docs/1123-极简模式-收尾与上现网实施方案.md` —— 极简模式收尾五步（git 自洽／文档订正／CDP 门／上现网）＋§5.1 部署实录＋**§8 S3＋S4 部署清单（尚未执行）**
- 试产功能：`POST /assets/productions/{id}/trial-verdict`（判定口）＋ `DispatchRequest.trial_only`（审核职能投试产）
- 拆包纪律：**任何"模块搬进包再反射转发"的做法必须带「包级 patch 能穿到实现模块」的用例**（否则 300+ 处 mock 静默失效，报错像业务 bug）
- 判现网版本纪律：**`.deploy_last_commit` 只在走 `deploy_server.sh` 时更新，手工 scp＋build 会把它留在旧值**；要看「镜像构建时间＋镜像内 grep 得到接口＋库里 `alembic_version`」三件套（11-23 曾据此误判"现网落后 113 支"）
- 跑全量 pytest 的**代理**前提：`NO_PROXY` 里含 `::1` 会让 httpx 抛 `InvalidURL: Invalid port: ':1]'`，`tests/unit/test_wechat_dl_*` 五个文件**整片假红 44 条**（11-24 首跑就踩）。跑前 `env -u NO_PROXY -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY …` 清干净再判，别去动业务代码。
- 跑全量 pytest 的环境前提：三组用例会**按仓库根相对路径取文件**（测试在 `/app/tests/…`，`parents[3]` 解出 `/`），后端镜像里只有 `/app`，所以直接 `docker exec clip-backend pytest tests/` 会得到 **12 条与代码无关的红**（11-24 实测：4 failed＋8 errors）——`/alembic`、`/autoclip/app/prompt/`、以及超时链用例的 **4 个文件**（`nginx.conf`、`frontend/nginx.conf`、`frontend/src/api/client.ts`、`frontend/src/api/assets.ts`）。⚠️ **别只补前三个位置**：11-24 我第一次就只补了 `alembic`／`autoclip/app`／`frontend/nginx.conf`，复跑仍剩 1 failed，`FileNotFoundError` 只是换了路径。**六件补齐才作数**，完整命令见 `1123-素材库全景与极简模式施工方案.md` §12.5。

