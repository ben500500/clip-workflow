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
