# 短剧切片工作流系统 — 项目文档

> 版本：v3.0 | 更新日期：2026-08-06
>
> 覆盖：切片工作流 + 视频号自动发布 + IAA 数据看板 + 分布式切片 + 智能数据导入

---

## 一、项目简介

短剧切片工作流系统（Clip Workflow）是一套面向短剧分发团队的端到端自动化平台。系统将传统的 Shell 脚本流水线封装为 Web 工作流，覆盖从正片上传到发布变现的全链路：

1. **AI 智能选点** — 基于 AutoClip（通义千问 ASR + LLM）自动识别高光片段
2. **通用区间挖洞** — 检测任意需移除的内容段（不限于片尾）
3. **多平台去重切片** — 按视频号/抖音/快手分别应用去重 Profile
4. **视频号自动发布** — Playwright RPA 浏览器自动化，含小程序挂载引导
5. **IAA 数据看板** — 打通「视频号内容 → 小程序短剧 → 广告收益」全链路漏斗
6. **分布式切片执行** — Go Worker + Redis Stream 任务分发，支持多节点水平扩展
7. **智能数据导入** — 自动识别多平台数据格式，支持指纹匹配、手动映射、标准模板三种模式

### 核心原则

- **最小侵入**：现有 Shell 脚本原样保留，后端仅做调度层
- **配置外置**：所有参数暴露到前端界面，无需改代码
- **数据驱动**：收益归因到单条视频，全链路漏斗可诊断
- **弹性扩展**：切片任务分布式执行，Worker 节点按需增减

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                         React Frontend                               │
│  (Vite + React 18 + Ant Design 5 + ECharts + Zustand)               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐│
│  │素材管理 │ │选点工作台│ │区间检测 │ │任务监控 │ │成品库   │ │发布管理 ││
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘│
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                       │
│  │数据看板 │ │数据录入 │ │切片监控 │ │系统设置 │                       │
│  └────────┘ └────────┘ └────────┘ └────────┘                       │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ REST API + WebSocket
┌──────────────────────────▼───────────────────────────────────────────┐
│                         FastAPI Backend                               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐            │
│  │上传服务 │ │项目管理 │ │切片引擎 │ │发布调度 │ │数据看板 │            │
│  │ (tus)  │ │ CRUD   │ │ 调度器  │ │ (RPA)  │ │聚合计算 │            │
│  └───┬────┘ └────────┘ └───┬────┘ └───┬────┘ └───┬────┘            │
│  ┌────────┐ ┌──────────────────────────────────────────────────┐    │
│  │认证授权│ │        智能导入服务（指纹匹配/映射/模板）          │    │
│  │ (JWT)  │ │                                                    │    │
│  └────────┘ └──────────────────────────────────────────────────┘    │
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
    │ (队列+缓存+  │
    │  Stream分发) │
    └──────┬──────┘
           │
    ┌──────▼──────────────────────────────────────────────────────────┐
    │                  分布式切片 Worker 层                              │
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
    │  │ Worker-1  │  │ Worker-2  │  │ Worker-3  │  │ Worker-N  │       │
    │  │ (Go/Mac) │  │ (Go/Linux)│  │ (Go/GPU) │  │ (Go/...) │       │
    │  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
    │         ▲              ▲              ▲              ▲           │
    │         └──────────────┴──── Redis Stream ──────────┘           │
    └─────────────────────────────────────────────────────────────────┘
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
| 数据库 | PostgreSQL 15 + Alembic（数据库迁移） |
| 缓存/队列 | Redis 7（消息队列 + Stream 任务分发） |
| 对象存储 | MinIO |
| 反向代理 | Nginx 1.25 |
| AI 选点 | 通义千问 ASR (qwen3-asr-flash) + LLM (qwen-plus) |
| 自动发布 | Playwright + Chromium (CDP 协议) |
| 分布式切片 | Go 1.22 + bubbletea（TUI 界面） |
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
├── docker-compose.yml        # 容器编排（13 个服务）
├── init.sql                  # 数据库初始化（32 张表）
├── nginx.conf                # Nginx 反向代理配置
│
├── alembic/                  # 数据库迁移（Alembic）
│   ├── alembic.ini
│   ├── env.py
│   └── versions/             # 迁移脚本
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
│       ├── api/              # API 路由层（14 个模块）
│       │   ├── projects.py   # 项目 CRUD
│       │   ├── upload.py     # 文件上传（tus 分片）
│       │   ├── autoclip.py   # AI 选点
│       │   ├── intervals.py  # 区间检测
│       │   ├── slice.py      # 切片执行
│       │   ├── preview.py    # 预览生成
│       │   ├── publications.py # 发布记录
│       │   ├── publish.py    # 发布管理（v2）
│       │   ├── dashboard.py  # 数据看板（v2）
│       │   ├── import_.py    # 智能数据导入（v3）
│       │   ├── config.py     # 系统配置
│       │   ├── auth.py       # 认证/用户/会话（v3）
│       │   ├── workers.py    # Worker 节点管理（v3）
│       │   ├── monitor.py    # 监控告警（v3 三期）
│       │   └── maintenance.py# 运维优化：归档/清理/生命周期（三期）
│       ├── models/
│       │   └── models.py     # 27 个 ORM 模型
│       ├── services/         # 业务逻辑层（13 个服务）
│       │   ├── upload_service.py
│       │   ├── autoclip_service.py
│       │   ├── interval_service.py
│       │   ├── slice_service.py
│       │   ├── minio_service.py
│       │   ├── publish_service.py    # RPA 发布（v2）
│       │   ├── dashboard_service.py  # 看板聚合（v2）
│       │   ├── data_import_service.py # 智能导入（v3）
│       │   ├── smart_import_service.py # 智能导入增强（v3）
│       │   ├── redis_stream.py # Redis Stream 分发（v3）
│       │   ├── auth_service.py       # 认证授权（v3）
│       │   ├── monitor_service.py    # 监控告警（三期）
│       │   └── maintenance_service.py# 运维优化（三期）
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
│       ├── App.tsx           # 路由定义（15 个页面）
│       ├── main.tsx          # 入口
│       ├── api/              # API 客户端（10 个模块）
│       ├── components/       # 通用组件（5 个）
│       ├── pages/            # 页面组件（14 个）
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
├── slice-worker/             # 分布式切片 Worker（v3）
│   ├── main.go               # Go 单文件 Worker 入口
│   ├── go.mod
│   ├── start.sh              # 一键启动脚本
│   └── README.md
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

### 5.1 表清单（32+ 张表）

#### 用户与认证

| 表名 | 说明 |
|------|------|
| `users` | 用户账号（角色：admin/operator/publisher/material） |
| `user_sessions` | 登录会话（JWT refresh token + 黑名单） |
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

#### V3 分布式切片

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `WorkerNode` | `worker_nodes` | Worker 节点注册（能力标签、心跳、状态、启停/CPU） |

#### V3 智能导入

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `ImportTemplate` | `import_templates` | 导入模板（标准模板 + 自定义映射模板） |
| `ImportHistory` | `import_histories` | 导入历史记录（来源、状态、行数、操作人） |

#### V3 安全认证

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `User` | `users` | 用户（角色 admin/operator/publisher/material） |
| `UserSession` | `user_sessions` | 登录会话（refresh_token 哈希、黑名单） |

#### V3 审计日志

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `AuditLog` | `audit_logs` | 审计日志（操作人、操作时间、操作类型、目标对象、变更前后值） |

#### 三期监控告警

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `AlertRule` | `alert_rules` | 告警规则（指标、比较符、阈值、级别、启停） |
| `AlertEvent` | `alert_events` | 告警事件（触发时间、级别、内容、通知状态） |

#### V4/V6/V7 短片制作（去水印 + 提示词生成 + 发布素材）

| 模型类 | 表名 | 说明 |
|--------|------|------|
| `WatermarkTask` | `watermark_tasks` | 去水印任务（批量提交，多视频，任务级关联来源提示词记录） |
| `WatermarkVideo` | `watermark_videos` | 去水印任务下的单条视频（含 prompt_record_id 来源关联） |
| `ShortdramaPrompt` | `shortdrama_prompts` | Seedance 提示词生成历史（文案→七段模板，可关联成片视频） |
| `PublishMaterial` | `publish_materials` | 短剧发布素材生成历史（剧情梗概→短标题/三款配文/成套标签/三条神评） |

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

distributed slice:
    slice_worker_nodes (独立，心跳注册)

import:
    import_templates (独立，标准+自定义)
    import_histories ──N:1──> users

audit:
    audit_logs ──N:1──> users
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

### 6.2 选点与区间检测 API
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

### 6.3 切片 API
| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/episodes/{id}/slice/run` | 执行切片（auto_accept_all 免审核一键切片；watermark_enabled/watermark_text 等参数支持动态文字水印） |
| `GET` | `/api/episodes/{id}/slice/tasks` | 切片任务列表（排除 detect_* 记录） |
| `GET` | `/api/slice-tasks/{id}` | 任务详情 |
| `GET` | `/api/slice-tasks/{id}/outputs` | 任务输出 |
| `GET` | `/api/slice-tasks/{id}/upload-url` | Worker 上传预签名 URL |
| `POST` | `/api/slice-tasks/{id}/callback` | Worker 回调（完成/失败） |
| `POST` | `/api/slice-tasks/{id}/progress` | Worker 进度上报 |
| `POST` | `/api/slice-tasks/{id}/retry` | 重试切片 |
| `POST` | `/api/slice-tasks/{id}/cancel` | 取消切片 |
| `DELETE` | `/api/slice-tasks/{id}` | 删除切片（级联删 MinIO 与 DB） |

### 6.4 预览与下载 API
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/outputs/{id}/preview/frames` | 帧图预览 |
| `GET` | `/api/outputs/{id}/preview/video` | 视频预览 |
| `GET` | `/api/outputs/{id}/download` | 单文件下载 |
| `POST` | `/api/outputs/batch-download` | 多选批量下载（返回 presigned 直链列表，前端逐个下载） |

### 6.5 Worker 节点管理 API
| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/workers/heartbeat` | 节点心跳注册 |
| `GET` | `/api/workers` | 节点列表 |
| `GET` | `/api/workers/{node_id}` | 节点详情 |
| `POST` | `/api/workers/{node_id}/enable` | 启用节点 |
| `POST` | `/api/workers/{node_id}/disable` | 停用节点（不再领取新任务） |
| `POST` | `/api/workers/{node_id}/cpu-percent` | 调整节点 CPU 分配比例 |
| `POST` | `/api/workers/sync-redis` | 从 Redis 同步节点状态 |

### 6.5.1 认证与用户 API（v3）
| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth/login` | 登录（返回 access_token + refresh_token Cookie） |
| `POST` | `/api/auth/refresh` | 无感刷新 access_token（双 Token） |
| `POST` | `/api/auth/logout` | 登出（吊销会话 Token 黑名单） |
| `GET` | `/api/auth/me` | 当前用户信息 |
| `POST` | `/api/auth/register` | 注册用户（管理员） |
| `GET` | `/api/auth/users` | 用户列表（管理员） |
| `PUT` | `/api/auth/users/{id}/role` | 修改用户角色 |
| `PUT` | `/api/auth/users/{id}/toggle` | 启用/停用用户 |
| `PUT` | `/api/auth/profile` | 修改个人资料/密码 |

### 6.5.2 监控告警 API（三期）
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/monitor/health` | 健康检查（数据库/Redis/MinIO/磁盘） |
| `GET` | `/api/monitor/metrics` | 采集各监控指标当前值 |
| `GET` | `/api/monitor/alerts/rules` | 告警规则列表 |
| `GET` | `/api/monitor/alerts/rules/meta` | 告警指标说明 |
| `POST` | `/api/monitor/alerts/rules` | 创建告警规则 |
| `PUT` | `/api/monitor/alerts/rules/{id}` | 更新告警规则 |
| `DELETE` | `/api/monitor/alerts/rules/{id}` | 删除告警规则 |
| `GET` | `/api/monitor/alerts/events` | 告警事件列表 |
| `POST` | `/api/monitor/alerts/check` | 手动触发一轮告警检查 |

### 6.5.3 运维优化 API（三期）
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/maintenance/status` | 运维配置状态 |
| `POST` | `/api/maintenance/archive` | 数据归档（>90 天看板数据） |
| `POST` | `/api/maintenance/cleanup-temp` | 清理临时文件 |
| `POST` | `/api/maintenance/minio-lifecycle` | 设置 MinIO 生命周期策略 |

### 6.6 发布管理 API（v2）


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

### 6.7 数据看板 API（v2）

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
| `GET/PUT` | `/api/dashboard/config` | 看板配置 |

### 6.8 智能数据导入 API（v3）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/dashboard/import/upload` | 智能导入（自动识别平台格式） |
| `POST` | `/api/dashboard/import/preview` | 预览文件内容（手动映射用） |
| `POST` | `/api/dashboard/import/confirm` | 确认导入（带映射关系） |
| `GET` | `/api/dashboard/import/templates` | 获取标准模板列表 |
| `POST` | `/api/dashboard/import/templates/custom` | 保存自定义模板 |
| `GET` | `/api/dashboard/import/history` | 导入历史记录 |

### 6.8.1 短片制作 API（v6，Seedance 提示词生成）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/shortdrama/prompt/generate` | 根据文案一次生成提示词三版本（长提示词/短提示词固定模板 + AI提示词，复用 AutoClip 模型，支持 10s/15s/自定义时长） |
| `GET` | `/api/shortdrama/prompt/templates` | 获取长/短提示词模板（用户可编辑，未编辑时返回内置默认） |
| `PUT` | `/api/shortdrama/prompt/templates` | 保存用户自定义长/短提示词模板（[视频文案] 占位符自动补齐） |
| `GET` | `/api/shortdrama/prompts` | 提示词生成历史列表（含成片视频签名地址） |
| `GET` | `/api/shortdrama/prompts/{id}` | 单条提示词记录详情 |
| `DELETE` | `/api/shortdrama/prompts/{id}` | 删除提示词记录（连同成片视频） |
| `POST` | `/api/shortdrama/prompts/{id}/video` | 为生成记录上传成片视频（Seedance 结果，存入 watermark-raw 桶） |
| `GET` | `/api/shortdrama/prompts/{id}/video` | 获取成片视频签名播放地址 |
| `DELETE` | `/api/shortdrama/prompts/{id}/video` | 删除成片视频（保留提示词记录） |
| `POST` | `/api/shortdrama/prompts/{id}/import-to-watermark` | 一键把成片视频导入去水印流程 |

### 6.8.2 短剧发布素材 API（v7）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/shortdrama/publish-material/generate` | 根据剧情梗概生成短剧发布素材（短标题→三款配文→成套标签→三条神评，复用 AutoClip 模型） |
| `GET` | `/api/shortdrama/publish-materials` | 发布素材生成历史列表 |
| `GET` | `/api/shortdrama/publish-materials/{id}` | 单条发布素材记录详情 |
| `DELETE` | `/api/shortdrama/publish-materials/{id}` | 删除发布素材记录 |

### 6.9 WebSocket

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
| `/episodes/:id/clips` | 片段审核 | AI 选点结果审核、视频预览、一键通过/拒绝 |
| `/episodes/:id/intervals` | 区间检测 | 挖洞区间审核（启用/停用/删除/手动添加） |
| `/episodes/:id/slice` | 切片任务 | 切片执行与进度（显示执行节点、自定义文字水印开关） |
| `/episodes/:id/preview` | 输出预览 | 视频预览（点击行区域直接展开）、多选批量下载、任务下拉 |
| `/publish` | 发布管理 | 发布任务列表、配置管理 |
| `/analytics/overview` | 数据总览 | 收益卡片、趋势图、漏斗、TOP5 |
| `/analytics/content` | 内容分析 | 视频数据表、排行、多维筛选 |
| `/analytics/import` | 数据录入 | 智能导入（自动识别/手动映射/模板） |
| `/slice-worker` | 切片监控 | Worker 节点状态、任务队列、实时日志（v3） |
| `/monitor` | 监控告警 | 健康检查、告警规则、告警事件（三期） |
| `/maintenance` | 运维优化 | 数据归档、临时文件清理、MinIO 生命周期（三期） |
| `/watermark` | 短片制作 | 提示词生成三版本（AI提示词/长提示词/短提示词，长/短模板可在线编辑持久化，复用 AutoClip 模型，10s/15s/自定义时长，题材/基调/角色下拉预设） + 成片视频上传/一键导入去水印 + 四套开源去水印引擎切换（seedance_wm / remove_mask / RAiW / Seedance 2.0）、批量上传/下载、异步进度、任务历史 + 短剧发布素材生成（短标题/三款配文/成套标签/三条神评），提示词→去水印→发布任务 id 关联自动代入文案，v4/v5 去水印；v6 提示词生成；v6.1 合规代称/自定义时长/预设下拉/历史上传视频导入去水印；v7 发布素材生成；v8 remove_mask ROI 经验库引擎；v9 提示词三版本 tab；v10 模板可编辑+Tab 顺序+历史去时间+状态重置+任务关联） |
| `/settings` | 系统设置 | 全局参数配置 |

### 7.2 导航菜单

```
仪表盘
短剧切片
短片制作
发布管理
数据看板
  ├── 总览
  ├── 内容分析
  └── 数据录入
切片监控
监控告警
运维优化
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
| tus-js-client | 3.x | 断点续传上传 |
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

### 8.2 错误恢复与容错

#### Celery 任务重试

所有异步任务配置统一的重试策略：

```python
class BaseTaskWithRetry(celery.Task):
    autoretry_for = (Exception, ConnectionError, TimeoutError)
    retry_backoff = True          # 指数退避
    retry_backoff_max = 600       # 最大间隔 10 分钟
    retry_max_delay = 300         # 初始延迟上限 5 分钟
    max_retries = 3               # 最多重试 3 次
```

- 视频处理任务（autoclip / detect / slice）：遇到 FFmpeg 崩溃、网络超时自动重试
- RPA 发布任务：遇到页面加载失败、Cookie 失效自动重试
- 数据采集任务：遇到 API 限流自动退避重试

#### 中间文件清理

- 任务完成（成功或失败）后自动清理临时目录
- 清理策略：`slice_outputs` 关联的本地临时文件在任务结束后 24 小时内删除
- MinIO 上的中间文件设置生命周期策略，7 天未访问自动清理

#### 断点续传

- 大文件上传采用 tus 协议，前端使用 tus-js-client，后端使用 tusd
- 上传中断后前端自动从断点恢复，无需重新上传
- 上传并发限制：同时最多 5 个大文件上传，超出排队等待

### 8.3 RPA 发布任务

| 任务名 | 平台 | 说明 |
|--------|------|------|
| `publish_wechat_channels` | 微信视频号 | Playwright 连接 Chrome CDP，自动上传/填写/截图/发布 |
| `publish_douyin` | 抖音 | 同上，页面结构不同 |
| `publish_kuaishou` | 快手 | 同上 |
| `check_cookie_status` | 全平台 | 定期检查登录态是否有效 |

#### 多账号支持

- 每个 `PublishProfile` 对应独立的 Chrome Profile 目录
- 不同账号的 Cookie、登录态完全隔离
- 支持同一平台多账号并行发布

#### 截图审核流程

```
发布前截图存 MinIO
    │
    ▼
前端展示截图预览
    │
    ├── 运营确认 → 执行发布
    ├── 运营拒绝 → 取消任务，标记 rejected
    └── 超时 30 分钟未操作 → 自动取消，标记 timeout
```

#### 失败重试

- 发布失败后最多重试 2 次，间隔 5 分钟
- 重试仍失败则标记 `failed`，通过钉钉机器人通知运营
- 失败原因记录到 `publish_tasks.error_message` 字段

---

## 九、分布式切片执行

### 9.1 方案概述

采用 **Go 单文件 Worker + Redis Stream 任务分发 + MinIO Presigned URL 直传** 的架构，实现切片任务的分布式执行。Worker 节点可以是 Mac（Apple Silicon 硬件加速）、Linux 服务器或 GPU 机器，通过 Redis Stream 接收任务，处理完成后直接将结果上传到 MinIO。

### 9.2 架构图

```
┌─────────────────────┐
│   FastAPI 主服务器    │
│  (任务拆分 + 入队)   │
└──────────┬──────────┘
           │ XADD
           ▼
┌─────────────────────┐
│    Redis Stream      │
│  slice:tasks:high   │  ← 高优先级队列
│  slice:tasks:normal │  ← 普通优先级队列
│  slice:tasks:low    │  ← 低优先级队列
└──────────┬──────────┘
           │ XREADGROUP
     ┌─────┼─────┬──────────┐
     ▼     ▼     ▼          ▼
┌──────┐┌──────┐┌──────┐┌──────┐
│W-1   ││W-2   ││W-3   ││W-N   │
│Mac   ││Linux ││GPU   ││...   │
│(arm) ││(cpu) ││(nvenc││      │
└──┬───┘└──┬───┘└──┬───┘└──┬───┘
   │       │       │       │
   │  Presigned URL 上传    │
   ▼       ▼       ▼       ▼
┌─────────────────────────────────┐
│            MinIO                 │
│   (切片成品直传，无需经过主服务器)  │
└─────────────────────────────────┘
```

### 9.3 Redis 数据结构

| Key | 类型 | 说明 |
|-----|------|------|
| `slice:tasks:high` | Stream | 高优先级任务队列（加急项目） |
| `slice:tasks:normal` | Stream | 普通优先级任务队列 |
| `slice:tasks:low` | Stream | 低优先级任务队列（批量任务） |
| `slice:nodes` | Hash | Worker 节点注册信息（node_id → JSON） |
| `slice:nodes:online` | Set | 当前在线 Worker 节点 ID 集合 |

### 9.4 任务消息格式

```json
{
  "task_id": "uuid-v4",
  "episode_id": 42,
  "mode": "fast|dedupe|scrub",
  "source_url": "https://minio/.../episode_42.mp4",
  "cutlist": [
    {"start": 10.5, "end": 45.2},
    {"start": 60.0, "end": 120.8}
  ],
  "intervals": [
    {"start": 45.2, "end": 60.0, "type": "black_screen"}
  ],
  "dedupe_config": {
    "speed_factor": 1.04,
    "saturation": 0.95,
    "brightness": 0.01,
    "sharpen_amount": 0.8
  },
  "output_upload_urls": {
    "video": "https://minio/.../presigned-put-video",
    "frames": "https://minio/.../presigned-put-frames"
  },
  "priority": "normal",
  "created_at": "2026-08-06T10:00:00Z",
  "timeout_seconds": 7200
}
```

### 9.5 Worker 节点能力标签

| 标签 | 说明 | 适用场景 |
|------|------|---------|
| `cpu` | 通用 CPU 处理 | 普通切片、帧图生成 |
| `gpu` | GPU 加速 | 大规模批量切片 |
| `nvenc` | NVIDIA NVENC 硬件编码 | 高速 H.264/H.265 编码 |
| `apple-silicon` | Apple Silicon VideoToolbox | Mac 节点硬件加速 |

Worker 启动时上报自身能力标签，主服务器根据任务需求匹配合适节点。例如需要 NVENC 编码的任务只分配给带 `nvenc` 标签的 Worker。

### 9.6 容错机制

| 机制 | 配置 | 说明 |
|------|------|------|
| 心跳 | 30 秒 | Worker 每 30 秒向 Redis 发送心跳，更新 `slice:nodes` 中的 `last_heartbeat` |
| 超时重分配 | 2 小时 | 任务超过 2 小时未完成，主服务器通过 XCLAIM 将任务重新分配给其他 Worker |
| Dead-letter 队列 | 自动 | 重试 3 次仍失败的任务进入 `slice:tasks:dead` 队列，等待人工处理 |
| 节点离线检测 | 60 秒 | 超过 60 秒未收到心跳，标记节点离线，其正在处理的任务自动重分配 |

### 9.7 一键启动脚本

Worker 节点通过 `start.sh` 一键启动，自动完成环境初始化：

```bash
#!/bin/bash
# slice-worker/start.sh

# 1. 自动下载 Go Worker 二进制（按平台/架构）
ARCH=$(uname -m)
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
curl -sL "https://releases.internal/slice-worker/${OS}-${ARCH}" -o slice-worker
chmod +x slice-worker

# 2. 下载视频处理引擎脚本
curl -sL "https://releases.internal/engines/latest.tar.gz" | tar xz

# 3. 自动生成配置（从环境变量读取 Redis/MinIO 连接信息）
cat > worker.json <<CONF
{
  "redis_url": "${REDIS_URL}",
  "redis_stream_prefix": "slice:tasks",
  "minio_endpoint": "${MINIO_ENDPOINT}",
  "minio_access_key": "${MINIO_ACCESS_KEY}",
  "minio_secret_key": "${MINIO_SECRET_KEY}",
  "node_id": "$(hostname)-$(date +%s)",
  "capabilities": ["${WORKER_CAPABILITY:-cpu}"],
  "concurrency": ${WORKER_CONCURRENCY:-2}
}
CONF

# 4. 启动 Worker
./slice-worker --config worker.json
```

### 9.8 TUI 界面预览

Worker 节点提供基于 **bubbletea** 框架的终端 UI，方便运维人员在服务器上实时查看状态：

```
┌─ Slice Worker ──────────────────────────────────────┐
│  Node: mac-studio-01  |  Capabilities: apple-silicon │
│  Status: ● Online     |  Uptime: 2h 34m             │
├──────────────────────────────────────────────────────┤
│  Tasks                                                │
│  ┌──────────────────────────────────────────────────┐│
│  │ #1042  ep42-scrub  ████████████░░░░  75%  03:21 ││
│  │ #1041  ep38-fast   ████████████████  100% ✓     ││
│  │ #1040  ep37-dedupe ░░░░░░░░░░░░░░░░  0%  Queued││
│  └──────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────┤
│  Logs                                                │
│  [10:32:15] #1042 FFmpeg: encoding segment 3/4       │
│  [10:32:12] #1041 Upload complete → minio/outputs/   │
│  [10:31:58] #1042 Heartbeat sent                     │
└──────────────────────────────────────────────────────┘
```

### 9.9 部署方式

| 方式 | 命令 | 说明 |
|------|------|------|
| 前台启动 | `bash start.sh` | 显示 TUI 界面，适合调试 |
| 后台模式 | `bash start.sh --daemon` | 后台运行，日志写入文件 |
| systemd | `systemctl start slice-worker` | Linux 服务管理 |
| launchd | `launchctl load slice-worker.plist` | macOS 服务管理 |

---

## 十、Docker 服务编排

### 10.1 服务列表（14 个）

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `postgres` | postgres:15-alpine | 5432 | 数据库 |
| `redis` | redis:7-alpine | 6379 | 缓存 + 消息队列 + Stream 分发 |
| `minio` | minio/minio:latest | 9000/9001 | 对象存储 |
| `minio_init` | minio/mc:latest | — | Bucket 初始化（一次性） |
| `autoclip` | 构建自 ./autoclip | 8000 | AI 选点 API |
| `autoclip_worker` | 同 autoclip | — | AI 选点 Worker |
| `alembic-migrate` | 构建自 ./backend | — | 数据库迁移（Alembic，一次性） |
| `backend` | 构建自 ./backend | 8000 | 主 API 服务 |
| `worker` | 同 backend | — | 视频处理 Worker |
| `beat` | 同 backend | — | Celery 定时调度（含告警/维护任务） |
| `rpa_worker` | 构建自 ./rpa | 9222 | RPA 发布 Worker（可选） |
| `frontend` | 构建自 ./frontend | 80 | 前端静态文件 |
| `nginx` | nginx:1.25-alpine | 80 | 反向代理入口 |
| `flower` | 同 backend | 5555 | Celery 任务监控（可选） |

> 注：分布式切片 Worker 不在 Docker Compose 中编排，通过 `start.sh` 在目标机器上独立部署（支持 Mac/Linux）。

### 10.2 数据卷

| 卷名 | 用途 |
|------|------|
| `postgres_data` | 数据库持久化 |
| `redis_data` | Redis AOF 持久化 |
| `minio_data` | 对象存储数据 |
| `media_data` | 媒体文件缓存 |
| `chrome_profiles` | Chrome 浏览器 Profile（RPA 用） |

### 10.3 Nginx 路由规则

| 路径 | 代理目标 | 说明 |
|------|---------|------|
| `/` | `frontend:80` | 前端静态文件（30 天缓存） |
| `/api/` | `backend:8000` | 后端 API |
| `/autoclip/` | `autoclip:8000` | AutoClip API（rewrite 去前缀） |
| `/ws/` | `backend:8000` | WebSocket（长连接 86400s） |
| `/minio/` | `minio:9000` | MinIO 代理（500M 上传限制） |
| `/health` | 200 OK | 健康检查 |

---

## 十一、IAA 数据看板

### 11.1 业务链路

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

### 11.2 指标体系（五层）

| 层级 | 关注问题 | 核心指标 |
|------|---------|---------|
| L1 总览 | 今天赚了多少？ | 累计/今日收益、累计播放、小程序UV、eCPM |
| L2 内容 | 视频表现如何？ | 播放量、完播率、互动率、社交推荐占比、跳转率 |
| L3 短剧 | 小程序和广告表现？ | 小程序UV、短剧完播率、广告曝光、eCPM |
| L4 漏斗 | 转化断在哪？ | 播放→跳转→开播→广告曝光→收益 各环节转化率 |
| L5 生态 | 公众号/企微反哺？ | 公众号导流UV、企微新增好友 |

### 11.3 数据归因

#### 渠道参数归因（精确）

发布时系统自动生成带渠道参数的跳转链接，完整链路如下：

```
发布视频时生成跳转链接
   │ 链接格式：https://xxx.com/drama?id=123&vid={视频ID}&from=video
   ▼
小程序解析参数
   │ 用户点击链接 → 小程序获取 vid 参数 → 调用统计接口回传
   ▼
后端按 vid 聚合 UV
   │ 统计接口收到回传 → 按 vid 维度累计 UV/PV
   ▼
计算单视频收益
   │ 精确归因：直接统计该视频引流带来的广告收益
   ▼
写入 video_metrics 表
```

**数据关联链路**：

```
video_metrics.publish_task_id → publish_tasks.id
publish_tasks.published_url  → 提取平台视频 ID
video_metrics.vid            → 渠道参数中的视频标识
```

#### 间接归因（近似）

当无法获取精确渠道参数时，采用间接归因：

```
单视频收益 = 该视频引流UV × (当日总收益 ÷ 当日总UV)
```

- 适用场景：评论区引导、主页入口等无法携带 vid 参数的场景
- 精度说明：假设所有 UV 的平均收益贡献相同，为近似值

#### 归因配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| 归因时间窗口 | 7 天 | 视频发布后 7 天内的引流数据计入归因 |
| 窗口可配置范围 | 1-30 天 | 在系统设置中调整 |

### 11.4 智能数据导入

#### 三种导入模式

```
┌──────────────────────────────────────────────────────────────┐
│                    智能数据导入流程                            │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  模式一：自动识别（推荐）                                      │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 上传文件 → 平台指纹匹配 → 自动解析 → 确认导入           │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  模式二：手动映射                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 上传文件 → 预览内容 → 拖拽列对应关系 → 确认导入          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  模式三：标准模板（兜底）                                      │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 下载标准模板 → 按模板填写数据 → 上传 → 直接导入          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

#### 平台指纹库

系统内置各平台导出文件的格式指纹，上传文件后自动匹配：

| 平台 | 指纹特征 | 典型字段 |
|------|---------|---------|
| 视频号创作者中心 | 特定列名组合 + CSV 编码 | "播放量"、"点赞数"、"分享数"、"评论数" |
| 小程序数据分析 | 固定表头 + 日期格式 | "页面路径"、"访问UV"、"播放次数"、"完播率" |
| 广告/流量主后台 | 金额单位为"分" + 特定列名 | "广告位"、"曝光量"、"点击量"、"结算金额(分)" |
| 抖音 | 创作者服务平台导出格式 | "播放"、"点赞"、"评论"、"转发" |
| 快手 | 创作者中心导出格式 | "播放量"、"点赞"、"评论"、"分享" |

#### 单位自动转换

| 场景 | 转换规则 | 说明 |
|------|---------|------|
| 广告后台金额 | "分" → "元"（÷100） | 自动检测列名含"分"或值为整数 >10000 |
| 播放量 | "万" → 数字（×10000） | 自动检测含"万"/"w"的值 |
| 百分比 | "32.5%" → 0.325 | 自动去除百分号并转换 |

#### 数据更新策略

- 重复导入检测：按「日期 + 平台 + 数据维度」判断是否已存在
- 覆盖模式：新数据覆盖旧数据，保留导入记录
- 跳过模式：已存在的数据不覆盖，仅导入新数据
- 导入前提示：检测到重复数据时弹窗让用户选择覆盖或跳过

#### 数据来源说明

| 数据类型 | 来源 | 方式 | 说明 |
|---------|------|------|------|
| 视频号内容数据 | 创作者中心 CSV 导出 | 手动 | 播放/互动/跳转等 |
| 小程序数据 | 小程序后台 CSV 导出 | 手动 | UV/播放/完播率 |
| 广告数据 | 流量主后台 CSV 导出 | 手动 | 曝光/点击/eCPM/收益 |
| 发布数据 | 系统自动记录 | 自动 | RPA 发布时自动写入 |
| *未来：小程序数据分析* | *小程序 API 自动拉取* | *自动（V3）* | *待对接微信开放 API* |

---

## 十二、安全设计

### 12.1 API 认证

采用 JWT 双 Token 机制：

| Token | 有效期 | 存储位置 | 用途 |
|-------|--------|---------|------|
| `access_token` | 30 分钟 | 前端内存（Zustand） | API 请求鉴权 |
| `refresh_token` | 7 天 | HttpOnly Cookie | 无感刷新 access_token |

- access_token 过期后前端自动使用 refresh_token 获取新 token
- refresh_token 过期后需重新登录
- 支持 Token 黑名单（用户主动登出时使 refresh_token 失效）

### 12.2 权限模型（RBAC）

| 角色 | 权限范围 |
|------|---------|
| `superadmin` | 全部功能 + 系统配置 + 用户管理 + 审计日志查看 |
| `admin` | 项目管理（短剧切片） + 发布管理 + 数据看板 + 去重参数配置 + 数据导入 + 短片制作 |
| `user` | 查看分配给自己的项目 + 录入数据 + 执行分配的任务 |

**权限矩阵**：

| 功能模块 | superadmin | admin | user |
|---------|-----------|-------|------|
| 系统配置 | 读写 | 只读 | 无 |
| 用户管理 | 增删改查 | 只读 | 无 |
| 项目管理（短剧切片） | 全部项目 | 全部项目 | 仅分配给自己的 |
| 发布管理 | 全部 | 全部 | 仅分配给自己的 |
| 数据看板 | 全部 | 全部 | 仅录入 |
| 去重参数配置 | 读写 | 读写 | 无 |
| 数据导入 | 读写 | 读写 | 只读 |
| 审计日志 | 查看 | 无 | 无 |
| 切片 Worker 管理 | 读写 | 只读 | 无 |

### 12.3 MinIO Presigned URL

- 有效期：30 分钟，过期自动刷新
- 上传 URL：前端请求后端获取临时上传 URL，直接上传到 MinIO（不经过后端）
- 下载 URL：成品预览/下载通过 Presigned URL 直接访问 MinIO
- 安全限制：URL 绑定具体文件路径，不可遍历其他文件

### 12.4 RPA Cookie 加密

- 存储方式：AES-256 加密后存入数据库
- 加密密钥：从 `.env` 文件读取，不硬编码
- 访问控制：仅 RPA Worker 服务可解密 Cookie
- 传输安全：Cookie 在 API 响应中脱敏显示（`****`）

### 12.5 敏感信息管理

| 措施 | 说明 |
|------|------|
| `.env` 文件权限 | 设置为 600（仅 owner 可读写） |
| Docker secrets | 生产环境使用 Docker secrets 管理密码 |
| 数据库密码 | 不在代码中出现，仅通过环境变量注入 |
| API Key | 通义千问 API Key 等通过 `.env` 管理 |
| 日志脱敏 | 敏感字段（密码、Cookie、Token）在日志中自动脱敏 |

---

## 十三、监控与运维（三期）

### 13.1 健康检查

| 检查项 | 方式 | 说明 |
|--------|------|------|
| 后端服务 | `GET /api/health` | 返回 200 OK（轻量，供 Docker healthcheck） |
| 增强健康检查 | `GET /api/health/detailed` | 数据库/Redis/MinIO/磁盘 连接状态（三期） |
| 监控面板 | `/api/monitor/health` | 前端监控告警页健康检查卡片 |
| Docker 容器 | `docker healthcheck` | 每个服务配置健康检查指令 |
| Worker 节点 | Redis 心跳 | 30 秒心跳，60 秒未响应标记离线 |
| RPA Cookie | 定时检测 | `check_cookie_status` 任务定期检查登录态 |

### 13.2 任务监控

| 工具 | 端口 | 说明 |
|------|------|------|
| Celery Flower | 5555 | 实时查看任务队列、执行状态、失败重试 |
| Worker TUI | 终端 | 分布式切片 Worker 的 bubbletea 界面 |
| Docker logs | — | `docker compose logs -f` 实时查看 |
| 监控告警页 | 前端 | 健康检查卡片 + 告警规则/事件管理（三期） |

### 13.3 告警规则（三期）

| 告警项 | 指标 | 默认阈值 | 级别 | 说明 |
|--------|------|--------|------|------|
| Worker 离线 | worker_offline | >60 秒无心跳 | 严重 | 分布式切片 Worker 失联 |
| 任务失败 | task_failed | 同一任务失败 >3 次 | 严重 | 需要人工介入 |
| 磁盘使用 | disk_usage | >80% | 警告 | 清理临时文件或扩容 |
| Cookie 即将过期 | cookie_expiring | 有效期 <24 小时 | 警告 | 提醒运营重新扫码 |
| Redis 内存 | redis_memory | >80% 最大内存 | 警告 | 清理过期 key 或扩容 |
| 队列积压 | queue_backlog | 待处理任务 >100 | 警告 | 增加 Worker 节点 |
| eCPM 偏低 | ecpm_low | <10 元 | 警告 | 检查广告填充率 |

规则存储于 `alert_rules` 表，事件落库 `alert_events`，支持在监控页配置启停/阈值/Webhook。

### 13.4 告警通道

- **钉钉机器人 Webhook**：所有告警推送到运维群（规则级 Webhook 优先，其次全局 `DINGTALK_WEBHOOK`）
- 消息格式：`[级别] 告警项 - 详情 - 时间`
- 示例：`[严重] Worker mac-studio-01 离线超过 60 秒 - 2026-08-06 10:32:15`
- Celery beat 周期执行 `run_alert_check_task`（默认每 300 秒）

### 13.5 性能优化（三期）

| 优化项 | 配置 | 说明 |
|--------|------|------|
| 上传并发限制 | 最多 5 个同时上传 | 防止带宽打满 |
| 数据库分区 | `video_metrics` 按日期分区 | 提升查询性能 |
| 数据归档 | >90 天的看板数据定期归档 | 保持主表轻量（`METRICS_ARCHIVE_DAYS`） |
| 临时文件清理 | >24h 的本地临时文件清理 | 释放磁盘空间 |
| MinIO 生命周期 | 90 天未访问 → 低频存储 | 降低存储成本（`MINIO_LIFECYCLE_DAYS`） |
| Redis TTL | 任务消息 TTL 24 小时 | 防止队列堆积 |
| 数据库迁移 | Alembic 管理 schema 版本 | 安全迭代数据库结构 |

---

## 十四、部署指南

### 14.1 环境要求

| 配置项 | 最低要求 | 推荐配置 |
|--------|---------|---------|
| CPU | 4 核 | 8 核+ |
| 内存 | 8 GB | 16 GB+ |
| 磁盘 | 100 GB SSD | 500 GB+ SSD |
| Docker | 20.10+ | 最新稳定版 |
| Docker Compose | 2.0+ | 最新稳定版 |

### 14.2 本地部署

```bash
# 克隆代码
git clone https://github.com/ben500500/clip-workflow.git
cd clip-workflow

# 一键部署
bash deploy.sh
```

### 14.3 阿里云部署

```bash
# SSH 登录服务器后执行
cd /opt && git clone --depth 1 https://github.com/ben500500/clip-workflow.git
cd clip-workflow
bash scripts/server-setup.sh --skip-rpa
```

安全组需放行端口：80（Web）、9001（MinIO 控制台）。

### 14.4 环境变量

首次部署时从 `.env.example` 自动生成 `.env`，包含以下关键配置：

| 配置段 | 关键变量 |
|--------|---------|
| 数据库 | `POSTGRES_PASSWORD` |
| Redis | `REDIS_PASSWORD` |
| MinIO | `MINIO_ROOT_PASSWORD` |
| AutoClip | `DASHSCOPE_API_KEY`（通义千问 API Key） |
| RPA | `CHROME_DEBUG_PORT`、`RPA_REQUIRE_MANUAL_CONFIRM` |
| 安全 | `JWT_SECRET_KEY`、`COOKIE_ENCRYPT_KEY` |
| 切片 Worker | `SLICE_WORKER_REDIS_URL`、`SLICE_WORKER_CAPABILITY` |

### 14.5 常用运维命令

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

# 数据库迁移
alembic upgrade head

# 查看 Celery 任务监控
open http://localhost:5555
```

---

## 十五、开发分期

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

### 二期（+4 周）— 已完成

- Playwright RPA Worker ✅
- 视频号自动发布 + 截图确认 ✅
- 小程序挂载引导 ✅
- 短剧变现页（小程序/广告指标 + 分剧排行）✅
- 转化漏斗完整版 ✅
- 视频标签系统 + 多维交叉分析 ✅
- 异常预警 ✅
- **分布式切片执行**（Go Worker + Redis Stream + TUI 监控）✅
- **智能数据导入**（平台指纹匹配 + 手动映射 + 标准模板）✅
- **安全认证体系**（JWT 双 Token + RBAC 三级权限 + Cookie 加密）✅
- **数据库迁移**（Alembic 集成）✅

### 三期（按需）— 部分完成

- **监控告警系统**（健康检查 + 告警规则 + 钉钉 Webhook）✅
- 生态联动页（公众号/企微）✅
- 小程序 API 自动拉取（待对接微信开放 API）
- **GPU 加速编码**（nvenc / VideoToolbox 自动探测 + 手动指定）✅
- **竖屏转横屏智能裁切**（固定裁切 / 动态人脸跟踪，切片执行可选）✅
- 多平台发布 API 对接（Playwright RPA 已支持三平台）
- **性能优化**（数据归档 + 临时文件清理 + MinIO 存储生命周期）✅

---

## 十六、风险与注意事项

### 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| AutoClip API 不稳定 | 选点失败 | 支持手动选点 fallback |
| FFmpeg 任务 OOM | 服务崩溃 | Worker concurrency=1 |
| Playwright 页面改版 | 自动发布失效 | 监控 + 告警 + 快速修复 |
| Cookie 过期 | 发布中断 | 定期检测 + 提示扫码 |
| 大文件上传中断 | 体验差 | tus 断点续传 |
| 分布式 Worker 失联 | 任务积压 | 心跳检测 + XCLAIM 重分配 + dead-letter 队列 |
| Redis Stream 积压 | 内存溢出 | 任务消息 TTL 24h + 队列积压告警 |

### 业务风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 视频号检测 RPA 行为 | 账号受限 | 随机延迟 + 人工确认 + 限量（默认 20 条/天） |
| 去重参数被识别 | 切片被限流 | 多平台 Profile 调优 |
| 收益归因不准 | 决策偏差 | 渠道参数归因 + 间接归因双轨 |
| 数据录入滞后 | 看板不准 | 智能导入降低门槛 + 未来 API 自动化 |

---

## 十七、附录

### A. 现有脚本清单

| 文件 | 用途 | 部署位置 |
|------|------|---------|
| `slice.sh` | 普通切片（fast/dedupe） | `engines/` |
| `slice_scrub.sh` | 挖洞模式切片 | `engines/` |
| `detect_intervals.py` | 通用区间检测（黑场/静止画面/水印/自定义） | `engines/` |
| `vert2horiz_crop.py` | 竖屏转横屏（固定裁切/动态人脸跟踪） | `engines/` |
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

### E. 近期变更日志（v2.0 → v2.1）

| 日期 | 变更 |
|------|------|
| 2026-08-06 | 三期实现：监控告警系统（健康检查+告警规则+钉钉Webhook）、运维优化（数据归档+临时清理+MinIO生命周期）、GPU加速编码（nvenc/VideoToolbox）、JWT双Token+Cookie AES加密、Alembic迁移、视频多标签系统 |
| 2026-08-06 | 一键切片移到剧集详情工作台入口；Worker 心跳双写后端 DB；成品预览点击整行展开视频；切片执行支持自定义文字动态水印 |
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
| 2026-08-06 | AutoClip ASR 字幕缓存复用：按视频内容哈希+ASR方式缓存 SRT，再次启动 AI 选点直接复用，避免重复转写（可 `AUTOCLIP_ASR_CACHE=false` 关闭） |

---

> GitHub 仓库：https://github.com/ben500500/clip-workflow
>
> 本文档随项目迭代持续更新。
