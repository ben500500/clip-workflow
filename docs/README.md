# Clip Workflow

AI 驱动的智能视频剪辑工作流平台，提供自动化视频剪辑、素材管理、工作流编排等功能。

---

## 目录

- [项目简介](#项目简介)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 文档](#api-文档)
- [开发指南](#开发指南)
- [部署说明](#部署说明)
- [运维管理](#运维管理)

---

## 项目简介

Clip Workflow 是一个基于 AI 的智能视频剪辑平台，支持：

- **智能剪辑**：基于 AI 模型自动识别视频高光时刻，生成精彩片段
- **工作流编排**：可视化编排剪辑流程，支持自定义模板
- **素材管理**：集中管理视频、音频、图片等素材资源
- **多平台适配**：自动裁剪适配不同平台的视频尺寸规格
- **字幕生成**：自动为视频生成字幕并导出多种格式
- **协作编辑**：支持多人协作项目编辑

---

## 系统架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Frontend  │────▶│    Nginx     │────▶│   Backend   │
│  (React/TS) │     │  (反向代理)   │     │ (FastAPI)   │
└─────────────┘     └──────┬───────┘     └──────┬───────┘
                           │                     │
                           │                     ▼
                           │              ┌──────────────┐
                           │              │   AutoClip   │
                           │              │  (AI 剪辑服务) │
                           │              └──────┬───────┘
                           │                     │
                           ▼                     ▼
                    ┌─────────────────────────────────────┐
                    │              Redis                  │
                    │        (Celery Broker/BE)           │
                    └─────────────────────────────────────┘
                           │
                           ▼
                    ┌─────────────────────────────────────┐
                    │           PostgreSQL                │
                    │          (主数据库)                   │
                    └─────────────────────────────────────┘
                           │
                           ▼
                    ┌─────────────────────────────────────┐
                    │            MinIO                    │
                    │       (对象存储/素材)                 │
                    └─────────────────────────────────────┘
```

### 服务说明

| 服务 | 说明 | 端口 |
|------|------|------|
| **Nginx** | 反向代理，统一入口 | 80 |
| **Frontend** | 前端应用 (React/TypeScript) | 3000 |
| **Backend** | 后端 API 服务 (FastAPI) | 8001 |
| **Worker** | Celery 异步任务执行器 | - |
| **Beat** | Celery 定时任务调度器 | - |
| **AutoClip** | AI 智能剪辑 API 服务 | 8000 |
| **AutoClip Worker** | AI 剪辑任务执行器 | - |
| **PostgreSQL** | 主数据库 | 5432 |
| **Redis** | 缓存和消息队列 | 6379 |
| **MinIO** | 对象存储（素材文件） | 9000/9001 |

---

## 技术栈

### 后端
- **运行时**: Python 3.11+
- **Web 框架**: FastAPI
- **ORM**: SQLAlchemy 2.0 + asyncpg
- **任务队列**: Celery + Redis
- **数据验证**: Pydantic v2

### 前端
- **框架**: React 18 + TypeScript
- **构建工具**: Vite
- **状态管理**: Zustand / Redux Toolkit
- **UI 组件**: Ant Design / Tailwind CSS

### AI 引擎
- **AI 模型**: 通义千问 VL 系列 (DashScope API)
- **视频处理**: FFmpeg

### 基础设施
- **容器化**: Docker + Docker Compose
- **数据库**: PostgreSQL 15
- **缓存**: Redis 7
- **对象存储**: MinIO
- **反向代理**: Nginx

---

## 快速开始

### 前置条件

- Docker >= 24.0
- Docker Compose >= 2.20
- Git

### 部署步骤

**方式一：一键部署**

```bash
# 克隆项目
git clone <repository-url> clip-workflow
cd clip-workflow

# 一键部署
bash deploy.sh
```

**方式二：分步部署**

```bash
# 1. 初始化项目
bash scripts/init.sh

# 2. 编辑配置
vim .env

# 3. 构建并启动
bash scripts/start.sh
```

部署完成后访问：
- 前端应用: http://localhost
- API 文档: http://localhost/api/docs
- MinIO 控制台: http://localhost:9001

### 快速验证

```bash
# 查看服务状态
bash scripts/status.sh

# 查看所有日志
bash scripts/logs.sh

# 查看特定服务日志
bash scripts/logs.sh backend
bash scripts/logs.sh nginx -f
```

---

## 配置说明

### 环境变量

项目使用 `.env` 文件管理配置，从 `.env.example` 复制后修改：

```bash
cp .env.example .env
```

### 关键配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `SECRET_KEY` | 应用密钥（必须修改） | - |
| `POSTGRES_PASSWORD` | 数据库密码 | clipworkflow_secret |
| `REDIS_PASSWORD` | Redis 密码 | clipworkflow_redis |
| `MINIO_ROOT_PASSWORD` | MinIO 管理员密码 | minioadmin_secret |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key | - |
| `NGINX_PORT` | Nginx 对外端口 | 80 |
| `APP_ENV` | 运行环境 | development |

### 端口映射

| 端口 | 服务 | 说明 |
|------|------|------|
| 80 | Nginx | 统一入口（可通过 NGINX_PORT 修改） |
| 5432 | PostgreSQL | 数据库（仅内网） |
| 6379 | Redis | 缓存（仅内网） |
| 9000 | MinIO API | 对象存储 API |
| 9001 | MinIO Console | 管理控制台 |

---

## API 文档

启动服务后，API 文档可通过以下地址访问：

- **Swagger UI**: http://localhost/api/docs
- **ReDoc**: http://localhost/api/redoc
- **OpenAPI JSON**: http://localhost/api/openapi.json

### 主要 API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login` | POST | 用户登录 |
| `/api/v1/auth/register` | POST | 用户注册 |
| `/api/v1/projects` | GET/POST | 项目管理 |
| `/api/v1/media` | GET/POST | 素材管理 |
| `/api/v1/clip-tasks` | GET/POST | 剪辑任务 |
| `/api/v1/autoclip` | GET/POST | AI 剪辑 |
| `/api/v1/workflows` | GET/POST | 工作流管理 |
| `/api/v1/health` | GET | 健康检查 |

---

## 开发指南

### 本地开发环境

```bash
# 启动基础设施（数据库、缓存、对象存储）
docker compose up -d postgres redis minio

# 后端开发
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端开发
cd frontend
npm install
npm run dev
```

### 代码规范

- **Python**: 遵循 PEP 8，使用 Black 格式化，Ruff 检查
- **TypeScript**: 使用 ESLint + Prettier
- **提交信息**: 遵循 Conventional Commits 规范

### 项目结构

```
clip-workflow/
├── backend/            # 后端 FastAPI 应用
│   ├── app/
│   │   ├── api/       # API 路由
│   │   ├── core/      # 核心配置
│   │   ├── models/    # SQLAlchemy 模型
│   │   ├── schemas/   # Pydantic 模式
│   │   ├── services/  # 业务逻辑
│   │   └── tasks/     # Celery 任务
│   └── Dockerfile
├── frontend/           # 前端 React 应用
│   ├── src/
│   └── Dockerfile
├── autoclip/           # AI 剪辑服务
│   ├── app/
│   └── Dockerfile
├── engines/            # 引擎脚本
├── scripts/            # 运维脚本
├── docs/               # 文档
├── docker-compose.yml  # Docker Compose 配置
├── nginx.conf          # Nginx 配置
├── init.sql            # 数据库初始化
├── .env.example        # 环境变量模板
└── deploy.sh           # 一键部署脚本
```

---

## 部署说明

### 生产环境部署

```bash
# 1. 配置生产环境变量
cp .env.example .env
# 编辑 .env，设置 APP_ENV=production

# 2. 一键部署
bash deploy.sh
```

### 关键部署注意事项

1. **密钥安全**: 务必修改 `SECRET_KEY`，使用以下命令生成：
   ```bash
   openssl rand -hex 32
   ```

2. **密码安全**: 修改所有默认密码（PostgreSQL、Redis、MinIO）

3. **数据持久化**: 数据存储在 Docker 卷中，默认位置：
   - PostgreSQL: `postgres_data`
   - Redis: `redis_data`
   - MinIO: `minio_data`
   - 媒体文件: `media_data`

4. **备份策略**:
   ```bash
   # 备份数据库
   docker exec clip-postgres pg_dump -U clipworkflow clipworkflow > backup.sql

   # 备份 MinIO 数据
   docker run --rm -v minio_data:/data -v $(pwd):/backup alpine tar czf /backup/minio-backup.tar.gz -C /data .
   ```

---

## 运维管理

### 常用命令

```bash
# 启动服务
bash scripts/start.sh

# 停止服务
bash scripts/stop.sh

# 重启服务
bash scripts/restart.sh

# 查看日志
bash scripts/logs.sh          # 所有服务
bash scripts/logs.sh backend  # 特定服务
bash scripts/logs.sh nginx -f # 实时跟踪

# 查看状态
bash scripts/status.sh
```

### Docker Compose 命令

```bash
# 构建镜像
docker compose build

# 启动服务
docker compose up -d

# 停止服务
docker compose down

# 查看日志
docker compose logs -f

# 重启服务
docker compose restart

# 查看资源使用
docker stats
```

### 故障排查

1. **服务无法启动**
   ```bash
   # 查看详细日志
   docker compose logs <service_name>
   ```

2. **数据库连接失败**
   ```bash
   # 检查数据库状态
   docker compose exec postgres pg_isready -U clipworkflow
   ```

3. **存储空间不足**
   ```bash
   # 清理未使用的 Docker 资源
   docker system prune -af
   ```

---

## 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE](../LICENSE)