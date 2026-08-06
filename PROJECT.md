# 短剧切片工作流系统 — 项目文档

> 版本：v2.1 | 更新日期：2026-08-06
>
> 覆盖：切片工作流（含分布式切片） + 视频号自动发布 + IAA 数据看板 + Worker 节点管理
>
> 本文档已同步截至当前 HEAD（`e98e39a`）的全部功能与结构变更。

---

## 一、项目简介

短剧切片工作流系统（Clip Workflow）是一套面向短剧分发团队的端到端自动化平台。系统将传统的 Shell 脚本流水线封装为 Web 工作流，覆盖从正片上传到发布变现的全链路：

1. **AI 智能选点** — 基于 AutoClip（通义千问 ASR / 本地 faster-whisper + LLM）自动识别高光片段
2. **通用区间检测** — 检测任意需移除的内容段（片尾黑场 / 静止画面 / 水印等，不限于片尾）
3. **多平台去重切片** — 按视频号/抖音/快手分别应用去重 Profile
4. **分布式切片** — Go Slice Worker 节点从 Redis Stream 领取任务，支持远程节点/多节点并发/CPU 资源分配
5. **视频号自动发布** — Playwright RPA 浏览器自动化，含小程序挂载引导
6. **IAA 数据看板** — 打通「视频号内容 → 小程序短剧 → 广告收益」全链路漏斗

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
│  │项目管理 │ │选点工作台│ │区间检测 │ │切片任务 │ │成品预览 │ │发布管理 ││
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘│
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐          │
│  │Worker  │ │数据看板 │ │数据录入 │ │用户管理 │ │系统设置 │          │
│  │ 节点   │ └────────┘ └────────┘ └────────┘ └────────┘          │
│  └────────┘                                                       │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ REST API + WebSocket
┌──────────────────────────▼───────────────────────────────────────────┐
│                         FastAPI Backend                               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ │
│  │上传服务 │ │项目管理 │ │区间检测 │ │切片调度 │ │发布调度 │ │数据看板 │ │
│  │ (tus)  │ │ CRUD   │ │进度落库 │ │双引擎   │ │ (RPA)  │ │聚合计算 │ │
│  └───┬────┘ └────────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ │
│      └─────────────────────┴──────────┴──────────┴──────────┘      │
│                       Celery Worker Pool                             │
│  task_autoclip │ task_detect │ task_slice │ task_publish │ task_data │
└──────────┬───────────────────────────────┬───────────────────────────┘
           │                    ┌──────────▼───────────┐
           │                    │  Redis Stream        │
           │                    │  slice:priority/high │
           │                    └──────────┬───────────┘
           │                               │
           │                    ┌──────────▼───────────┐
           │                    │  Go Slice Worker 节点 │
           │                    │  (slice-worker-1/2/… │
           │                    │   远程节点/托盘模式)  │
           │                    └──────────┬───────────┘
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
| 反向代理 | Nginx 1.28 |
| AI 选点 | 通义千问 ASR (qwen3-asr-flash) + LLM (qwen-plus) |
| 自动发布 | Playwright + Chromium (CDP 协议) |
| 容器化 | Docker + Docker Compose |
| 视频处理 | FFmpeg（engines/ 脚本封装，切片支持 CPU 线程限制） |
| 分布式切片 | Go 1.21+ Slice Worker（Redis Stream 队列 + 心跳注册 + 系统托盘） |
| AI 选点 ASR | 阿里云 qwen3-asr-flash（默认）或本地 faster-whisper（`AUTOCLIP_ASR_METHOD=whisper`） |

---

## 四、项目结构

```
clip-workflow/
├── .env.example              # 环境变量配置模板
├── .gitignore
├── LICENSE
├── deploy.sh                 # 本地一键部署脚本
├── deploy_remote_worker.sh   # 远程 Slice Worker 节点一键部署脚本
├── docker-compose.yml        # 容器编排（15 个服务）
├── init.sql                  # 数据库初始化（扩展表，业务表由 ORM 创建）
├── nginx.conf                # Nginx 反向代理配置
│
├── autoclip/                 # AutoClip AI 选点服务
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py           # FastAPI 入口（ASR：阿里云/本地 whisper）
│       ├── celery_app.py     # Celery 实例
│       ├── config.py
│       ├── pipeline/         # 流水线：ASR→大纲→时间线→评分→标题
│       ├── prompt/           # LLM Prompt 模板
│       └── utils/
│
├── backend/                  # 后端主服务
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py           # FastAPI 入口（启动时预置默认配置/平台去重）
│       ├── config.py         # 配置管理（Pydantic Settings）
│       ├── database.py       # 异步数据库引擎
│       ├── api/              # API 路由层（12 个模块）
│       │   ├── auth.py       # 认证/用户/角色管理
│       │   ├── projects.py   # 项目/剧集 CRUD
│       │   ├── upload.py     # 文件上传（tus 分片）
│       │   ├── autoclip.py   # AI 选点
│       │   ├── intervals.py  # 区间检测（进度落库 slice_tasks）
│       │   ├── slice.py      # 切片执行（双引擎分发）
│       │   ├── preview.py    # 预览生成/批量下载
│       │   ├── publications.py # 发布记录
│       │   ├── publish.py    # 发布管理（v2）
│       │   ├── dashboard.py  # 数据看板（v2）
│       │   ├── config.py     # 系统配置/平台去重 Profile
│       │   └── workers.py    # Worker 节点管理（心跳/启停/CPU）
│       ├── models/
│       │   └── models.py     # 22 个 ORM 模型（含 WorkerNode）
│       ├── services/         # 业务逻辑层（10 个服务）
│       │   ├── upload_service.py
│       │   ├── autoclip_service.py
│       │   ├── interval_service.py
│       │   ├── slice_service.py
│       │   ├── minio_service.py
│       │   ├── redis_stream.py      # Redis Stream 切片队列/节点控制 key
│       │   ├── publish_service.py    # RPA 发布（v2）
│       │   ├── dashboard_service.py  # 看板聚合（v2）
│       │   ├── smart_import_service.py # 智能 Excel 导入（v2）
│       │   └── data_import_service.py # Excel 导入（v2）
│       ├── celery/
│       │   └── tasks.py      # 6 个异步任务（含确认发布）
│       └── utils/
│           └── helpers.py
│
├── frontend/                 # 前端应用
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── App.tsx           # 路由定义（22 个页面）
│       ├── main.tsx          # 入口
│       ├── api/              # API 客户端（11 个模块）
│       ├── components/       # 通用组件（3 个）
│       ├── pages/            # 页面组件（22 个）
│       ├── types/            # TypeScript 类型定义
│       └── utils/            # 工具函数
│
├── slice-worker/             # 分布式切片 Worker（Go）
│   ├── Dockerfile
│   ├── go.mod / go.sum
│   ├── worker.go             # 主逻辑（领取任务/心跳/回调）
│   ├── redis_client.go       # Redis Stream 消费/节点控制 key
│   ├── task_executor.go      # 任务执行（调 engines/slice.py）
│   ├── file_transfer.go      # 文件下载/上传 MinIO
│   ├── callback.go           # 后端回调
│   ├── config.go             # 配置（node-id/cpu-percent 等）
│   ├── tray.go / tray_common.go / tray_windows.go / tray_darwin.go / tray_other.go
│   ├── exec_unix.go / exec_windows.go  # 平台化进程管理
│   ├── tui.go                # 终端 UI/日志模式
│   ├── worker.json           # 节点配置模板
│   ├── windows/              # Windows 一键部署/卸载脚本
│   ├── macos/                # macOS 编译/登录项脚本
│   ├── icons/                # 托盘图标
│   └── README-tray.md        # 托盘使用说明
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
├── engines/                  # 视频处理引擎脚本
│   ├── detect_intervals.py   # 区间检测（credits/static/watermark）
│   ├── slice.py              # 切片引擎（支持 --cpu-percent）
│   ├── preview.py            # 帧图/视频预览
│   └── README.md
│
├── docs/                     # 文档
│   ├── README.md
│   ├── remote-worker-部署说明.md  # 远程 Slice Worker 部署
│   └── deployment-guide.html     # 部署操作指南
│
└── scripts/                  # 运维脚本
    ├── server-setup.sh       # 阿里云一键部署
    ├── start.sh / stop.sh / restart.sh
    ├── status.sh / logs.sh
    └── init.sh
```

---

## 五、数据库设计

### 5.1 表清单

> 说明：`init.sql` 只负责预置用户/认证/协作/素材等扩展表，**业务表**（`projects` / `episodes` / `slice_tasks` / `publish_tasks` / `video_metrics` 等）由后端 SQLAlchemy `Base.metadata.create_all` 在启动时自动创建，避免两套 schema 互相冲突。

#### 扩展表（init.sql 预置）

| 表名 | 说明 |
|------|------|
| `users` | 用户账号（角色：admin/operator/publisher/material） |
| `user_sessions` | 登录会话（JWT refresh token） |
| `user_oauth_accounts` | OAuth 第三方账号绑定 |
| `project_members` | 项目协作成员 |
| `workflow_templates` | 工作流模板 |
| `media_assets` | 素材文件（视频/音频/图片） |
| `media_tags` / `media_asset_tags` | 素材标签 |
| `clip_tasks` | 剪辑任务 |
| `autoclip_configs` | AutoClip 配置 |
| `autoclip_history` | AutoClip 执行历史 |
| `celery_tasks` / `celery_periodic_tasks` | Celery 任务表 |
| `notifications` | 通知 |
| `system_configs` | 系统配置（扩展） |

#### ORM 模型（SQLAlchemy，22 个）

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `User` | `users` | 用户（password_hash、角色 admin/operator/publisher/material） |
| `Project` | `projects` | 项目 |
| `Episode` | `episodes` | 剧集（状态机：uploaded→clips_detected→intervals_detected→slicing→completed） |
| `AutoClipProject` | `autoclip_projects` | AutoClip 项目关联（含 error_message） |
| `ClipCandidate` | `clip_candidates` | AI 选点候选片段 |
| `DetectedInterval` | `detected_intervals` | 检测到的待挖洞区间 |
| `SliceTask` | `slice_tasks` | 切片任务（含 node_id，可复用为 detect_* 区间检测进度记录） |
| `SliceOutput` | `slice_outputs` | 切片输出文件 |
| `Publication` | `publications` | 发布记录 |
| `PlatformProfile` | `platform_profiles` | 平台去重配置 |
| `SystemConfig` | `system_config` | 系统配置 |
| `PublishTask` | `publish_tasks` | 发布任务（含平台、状态、截图审核） |
| `PublishProfile` | `publish_profiles` | 发布配置（Chrome 端口、模板、频率限制） |
| `VideoMetric` | `video_metrics` | 视频内容数据（播放/互动/跳转/归因） |
| `MiniProgramMetric` | `mini_program_metrics` | 小程序数据（UV/播放/完播率） |
| `AdMetric` | `ad_metrics` | 广告数据（曝光/点击/eCPM/收益） |
| `DramaMetric` | `drama_metrics` | 分剧维度数据 |
| `FunnelSnapshot` | `funnel_snapshots` | 漏斗快照（每日计算） |
| `EcosystemMetric` | `ecosystem_metrics` | 生态数据（公众号/企微） |
| `ImportTemplate` | `import_templates` | 智能导入模板 |
| `ImportHistory` | `import_history` | 智能导入历史 |
| `WorkerNode` | `worker_nodes` | Worker 节点注册（node_id/hostname/ip/os/arch/max_concurrent/enabled/cpu_percent/status 等） |

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
    import_templates / import_history (独立)

workers:
    worker_nodes（独立，由 Go Worker 心跳注册，与 Redis 节点控制 key 同步）
```

---

## 六、API 接口

### 6.1 认证与用户（`/api/auth`）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth/login` | 登录 |
| `GET` | `/api/auth/me` | 当前用户 |
| `POST` | `/api/auth/register` | 注册 |
| `GET` | `/api/auth/users` | 用户列表 |
| `PUT` | `/api/auth/users/{id}/role` | 修改用户角色 |

### 6.2 工作流 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST` | `/api/projects` | 项目列表/创建 |
| `GET/PUT/DELETE` | `/api/projects/{id}` | 项目详情/更新/删除 |
| `GET` | `/api/projects/stats` | 项目统计 |
| `POST` | `/api/projects/{id}/episodes` | 创建剧集 |
| `GET` | `/api/projects/{id}/episodes` | 剧集列表 |
| `GET` | `/api/episodes/{id}` | 剧集详情 |
| `GET` | `/api/episodes/{id}/video-url` | 剧集视频地址（presigned） |
| `DELETE` | `/api/episodes/{id}` | 删除剧集 |
| `POST` | `/api/upload/resume` | 初始化分片上传 |
| `PATCH` | `/api/upload/{id}` | 上传分片 |
| `GET` | `/api/upload/{id}/progress` | 上传进度 |
| `POST` | `/api/upload/complete` | 完成上传 |
| `POST` | `/api/upload` | 单文件上传 |
| `DELETE` | `/api/upload/{id}` | 取消上传 |

### 6.3 选点与区间检测 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/episodes/{id}/autoclip/run` | 启动 AI 选点 |
| `GET` | `/api/episodes/{id}/autoclip/progress` | 选点进度（含 error_message） |
| `GET` | `/api/episodes/{id}/autoclip/clips` | 候选片段列表 |
| `PUT` | `/api/clips/{clip_id}` | 审核/调整片段（通过/拒绝/改时间） |
| `POST` | `/api/episodes/{id}/autoclip/regenerate` | 重新选点 |
| `POST` | `/api/episodes/{id}/intervals/detect` | 启动区间检测 |
| `GET` | `/api/episodes/{id}/intervals/progress` | 检测进度（含 error_message） |
| `GET` | `/api/episodes/{id}/intervals` | 区间列表 |
| `POST` | `/api/intervals` | 手动添加区间 |
| `PUT` | `/api/intervals/{id}` | 更新区间 |
| `DELETE` | `/api/intervals/{id}` | 删除区间 |
| `PUT` | `/api/intervals/{id}/toggle` | 启用/停用区间 |

### 6.4 切片 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/episodes/{id}/slice/run` | 执行切片（auto_accept_all 免审核一键切片） |
| `GET` | `/api/episodes/{id}/slice/tasks` | 切片任务列表（排除 detect_* 记录） |
| `GET` | `/api/slice-tasks/{id}` | 任务详情 |
| `GET` | `/api/slice-tasks/{id}/outputs` | 任务输出 |
| `GET` | `/api/slice-tasks/{id}/upload-url` | Worker 上传预签名 URL |
| `POST` | `/api/slice-tasks/{id}/callback` | Worker 回调（完成/失败） |
| `POST` | `/api/slice-tasks/{id}/progress` | Worker 进度上报 |
| `POST` | `/api/slice-tasks/{id}/retry` | 重试切片 |
| `POST` | `/api/slice-tasks/{id}/cancel` | 取消切片 |
| `DELETE` | `/api/slice-tasks/{id}` | 删除切片（级联删 MinIO 与 DB） |

### 6.5 预览与下载 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/outputs/{id}/preview/frames` | 帧图预览 |
| `GET` | `/api/outputs/{id}/preview/video` | 视频预览 |
| `GET` | `/api/outputs/{id}/download` | 单文件下载 |
| `POST` | `/api/outputs/batch-download` | 多选批量下载（返回 presigned 直链列表，前端逐个下载） |

### 6.6 Worker 节点管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/workers/heartbeat` | 节点心跳注册 |
| `GET` | `/api/workers` | 节点列表 |
| `GET` | `/api/workers/{node_id}` | 节点详情 |
| `POST` | `/api/workers/{node_id}/enable` | 启用节点 |
| `POST` | `/api/workers/{node_id}/disable` | 停用节点（不再领取新任务） |
| `POST` | `/api/workers/{node_id}/cpu-percent` | 调整节点 CPU 分配比例 |
| `POST` | `/api/workers/sync-redis` | 从 Redis 同步节点状态 |

### 6.7 发布管理 API（v2）

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

### 6.8 系统配置 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/config` | 全部配置（默认+已保存合并） |
| `PUT` | `/api/config` | 更新配置 |
| `GET` | `/api/config/platform-profiles` | 平台去重 Profile 列表 |
| `POST` | `/api/config/platform-profiles` | 创建 Profile |
| `PUT` | `/api/config/platform-profiles/{id}` | 更新 Profile |

### 6.9 数据看板 API（v2）

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
| `GET` | `/api/dashboard/videos/cross-analysis` | 跨维度交叉分析 |
| `GET` | `/api/dashboard/mini-program` | 小程序指标 |
| `GET` | `/api/dashboard/ads` | 广告指标 |
| `GET` | `/api/dashboard/dramas` | 分剧排行 |
| `GET` | `/api/dashboard/dramas/{id}` | 分剧详情 |
| `GET` | `/api/dashboard/funnel` | 漏斗数据 |
| `GET` | `/api/dashboard/funnel/trend` | 漏斗趋势 |
| `GET` | `/api/dashboard/funnel/compare` | 漏斗对比 |
| `GET` | `/api/dashboard/ecosystem` | 生态数据 |
| `POST` | `/api/dashboard/metrics/video` | Excel 导入视频数据 |
| `POST` | `/api/dashboard/metrics/mini-program` | Excel 导入小程序数据 |
| `POST` | `/api/dashboard/metrics/ads` | Excel 导入广告数据 |
| `GET` | `/api/dashboard/metrics/template` | 下载导入模板 |
| `GET/PUT` | `/api/dashboard/config` | 看板配置 |
| `POST` | `/api/dashboard/import/upload` | 智能导入上传 |
| `POST` | `/api/dashboard/import/preview` | 智能导入预览 |
| `POST` | `/api/dashboard/import/confirm` | 智能导入确认 |
| `GET` | `/api/dashboard/import/templates` | 智能导入模板列表 |
| `POST` | `/api/dashboard/import/templates/custom` | 保存自定义导入模板 |
| `GET` | `/api/dashboard/import/history` | 导入历史 |

### 6.10 WebSocket

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
| `/projects/:id` | 项目详情 | 剧集列表、上传与剧集列表上下排布 |
| `/episodes/:id` | 剧集详情 | 素材信息、选点/区间检测/切片操作入口（含错误提示） |
| `/episodes/:id/clips` | 片段审核 | AI 选点结果审核、视频预览、一键通过/拒绝、一键切片 |
| `/episodes/:id/intervals` | 区间检测 | 挖洞区间审核（启用/停用/删除/手动添加） |
| `/episodes/:id/slice` | 切片任务 | 切片执行与进度（显示执行节点） |
| `/episodes/:id/preview` | 输出预览 | 帧图/视频预览、多选批量下载、任务下拉 |
| `/publish` | 发布管理 | 发布任务列表、配置管理 |
| `/workers` | Worker 节点 | 节点状态/启停/CPU 分配/运行进度 |
| `/analytics/overview` | 数据总览 | 收益卡片、趋势图、漏斗、TOP5 |
| `/analytics/content` | 内容分析 | 视频数据表、排行、多维筛选 |
| `/analytics/monetization` | 短剧变现 | 分剧/小程序/广告指标 |
| `/analytics/funnel` | 转化漏斗 | 漏斗分析与对比 |
| `/analytics/ecosystem` | 生态联动 | 公众号/企微数据 |
| `/analytics/import` | 数据录入 | Excel 上传、智能导入、模板下载 |
| `/analytics/settings` | 看板设置 | 看板全局配置 |
| `/profile` | 个人中心 | 个人信息 |
| `/user-management` | 用户管理 | 用户列表、角色管理 |
| `/settings` | 系统设置 | 全局参数配置、平台去重 Profile、配置说明 |

### 7.2 导航菜单

```
仪表盘
项目管理
发布管理
Worker 节点
数据看板
  ├── 总览
  ├── 内容分析
  ├── 短剧变现
  ├── 转化漏斗
  ├── 生态联动
  ├── 数据录入
  └── 看板设置
个人中心
用户管理
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

### 8.1 Celery 任务清单（后端 worker）

| 任务名 | 队列 | 说明 |
|--------|------|------|
| `autoclip_task` | `video_processing` | 执行 AutoClip 流水线，轮询进度，获取片段结果 |
| `detect_task` | `video_processing` | 通用区间检测（进度落库 slice_tasks，支持 credits/static） |
| `slice_task` | `video_processing` | Celery 兜底切片（Worker 引擎不可用时回退） |
| `task_publish_video` | `publish` | RPA 视频发布（截图审核 → 确认 → 发布） |
| `confirm_publish_worker` | `publish` | 确认发布任务 |
| `task_collect_metrics` | `metrics` | 每日 00:30 定期指标采集与漏斗快照计算 |

### 8.2 RPA 发布任务

| 任务名 | 平台 | 说明 |
|--------|------|------|
| `publish_wechat_channels` | 微信视频号 | Playwright 连接 Chrome CDP，自动上传/填写/截图/发布 |
| `publish_douyin` | 抖音 | 同上，页面结构不同 |
| `publish_kuaishou` | 快手 | 同上 |
| `check_cookie_status` | 全平台 | 定期检查登录态是否有效 |

### 8.3 分布式切片调度（Go Slice Worker）

- 后端 `slice.py` 按 `SLICE_ENGINE` 选择引擎：`worker`（默认，Redis Stream 分发到 Go Worker）或 `celery`（回退）。
- Go Worker 从 Redis Stream（`slice:priority` / `slice:high`）领取任务，执行 `engines/slice.py` 后回传进度/结果到后端回调接口。
- 节点心跳注册 `worker_nodes`，支持多节点并发、启停开关、CPU 分配（`slice:node-enabled:{id}` / `slice:node-cpu-percent:{id}`）。
- 全局并发控制：`max_concurrent_tasks` 实际闸门，超限返回 429。

---

## 九、Docker 服务编排

### 9.1 服务列表（15 个）

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `postgres` | postgres:15-alpine | 15432(映射) | 数据库（内部 5432） |
| `redis` | redis:7-alpine | 16379(映射) | 缓存 + 消息队列（内部 6379） |
| `minio` | minio/minio:latest | 9000/9001 | 对象存储 |
| `minio_init` | minio/mc:latest | — | Bucket 初始化（一次性） |
| `autoclip` | 构建自 ./autoclip | 8000 | AI 选点 API |
| `backend` | 构建自 ./backend | 8001(映射) | 主 API 服务（内部 8080） |
| `worker` | 同 backend | — | Celery 视频处理 Worker |
| `beat` | 同 backend | — | Celery 定时调度 |
| `rpa_worker` | 构建自 ./rpa | 9222 | RPA 发布 Worker（可选） |
| `slice-worker` | 构建自 ./slice-worker | — | Go 分布式切片节点 1 |
| `slice-worker-2` | 同 slice-worker | — | Go 分布式切片节点 2（同机扩容） |
| `frontend` | 构建自 ./frontend | 3000(映射) | 前端静态文件（内部 80） |
| `nginx` | nginx:1.28-alpine | 80 | 反向代理入口 |

> 注：`autoclip_worker` 独立实例已移除（由 autoclip 服务内嵌 worker 模式替代）。

### 9.2 数据卷

| 卷名 | 用途 |
|------|------|
| `postgres_data` | 数据库持久化 |
| `redis_data` | Redis AOF 持久化 |
| `minio_data` | 对象存储数据 |
| `media_data` | 媒体文件缓存 |
| `chrome_profiles` | Chrome 浏览器 Profile（RPA 用） |
| `slice_worker_temp` | 切片 Worker 临时目录 |
| `./hf-cache` | faster-whisper 模型缓存（持久化） |
| `./whisper-model` | 本地平铺模型目录（只读挂载） |

### 9.3 Nginx 路由规则

| 路径 | 代理目标 | 说明 |
|------|---------|------|
| `/` | `frontend:80` | 前端静态文件（静态资源 30 天缓存） |
| `/api/` | `backend:8080` | 后端 API |
| `/autoclip/` | `autoclip:8000` | AutoClip API（rewrite 去前缀） |
| `/ws/` | `backend:8080` | WebSocket（长连接 86400s） |
| `/minio/` | `minio:9000` | MinIO 代理（500M 上传限制） |
| `/health` | 200 OK | 健康检查 |

> Nginx 使用 Docker DNS 动态解析 upstream（`resolve`），容器重建后无需重启 nginx。

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
| 数据库 | `POSTGRES_PASSWORD`、`DATABASE_URL` |
| Redis | `REDIS_PASSWORD`、`REDIS_URL`、`CELERY_BROKER_URL` |
| MinIO | `MINIO_ROOT_PASSWORD`、`MINIO_EXTERNAL_ENDPOINT`（浏览器可访问地址，修复预览/下载） |
| AutoClip | `DASHSCOPE_API_KEY`（通义千问 API Key）、`AUTOCLIP_ASR_METHOD`（aliyun_speech/whisper）、`WHISPER_MODEL` |
| 分布式切片 | `SLICE_ENGINE`（worker/celery）、`WORKER_CALLBACK_BASE_URL`、`CPU_PERCENT`（默认 50） |
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

# 查看切片节点日志
docker compose logs -f slice-worker slice-worker-2
```

### 11.6 分布式切片节点部署

**同机扩容**（docker-compose 已内置 `slice-worker` + `slice-worker-2`）：

```bash
docker compose up -d slice-worker slice-worker-2
```

**远程物理机/Windows/macOS 节点**：

- Linux 远程节点：`bash deploy_remote_worker.sh`（详见 `docs/remote-worker-部署说明.md`）
- Windows：拷贝 `slice-worker/` 目录，双击 `windows/deploy_windows.bat`（自动编译 + 托盘模式 + 开机自启）
- macOS：`./slice-worker/macos/build_mac.sh --run`（菜单栏图标）

前置条件：服务器需开放 Redis(6379)/后端回调(80)/MinIO(9000) 端口，且 `.env` 中 `MINIO_EXTERNAL_ENDPOINT` 指向服务器 IP。

---

## 十二、开发分期

### 一期 MVP — 已完成

- 项目脚手架（FastAPI + React + Docker Compose）
- 分片上传 + MinIO 存储
- 素材管理 CRUD
- AutoClip 集成（API 调用 + 配置项暴露）
- 通用区间检测
- 切片执行（多模式：fast/dedupe/scrub）
- 帧图预览 + 视频预览
- 数据看板 MVP（总览 + 内容分析 + 数据录入）

### 二期 — 已完成

- Playwright RPA Worker（视频号/抖音/快手）
- 视频号自动发布 + 截图确认
- 短剧变现页（小程序/广告指标 + 分剧排行）
- 转化漏斗完整版（含对比）
- 数据看板 v3（智能导入 + 自定义模板 + 生态联动）
- 视频标签系统 + 多维交叉分析
- 权限体系（admin/operator/publisher/material 角色）
- 用户管理 / 个人中心
- **分布式切片（Go Slice Worker + Redis Stream + 远程节点 + 托盘）**
- **Worker 节点管理页 + CPU 资源分配 + 免审核一键切片**
- **区间检测进度落库修复 + 静止画面检测修复**
- **系统设置配置合并修复 + 平台去重默认配置**
- **错误提示（感叹号 + Tooltip 完整错误）**
- **成片预览多选批量下载 + 切片并发控制**

### 三期（按需）

- 小程序 API 自动拉取
- GPU 加速编码
- 多平台发布 API 对接
- 目标管理

---

## 十三、风险与注意事项

### 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| AutoClip API 不稳定 | 选点失败 | 本地 whisper ASR 兜底 + 手动选点 fallback |
| FFmpeg 任务 OOM | 服务崩溃 | Worker concurrency=1 + CPU 线程限制 |
| Playwright 页面改版 | 自动发布失效 | 监控 + 告警 + 快速修复 |
| Cookie 过期 | 发布中断 | 定期检测 + 提示扫码 |
| 大文件上传中断 | 体验差 | tus 断点续传 |
| Redis/MinIO 端口对外 | 安全风险 | 确认部署环境网络可信，按内网使用 |
| 切片任务无限堆积 | 资源抢占 | 全局并发闸门（max_concurrent_tasks，超限 429） |

### 业务风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 视频号检测 RPA 行为 | 账号受限 | 随机延迟 + 人工确认 + 限量（默认 20 条/天） |
| 去重参数被识别 | 切片被限流 | 多平台 Profile 调优 |
| 收益归因不准 | 决策偏差 | 渠道参数归因 + 间接归因双轨 |
| 数据录入滞后 | 看板不准 | 提醒机制 + 未来 API 自动化 |

---

## 十四、附录

### A. 引擎脚本清单

| 文件 | 用途 | 部署位置 |
|------|------|---------|
| `detect_intervals.py` | 区间检测（credits 黑场 / static 静止画面 / watermark 降级） | `engines/` |
| `slice.py` | 切片引擎（fast/dedupe/scrub + `--cpu-percent` 线程限制） | `engines/` |
| `preview.py` | 帧图/视频预览 | `engines/` |
| `README.md` | 引擎脚本规范说明 | `engines/` |

### B. AutoClip 配置参数

```python
AUTOCLIP_CONFIG = {
    "llm_provider": "dashscope",
    "llm_model": "qwen-plus",
    "asr_model": "qwen3-asr-flash",       # 或本地 faster-whisper（AUTOCLIP_ASR_METHOD=whisper）
    "asr_segment_seconds": 270,
    "min_score_threshold": 60,
    "max_clips": 30,                      # 可选：自定义切片数量
    "min_duration": 30,
    "max_duration": 180,
    "chunk_size_minutes": 30,
    "timeline_temperature": 0.3,
    "scoring_temperature": 0.1,
    "start_time": None,                   # 可选：选点时间范围（秒）
    "end_time": None,
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

### E. 近期变更日志（v2.0 → v2.1）

| 日期 | 变更 |
|------|------|
| 2026-08-06 | 分布式切片方案（Go Worker + Redis Stream + 远程节点/托盘/CPU 分配） |
| 2026-08-06 | Worker 节点管理页、Header 节点状态图标、启停/CPU 调整 |
| 2026-08-06 | 免审核一键切片、成片预览多选批量下载、切片并发闸门 |
| 2026-08-06 | 区间检测进度落库修复（进度条消失）、静止画面检测正则修复 |
| 2026-08-06 | 成品预览任务下拉修复（NULL mode 过滤）、节点状态图标轮询、弹窗底色 |
| 2026-08-06 | 系统设置配置合并修复 + 平台去重默认配置预置 |
| 2026-08-06 | 错误提示组件（感叹号 + Tooltip 完整错误） |
| 2026-08-06 | 数据看板 v3（智能导入/自定义模板/生态联动/漏斗对比） |
| 2026-08-06 | 权限体系 + 用户管理 + 个人中心 |
| 2026-08-06 | AutoClip 支持 max_clips / start_time / end_time、本地 whisper ASR |

---

> 仓库地址：https://cnb.cool/ben500500/clip-workflow
>
> 本文档随项目迭代持续更新。
