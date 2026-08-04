# 短剧切片工作流系统 — 项目文档

> 版本：v2.0 | 更新日期：2026-08-04
>
> 覆盖：切片工作流 + 视频号自动发布 + IAA 数据看板

---

## 一、项目简介

短剧切片工作流系统（Clip Workflow）是一套面向短剧分发团队的端到端自动化平台。系统将传统的 Shell 脚本流水线封装为 Web 工作流，覆盖从正片上传到发布变现的全链路：

1. **AI 智能选点** — 基于 AutoClip（通义千问 ASR + LLM）自动识别高光片段
2. **通用区间挖洞** — 检测任意需移除的内容段（不限于片尾）
3. **多平台去重切片** — 按视频号/抖音/快手分别应用去重 Profile
4. **视频号自动发布** — Playwright RPA 浏览器自动化，含小程序挂载引导
5. **IAA 数据看板** — 打通「视频号内容 → 小程序短剧 → 广告收益」全链路漏斗

### 核心原则

- **最小侵入**：现有 Shell 脚本原样保留，后端仅做调度层
- **配置外置**：所有参数暴露到前端界面，无需改代码
- **数据驱动**：收益归因到单条视频，全链路漏斗可诊断

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                         React Frontend                               │
│  (Vite + React 18 + Ant Design 5 + ECharts + Zustand)               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐│
│  │素材管理 │ │选点工作台│ │区间检测 │ │任务监控 │ │成品库   │ │发布管理 ││
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘│
│  ┌────────┐ ┌────────┐ ┌────────┐                                  │
│  │数据看板 │ │数据录入 │ │系统设置 │                                  │
│  └────────┘ └────────┘ └────────┘                                  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ REST API + WebSocket
┌──────────────────────────▼───────────────────────────────────────────┐
│                         FastAPI Backend                               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐            │
│  │上传服务 │ │项目管理 │ │切片引擎 │ │发布调度 │ │数据看板 │            │
│  │ (tus)  │ │ CRUD   │ │ 调度器  │ │ (RPA)  │ │聚合计算 │            │
│  └───┬────┘ └────────┘ └───┬────┘ └───┬────┘ └───┬────┘            │
│      └─────────────────────┴──────────┴──────────┘                  │
│                       Celery Worker Pool                             │
│  task_autoclip │ task_detect │ task_slice │ task_publish │ task_data │
└──────────┬───────────────────────────────┬───────────────────────────┘
           │                               │
    ┌──────▼──────┐                 ┌──────▼──────┐
    │  PostgreSQL  │                 │    MinIO     │
    │ (元数据+     │                 │ (视频+图片)  │
    │  看板数据)   │                 │              │
    └─────────────┘                 └─────────────┘
           │
    ┌──────▼──────┐
    │    Redis     │
    │ (队列+缓存)  │
    └─────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────────────┐
    │                    外部服务层                                      │
    │  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
    │  │  AutoClip    │  │  Playwright  │  │  浏览器自动化发布        │  │
    │  │  (AI选点)    │  │  RPA Worker  │  │  视频号/抖音/快手       │  │
    │  └─────────────┘  └──────────────┘  └────────────────────────┘  │
    └─────────────────────────────────────────────────────────────────┘
```

---

## 三、技术栈

| 层级 | 技术选型 |
|------|---------|
| 前端 | React 18 + TypeScript + Vite 5 + Ant Design 5 + ECharts + Zustand |
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2.0 (async) + Celery 5 |
| 数据库 | PostgreSQL 15 |
| 缓存/队列 | Redis 7 |
| 对象存储 | MinIO |
| 反向代理 | Nginx 1.25 |
| AI 选点 | 通义千问 ASR (qwen3-asr-flash) + LLM (qwen-plus) |
| 自动发布 | Playwright + Chromium (CDP 协议) |
| 容器化 | Docker + Docker Compose |
| 视频处理 | FFmpeg (通过 Shell 脚本封装) |

---

## 四、项目结构

```
clip-workflow/
├── .env.example              # 环境变量配置模板
├── .gitignore
├── LICENSE
├── deploy.sh                 # 本地一键部署脚本
├── docker-compose.yml        # 容器编排（12 个服务）
├── init.sql                  # 数据库初始化（28 张表）
├── nginx.conf                # Nginx 反向代理配置
│
├── autoclip/                 # AutoClip AI 选点服务
│   ├── Dockerfile
│   └── requirements.txt
│
├── backend/                  # 后端主服务
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py           # FastAPI 入口
│       ├── config.py         # 配置管理（Pydantic Settings）
│       ├── database.py       # 异步数据库引擎
│       ├── api/              # API 路由层（10 个模块）
│       │   ├── projects.py   # 项目 CRUD
│       │   ├── upload.py     # 文件上传（tus 分片）
│       │   ├── autoclip.py   # AI 选点
│       │   ├── intervals.py  # 区间检测
│       │   ├── slice.py      # 切片执行
│       │   ├── preview.py    # 预览生成
│       │   ├── publications.py # 发布记录
│       │   ├── publish.py    # 发布管理（v2）
│       │   ├── dashboard.py  # 数据看板（v2）
│       │   └── config.py     # 系统配置
│       ├── models/
│       │   └── models.py     # 18 个 ORM 模型
│       ├── services/         # 业务逻辑层（8 个服务）
│       │   ├── upload_service.py
│       │   ├── autoclip_service.py
│       │   ├── interval_service.py
│       │   ├── slice_service.py
│       │   ├── minio_service.py
│       │   ├── publish_service.py    # RPA 发布（v2）
│       │   ├── dashboard_service.py  # 看板聚合（v2）
│       │   └── data_import_service.py # Excel 导入（v2）
│       ├── celery/
│       │   └── tasks.py      # 5 个异步任务
│       └── utils/
│           └── helpers.py
│
├── frontend/                 # 前端应用
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── App.tsx           # 路由定义（14 个页面）
│       ├── main.tsx          # 入口
│       ├── api/              # API 客户端（9 个模块）
│       ├── components/       # 通用组件（5 个）
│       ├── pages/            # 页面组件（13 个）
│       ├── types/            # TypeScript 类型定义
│       └── utils/            # 工具函数
│
├── rpa/                      # RPA 自动发布模块（v2）
│   ├── Dockerfile            # Playwright + Xvfb + Chromium
│   ├── requirements.txt
│   └── app/
│       ├── celery_app.py     # Celery 实例（publish 队列）
│       ├── config.py
│       ├── tasks.py          # 4 个发布任务
│       └── publishers/
│           ├── wechat.py     # 视频号 Publisher
│           ├── douyin.py     # 抖音 Publisher
│           └── kuaishou.py   # 快手 Publisher
│
├── engines/                  # 视频处理引擎（Shell 脚本）
│   └── README.md
│
├── docs/                     # 文档
│   ├── README.md
│   └── deployment-guide.html # 部署操作指南
│
└── scripts/                  # 运维脚本
    ├── server-setup.sh       # 阿里云一键部署
    ├── start.sh / stop.sh / restart.sh
    ├── status.sh / logs.sh
    └── init.sh
```

---

## 五、数据库设计

### 5.1 表清单（28 张表）

#### 用户与认证

| 表名 | 说明 |
|------|------|
| `users` | 用户账号（角色：user/admin/superadmin） |
| `user_sessions` | 登录会话（JWT refresh token） |
| `user_oauth_accounts` | OAuth 第三方账号绑定 |

#### 项目与工作流

| 表名 | 说明 |
|------|------|
| `projects` | 项目（包含剧集的容器） |
| `project_members` | 项目协作成员 |
| `workflow_templates` | 工作流模板 |
| `project_versions` | 项目版本历史（v2） |

#### 素材与剪辑

| 表名 | 说明 |
|------|------|
| `media_assets` | 素材文件（视频/音频/图片） |
| `media_tags` / `media_asset_tags` | 素材标签 |
| `clip_tasks` | 剪辑任务 |
| `autoclip_configs` | AutoClip 配置 |
| `autoclip_history` | AutoClip 执行历史 |

#### ORM 模型（SQLAlchemy）

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `Project` | `projects` | 项目 |
| `Episode` | `episodes` | 剧集 |
| `AutoClipProject` | `autoclip_projects` | AutoClip 项目关联 |
| `ClipCandidate` | `clip_candidates` | AI 选点候选片段 |
| `DetectedInterval` | `detected_intervals` | 检测到的待挖洞区间 |
| `SliceTask` | `slice_tasks` | 切片任务 |
| `SliceOutput` | `slice_outputs` | 切片输出文件 |
| `Publication` | `publications` | 发布记录 |
| `PlatformProfile` | `platform_profiles` | 平台去重配置 |
| `SystemConfig` | `system_config` | 系统配置 |

#### V2 发布管理

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `PublishTask` | `publish_tasks` | 发布任务（含平台、状态、截图审核） |
| `PublishProfile` | `publish_profiles` | 发布配置（Chrome 端口、模板、频率限制） |

#### V2 IAA 数据看板

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `VideoMetric` | `video_metrics` | 视频内容数据（播放/互动/跳转/归因） |
| `MiniProgramMetric` | `mini_program_metrics` | 小程序数据（UV/播放/完播率） |
| `AdMetric` | `ad_metrics` | 广告数据（曝光/点击/eCPM/收益） |
| `DramaMetric` | `drama_metrics` | 分剧维度数据 |
| `FunnelSnapshot` | `funnel_snapshots` | 漏斗快照（每日计算） |
| `EcosystemMetric` | `ecosystem_metrics` | 生态数据（公众号/企微） |

### 5.2 ER 关系

```
projects ──1:N──> episodes ──1:N──> clip_candidates
                        │
                        ├──1:N──> detected_intervals
                        │
                        ├──1:N──> slice_tasks ──1:N──> slice_outputs
                        │                                    │
                        │                                    ├──1:N──> publish_tasks
                        │                                    │
                        │                                    └──1:N──> video_metrics
                        │
                        └──1:1──> autoclip_projects

dashboard:
    video_metrics ──N:1──> publish_tasks
    mini_program_metrics (独立)
    ad_metrics (独立)
    drama_metrics (独立)
    funnel_snapshots (独立)
    ecosystem_metrics (独立)
```

---

## 六、API 接口

### 6.1 工作流 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST` | `/api/projects` | 项目列表/创建 |
| `GET/PUT/DELETE` | `/api/projects/{id}` | 项目详情/更新/删除 |
| `POST` | `/api/upload/init` | 初始化上传 |
| `POST` | `/api/upload/chunk` | 上传分片 |
| `POST` | `/api/upload/complete` | 完成上传 |
| `POST` | `/api/autoclip/start` | 启动 AI 选点 |
| `GET` | `/api/autoclip/status/{id}` | 选点进度 |
| `POST` | `/api/intervals/detect` | 启动区间检测 |
| `POST` | `/api/slice/execute` | 执行切片 |
| `GET` | `/api/preview/{id}` | 获取预览 |

### 6.2 发布管理 API（v2）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/publish/tasks` | 创建发布任务 |
| `GET` | `/api/publish/tasks` | 发布任务列表（支持 platform/status/date 过滤） |
| `GET` | `/api/publish/tasks/{id}` | 任务详情 |
| `POST` | `/api/publish/tasks/{id}/confirm` | 截图审核后确认发布 |
| `GET` | `/api/publish/profiles` | 发布配置列表 |
| `POST` | `/api/publish/profiles` | 创建发布配置 |
| `PUT` | `/api/publish/profiles/{id}` | 更新发布配置 |
| `DELETE` | `/api/publish/profiles/{id}` | 删除发布配置 |

### 6.3 数据看板 API（v2）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/dashboard/overview` | 总览（今日/本周收益、播放、UV、eCPM） |
| `GET` | `/api/dashboard/overview/trend` | 趋势数据 |
| `GET` | `/api/dashboard/overview/funnel` | 漏斗数据 |
| `GET` | `/api/dashboard/overview/top-videos` | TOP 视频 |
| `GET` | `/api/dashboard/videos` | 视频指标列表（分页+排序） |
| `GET` | `/api/dashboard/videos/{id}` | 视频详情 |
| `PUT` | `/api/dashboard/videos/{id}/tags` | 更新视频标签 |
| `GET` | `/api/dashboard/videos/ranking` | 视频排行 |
| `GET` | `/api/dashboard/mini-program` | 小程序指标 |
| `GET` | `/api/dashboard/ads` | 广告指标 |
| `GET` | `/api/dashboard/dramas` | 分剧排行 |
| `GET` | `/api/dashboard/funnel` | 漏斗数据 |
| `GET` | `/api/dashboard/funnel/trend` | 漏斗趋势 |
| `POST` | `/api/dashboard/metrics/video` | Excel 导入视频数据 |
| `POST` | `/api/dashboard/metrics/mini-program` | Excel 导入小程序数据 |
| `POST` | `/api/dashboard/metrics/ads` | Excel 导入广告数据 |
| `GET` | `/api/dashboard/metrics/template` | 下载导入模板 |
| `GET/PUT` | `/api/dashboard/config` | 看板配置 |

### 6.4 WebSocket

| 路径 | 说明 |
|------|------|
| `/ws/progress/{task_id}` | 实时任务进度推送 |

---

## 七、前端页面

### 7.1 页面清单

| 路由 | 页面 | 说明 |
|------|------|------|
| `/dashboard` | 仪表盘 | 项目概览、最近任务 |
| `/projects` | 项目列表 | 项目 CRUD |
| `/projects/:id` | 项目详情 | 剧集列表、项目设置 |
| `/episodes/:id` | 剧集详情 | 素材信息、操作入口 |
| `/episodes/:id/clips` | 片段审核 | AI 选点结果审核 |
| `/episodes/:id/intervals` | 区间检测 | 挖洞区间审核 |
| `/episodes/:id/slice` | 切片任务 | 切片执行与进度 |
| `/episodes/:id/preview` | 输出预览 | 帧图/视频预览、下载 |
| `/publish` | 发布管理 | 发布任务列表、配置管理 |
| `/analytics/overview` | 数据总览 | 收益卡片、趋势图、漏斗、TOP5 |
| `/analytics/content` | 内容分析 | 视频数据表、排行、多维筛选 |
| `/analytics/import` | 数据录入 | Excel 上传、模板下载 |
| `/settings` | 系统设置 | 全局参数配置 |

### 7.2 导航菜单

```
仪表盘
项目管理
发布管理
数据看板
  ├── 总览
  ├── 内容分析
  └── 数据录入
系统设置
```

### 7.3 前端依赖

| 库 | 版本 | 用途 |
|----|------|------|
| React | 18.2 | UI 框架 |
| React Router | 6.22 | 路由 |
| Ant Design | 5.15 | UI 组件库 |
| @ant-design/charts | 2.1 | 图表组件 |
| Axios | 1.6 | HTTP 客户端 |
| Zustand | 4.5 | 状态管理 |
| Day.js | 1.11 | 日期处理 |
| Vite | 5.1 | 构建工具 |
| TypeScript | 5.3 | 类型系统 |

---

## 八、异步任务

### 8.1 Celery 任务清单

| 任务名 | 队列 | 说明 |
|--------|------|------|
| `autoclip_task` | `video_processing` | 执行 AutoClip 流水线，轮询进度，获取片段结果 |
| `detect_task` | `video_processing` | 通用区间检测 |
| `slice_task` | `video_processing` | 视频切片（支持 scrub/fast 模式） |
| `task_publish_video` | `publish` | RPA 视频发布（截图审核 → 确认 → 发布） |
| `task_collect_metrics` | `metrics` | 定期指标采集与漏斗快照计算 |

### 8.2 RPA 发布任务

| 任务名 | 平台 | 说明 |
|--------|------|------|
| `publish_wechat_channels` | 微信视频号 | Playwright 连接 Chrome CDP，自动上传/填写/截图/发布 |
| `publish_douyin` | 抖音 | 同上，页面结构不同 |
| `publish_kuaishou` | 快手 | 同上 |
| `check_cookie_status` | 全平台 | 定期检查登录态是否有效 |

---

## 九、Docker 服务编排

### 9.1 服务列表（12 个）

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `postgres` | postgres:15-alpine | 5432 | 数据库 |
| `redis` | redis:7-alpine | 6379 | 缓存 + 消息队列 |
| `minio` | minio/minio:latest | 9000/9001 | 对象存储 |
| `minio_init` | minio/mc:latest | — | Bucket 初始化（一次性） |
| `autoclip` | 构建自 ./autoclip | 8000 | AI 选点 API |
| `autoclip_worker` | 同 autoclip | — | AI 选点 Worker |
| `backend` | 构建自 ./backend | 8000 | 主 API 服务 |
| `worker` | 同 backend | — | 视频处理 Worker |
| `beat` | 同 backend | — | Celery 定时调度 |
| `rpa_worker` | 构建自 ./rpa | 9222 | RPA 发布 Worker（可选） |
| `frontend` | 构建自 ./frontend | 80 | 前端静态文件 |
| `nginx` | nginx:1.25-alpine | 80 | 反向代理入口 |

### 9.2 数据卷

| 卷名 | 用途 |
|------|------|
| `postgres_data` | 数据库持久化 |
| `redis_data` | Redis AOF 持久化 |
| `minio_data` | 对象存储数据 |
| `media_data` | 媒体文件缓存 |
| `chrome_profiles` | Chrome 浏览器 Profile（RPA 用） |

### 9.3 Nginx 路由规则

| 路径 | 代理目标 | 说明 |
|------|---------|------|
| `/` | `frontend:80` | 前端静态文件（30 天缓存） |
| `/api/` | `backend:8000` | 后端 API |
| `/autoclip/` | `autoclip:8000` | AutoClip API（rewrite 去前缀） |
| `/ws/` | `backend:8000` | WebSocket（长连接 86400s） |
| `/minio/` | `minio:9000` | MinIO 代理（500M 上传限制） |
| `/health` | 200 OK | 健康检查 |

---

## 十、IAA 数据看板

### 10.1 业务链路

```
视频号短视频发布
   │ ① 播放（播放量/完播率/互动）
   ▼
用户点击跳转（视频挂载链接 / 评论区引导 / 主页入口）
   │ ② 跳转点击（跳转率）
   ▼
小程序打开短剧页
   │ ③ 开播（UV、播放次数）
   ▼
短剧内广告展示（激励视频/插屏/开屏）
   │ ④ 广告曝光 → 点击 → 结算
   ▼
IAA 分成收益（eCPM × 曝光 / 1000）
```

### 10.2 指标体系（五层）

| 层级 | 关注问题 | 核心指标 |
|------|---------|---------|
| L1 总览 | 今天赚了多少？ | 累计/今日收益、累计播放、小程序UV、eCPM |
| L2 内容 | 视频表现如何？ | 播放量、完播率、互动率、社交推荐占比、跳转率 |
| L3 短剧 | 小程序和广告表现？ | 小程序UV、短剧完播率、广告曝光、eCPM |
| L4 漏斗 | 转化断在哪？ | 播放→跳转→开播→广告曝光→收益 各环节转化率 |
| L5 生态 | 公众号/企微反哺？ | 公众号导流UV、企微新增好友 |

### 10.3 数据归因

| 方案 | 适用场景 | 精度 |
|------|---------|------|
| 渠道参数归因 | 小程序接入来源参数 `?from=video&vid=视频ID` | 精确 |
| 间接归因 | 无渠道参数时：单视频收益 = 该视频UV × 当日单UV收益 | 近似 |

---

## 十一、部署指南

### 11.1 环境要求

| 配置项 | 最低要求 | 推荐配置 |
|--------|---------|---------|
| CPU | 4 核 | 8 核+ |
| 内存 | 8 GB | 16 GB+ |
| 磁盘 | 100 GB SSD | 500 GB+ SSD |
| Docker | 20.10+ | 最新稳定版 |
| Docker Compose | 2.0+ | 最新稳定版 |

### 11.2 本地部署

```bash
# 克隆代码
git clone https://github.com/ben500500/clip-workflow.git
cd clip-workflow

# 一键部署
bash deploy.sh
```

### 11.3 阿里云部署

```bash
# SSH 登录服务器后执行
cd /opt && git clone --depth 1 https://github.com/ben500500/clip-workflow.git
cd clip-workflow
bash scripts/server-setup.sh --skip-rpa
```

安全组需放行端口：80（Web）、9001（MinIO 控制台）。

### 11.4 环境变量

首次部署时从 `.env.example` 自动生成 `.env`，包含以下关键配置：

| 配置段 | 关键变量 |
|--------|---------|
| 数据库 | `POSTGRES_PASSWORD` |
| Redis | `REDIS_PASSWORD` |
| MinIO | `MINIO_ROOT_PASSWORD` |
| AutoClip | `DASHSCOPE_API_KEY`（通义千问 API Key） |
| RPA | `CHROME_DEBUG_PORT`、`RPA_REQUIRE_MANUAL_CONFIRM` |

### 11.5 常用运维命令

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f

# 重启服务
docker compose restart

# 停止所有服务
docker compose down

# 更新代码并重建
git pull && docker compose up -d --build

# 仅启动 RPA（如需视频号发布）
docker compose up -d rpa_worker
```

---

## 十二、开发分期

### 一期 MVP（5 周）— 已完成

- 项目脚手架（FastAPI + React + Docker Compose）
- 数据库初始化（28 张表）
- 分片上传 + MinIO 存储
- 素材管理 CRUD
- AutoClip 集成（API 调用 + 配置项暴露）
- 通用区间检测
- 切片执行（多模式：fast/dedupe/scrub）
- 帧图预览 + 视频预览
- 数据看板 MVP（总览 + 内容分析 + 数据录入）

### 二期（+4 周）

- Playwright RPA Worker
- 视频号自动发布 + 截图确认
- 小程序挂载引导
- 短剧变现页（小程序/广告指标 + 分剧排行）
- 转化漏斗完整版
- 视频标签系统 + 多维交叉分析
- 异常预警

### 三期（按需）

- 生态联动页（公众号/企微）
- 目标管理 + 权限体系
- 小程序 API 自动拉取
- GPU 加速编码
- 多平台发布 API 对接

---

## 十三、风险与注意事项

### 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| AutoClip API 不稳定 | 选点失败 | 支持手动选点 fallback |
| FFmpeg 任务 OOM | 服务崩溃 | Worker concurrency=1 |
| Playwright 页面改版 | 自动发布失效 | 监控 + 告警 + 快速修复 |
| Cookie 过期 | 发布中断 | 定期检测 + 提示扫码 |
| 大文件上传中断 | 体验差 | tus 断点续传 |

### 业务风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 视频号检测 RPA 行为 | 账号受限 | 随机延迟 + 人工确认 + 限量（默认 20 条/天） |
| 去重参数被识别 | 切片被限流 | 多平台 Profile 调优 |
| 收益归因不准 | 决策偏差 | 渠道参数归因 + 间接归因双轨 |
| 数据录入滞后 | 看板不准 | 提醒机制 + 未来 API 自动化 |

---

## 十四、附录

### A. 现有脚本清单

| 文件 | 用途 | 部署位置 |
|------|------|---------|
| `slice.sh` | 普通切片（fast/dedupe） | `engines/` |
| `slice_scrub.sh` | 挖洞模式切片 | `engines/` |
| `detect_credits.py` | 区间检测（需泛化） | `engines/` |
| `preview.sh` | 帧图预览 | `engines/` |
| `batch_all.sh` | 批量处理 | `engines/` |
| `dedupe.conf` | 去重参数模板 | `engines/` |
| `autoclip2cutlist.py` | AutoClip 结果转 cutlist | `engines/` |

### B. AutoClip 配置参数

```python
AUTOCLIP_CONFIG = {
    "llm_provider": "dashscope",
    "llm_model": "qwen-plus",
    "asr_model": "qwen3-asr-flash",
    "asr_segment_seconds": 270,
    "min_score_threshold": 60,
    "max_clips": 30,
    "min_duration": 30,
    "max_duration": 180,
    "chunk_size_minutes": 30,
    "timeline_temperature": 0.3,
    "scoring_temperature": 0.1,
}
```

### C. 去重参数模板

```ini
FLIP_MIRROR=off
SPEED_CHANGE=on
SPEED_FACTOR=1.04
SATURATION=on
SATURATION_VALUE=0.95
BRIGHTNESS=on
BRIGHTNESS_VALUE=0.01
SHARPEN=on
SHARPEN_AMOUNT=0.8
CROP_BLACKBAR=off
WATERMARK=off
```

### D. 视频号自动发布参考项目

| 项目 | 技术栈 | 说明 |
|------|--------|------|
| [social-auto-upload](https://github.com/loongtrip/social-auto-upload) | Playwright + Vue | 多平台发布 |
| [kay-video-upload](https://github.com/changyikang/kay-video-upload) | Playwright | 定时发布、封面设置 |

---

> GitHub 仓库：https://github.com/ben500500/clip-workflow
>
> 本文档随项目迭代持续更新。
