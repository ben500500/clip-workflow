# 端到端自动化操作流程（Computer-Use Playbook）

> 版本：v1.1（契约对齐）| 日期：2026-08-18
> 适用对象：Computer-Use / Agent 类插件（Claude、Codex、Browser-Use 等）
> 目标链路：**资源导入 → AI 选点 → 区间检测 → 切片 → 视频号发布**
> 说明：本文档是给 **Computer-Use 类插件**看的「操作手册」，所有步骤都给出可执行的 API 调用序列和浏览器操作路径。插件可以直接按步骤逐步执行。
> ⚠️ **v1.1 契约对齐**：本文档所有接口契约已与 `main` 分支真实代码逐一核对修正（登录/刷新路径、登录态 `state` 枚举、发布确认 `pending_confirm`、tus 分片上传、账号 `enabled` 字段）；第四节问题清单已按 PR #177 标注修复状态。**测试请以本文档为准**，避免按旧契约踩 404/判错。

---

## 〇、前置准备

### 0.1 系统地址与登录

| 项 | 值 | 备注 |
|----|----|------|
| 前端 URL | `http://<host>:5173` 或生产环境 | 具体取决于部署环境 |
| 后端 API | `http://<host>:8000/api` | FastAPI |
| 登录方式 | `POST /api/auth/login` | 用户名 + 密码 → `access_token`（auth 路由自带 `/api/auth` 前缀） |
| Token 格式 | `Authorization: Bearer <access_token>` | 所有后续请求都需要 |

### 0.2 登录请求体

```json
{
  "username": "<用户名>",
  "password": "<密码>"
}
```

**响应**：
```json
{
  "access_token": "eyJhbGciOi...",
  "user": {
    "id": "uuid",
    "username": "operator_1",
    "role": "operator"
  }
}
```

### 0.3 需要的角色权限

| 角色 | 必备能力 | 说明 |
|------|---------|------|
| `admin` | 全部 | 推荐使用，避免权限不足 |
| `operator` | 素材导入、选点、切片、发布 | 满足日常流程 |
| `publisher` | 发布管理 | 只能发布 |

> ⚠️ **注意**：多运营者发布需要 `operator_id` 与账号绑定。若使用 `admin` 角色，须确保运营者映射已配置。

---

## 一、链路总览（Flow Overview）

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  ① 登录   │ → │ ② 资源导入│ → │ ③ AI选点  │ → │ ④ 区间检测 │ → │ ⑤ 切片   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
                                                    │              │
                                                    │              ▼
                                                    │        ┌──────────┐
                                                    │        │ ⑥ 成品库   │
                                                    │        └──────────┘
                                                    │              │
                                                    ▼              ▼
                                              ┌─────────────────────────┐
                                              │ ⑦ 发布（视频号多运营者）  │
                                              └─────────────────────────┘
                                                    │
                                                    ▼
                                              ┌──────────┐
                                              │ ⑧ 确认发布 │
                                              └──────────┘
```

---

## 二、详细操作步骤（API 调用序列）

---

### ① 登录系统

**请求**：`POST /api/auth/login`

```json
{
  "username": "admin",
  "password": "******"
}
```

**响应**：获取 `access_token`，后续所有请求需带 `Authorization: Bearer <token>` 头。

**检查点**：
- [ ] 返回 `200 OK`，包含 `access_token`
- [ ] 用户角色为 `admin` 或 `operator`

---

### ② 资源导入（视频号链接 → 入库）

> **说明**：有两种路径。
> - **路径 A**：从「资源下载」页面粘贴视频号分享链接（推荐，全自动）
> - **路径 B**：从本地上传视频文件（传统路径）

---

#### 路径 A：视频号链接导入

**步骤 A1**：创建下载任务

**请求**：`POST /api/wechat-dl/import`

```json
{
  "source_url": "https://channels.weixin.qq.com/xxx/xxx",
  "source_type": "self_owned",
  "project_id": null
}
```

**响应**：
```json
{
  "task_id": "uuid",
  "status": "pending",
  "message": "已创建下载任务并进入 wechat_dl 队列"
}
```

**步骤 A2**：轮询下载任务状态

**请求**：`GET /api/wechat-dl/tasks/{task_id}`

**轮询间隔**：每 5 秒

**检查点**：
- [ ] `status` 依次经过 `pending → parsing → downloading → uploading → completed`
- [ ] 若 `status == "failed"`，检查 `error_message`，必要时重试

**步骤 A3**：下载完成 → 导入切片项目

**请求**：`POST /api/wechat-dl/tasks/{task_id}/import-to-project`

```json
{
  "target": "new",
  "project_name": "测试剧集-第1集"
}
```

或：

```json
{
  "target": "existing",
  "project_id": "已有项目UUID"
}
```

**响应**：
```json
{
  "project_id": "uuid",
  "episode_id": "uuid",
  "target": "new"
}
```

**检查点**：
- [ ] 返回 `project_id` 和 `episode_id`
- [ ] 该 episode 已归属目标项目，可在「素材管理」看到

---

#### 路径 B：本地上传

**步骤 B1**：创建上传会话

**请求**：`POST /api/upload/resume`

```json
{
  "file_name": "test_video.mp4",
  "file_size": 1024000,
  "chunk_size": 5242880,
  "metadata": {}
}
```

**响应**：`{ "id": "upload_id", "offset": 0, ... }`

**步骤 B2**：分片上传（循环，tus 协议）

**请求**：`PATCH /api/upload/{upload_id}`

请求头：`Upload-Offset: {offset}`（当前偏移）

body 为原始二进制分片数据（**不是 multipart，直接 raw bytes**）。每次返回 `{ "id": ..., "offset": <新偏移>, ... }`，以下一次返回的 offset 作为下一片的 `Upload-Offset` 续传，直到 `completed: true`。

**步骤 B3**：完成上传

**请求**：`POST /api/upload/complete`

```json
{
  "upload_id": "uuid",
  "project_id": "项目UUID",
  "title": "测试剧集-第1集",
  "episode_no": 1
}
```

**响应**：`{ "episode_id": "uuid", ... }`

**检查点**：
- [ ] 返回 `episode_id`
- [ ] 上传完成后文件已在 MinIO `raw-footage` 桶

> ⚠️ **上传协议注意**：本系统分片上传走 **tus 协议**（`PATCH /api/upload/{upload_id}` + `Upload-Offset` 请求头，原始二进制 body），不是传统的 `PUT ...?offset=` 表单分片。

---

### ③ AI 选点（AutoClip）

> **前置条件**：已有 `episode_id`（从步骤②获得）。

**步骤 C1**：启动 AI 选点

**请求**：`POST /api/episodes/{episode_id}/autoclip/run`

请求体（可选配置，未传则用默认值）：
```json
{
  "config": {
    "min_duration": 30,
    "max_duration": 180,
    "clip_count": 3,
    "model": "qwen-plus"
  }
}
```

**响应**：
```json
{
  "run_id": "uuid",
  "status": "running",
  "message": "AI 选点已启动"
}
```

**步骤 C2**：轮询选点进度

**请求**：`GET /api/episodes/{episode_id}/autoclip/progress`

**轮询间隔**：每 10 秒

**检查点**：
- [ ] `status` 从 `running` → `completed`
- [ ] 若 `status == "failed"`，检查 `error_message`
- [ ] 超时时间：**1 小时**（长视频 ASR 可能较慢）

**步骤 C3**：获取候选片段

**请求**：`GET /api/episodes/{episode_id}/autoclip/clips`

**响应**：
```json
[
  {
    "id": "clip_uuid",
    "clip_index": 1,
    "start_time": 120.5,
    "end_time": 180.0,
    "status": "pending",
    "score": 85.2,
    "summary": "高光片段描述"
  }
]
```

**检查点**：
- [ ] 至少返回 1 条候选片段
- [ ] 若返回空列表，说明选点未产出候选（需后续处理）

**步骤 C4**：自动审核全部候选片段

> 免审核模式：全部候选自动通过（`auto_accept_all: true`）。手动模式则需逐条更新状态。

**自动模式**（推荐）：直接跳到步骤⑤切片，传 `auto_accept_all: true`。

**手动模式**：逐条审核
**请求**：`PUT /api/clips/{clip_id}`

```json
{
  "status": "accepted"
}
```

---

### ④ 通用区间检测（可选，但推荐）

> **前置条件**：已有 `episode_id`。

**步骤 D1**：启动区间检测

**请求**：`POST /api/episodes/{episode_id}/intervals/detect`

```json
{
  "config": {
    "detect_type": "credits",
    "max_detect_time": 300
  }
}
```

**响应**：`{ "task_id": "uuid", "status": "running" }`

**步骤 D2**：轮询检测进度

**请求**：`GET /api/episodes/{episode_id}/intervals/progress`

**轮询间隔**：每 5 秒

**检查点**：
- [ ] `status` 从 `running` → `completed`
- [ ] 超时时间：**30 分钟**

**步骤 D3**：查看检测到的区间

**请求**：`GET /api/episodes/{episode_id}/intervals`

**检查点**：
- [ ] 确认已检测到片尾/片头等需去除的区间
- [ ] 如需手动添加/修改区间，用 `POST /api/intervals` / `PUT /api/intervals/{id}`

---

### ⑤ 切片执行

> **前置条件**：已有 `episode_id`，且已完成 AI 选点（步骤③）。

**步骤 E1**：执行切片

**请求**：`POST /api/episodes/{episode_id}/slice/run`

**完整请求体**（按需选填）：
```json
{
  "mode": "standard",
  "engine": "worker",
  "auto_accept_all": true,
  "variant_count": 3,
  "watermark_enabled": true,
  "watermark_text": "短剧名",
  "watermark_style": "scroll",
  "subtitle_enabled": true,
  "subtitle_mask_enabled": true,
  "subtitle_mask_preset": "auto",
  "subtitle_align_mask": true,
  "vert2horiz_enabled": false,
  "badge_default_width": 0,
  "dedupe_config": {
    "mode": "scale+shift",
    "params": {
      "scale_min": 0.98,
      "scale_max": 1.02
    }
  }
}
```

**响应**：
```json
{
  "task_id": "uuid",
  "status": "running",
  "message": "切片任务已发布到 worker 队列"
}
```

**步骤 E2**：轮询切片任务状态

**请求**：`GET /api/episodes/{episode_id}/slice/tasks`

**轮询间隔**：每 10 秒

**检查点**：
- [ ] 最新任务 `status` 从 `running` → `completed`
- [ ] 若 `status == "failed"`，检查 `error_message` 并重试
- [ ] 超时时间：**2 小时**

**步骤 E3**：获取切片输出

**请求**：`GET /api/slice-tasks/{task_id}/outputs`

**响应**：
```json
[
  {
    "id": "output_uuid",
    "file_key": "sliced/xxx.mp4",
    "duration": 45.5,
    "status": "completed",
    "presigned_url": "https://minio/..."
  }
]
```

**检查点**：
- [ ] `outputs` 数组非空
- [ ] 每个输出有 `file_key`，可用于后续发布

---

### ⑥ 成品预览（可选）

**请求**：`GET /api/preview/{output_id}` 或通过 `presigned_url` 直接预览

---

### ⑦ 创建发布任务（视频号）

> **前置条件**：已有 `output_id`（切片输出）和 `video_account_id`（视频号账号）。

**步骤 F1**：获取可用的视频号账号

**请求**：`GET /api/publish/video-accounts`

**响应**：
```json
[
  {
    "id": "account_uuid",
    "account_name": "运营者-张三",
    "platform": "wechat",
    "enabled": true,
    "profile_id": "profile_uuid",
    "operator_id": "operator_uuid"
  }
]
```

**检查点**：
- [ ] 至少有 1 个 `enabled == true` 的账号（注意是 `enabled: bool`，不是 `status`）
- [ ] 账号已绑定 `profile_id`（对应 Chrome 端口）

**步骤 F2**：检查登录状态

**请求**：`GET /api/publish/login/status/{account_id}`

**响应**：
```json
{
  "account_id": "account_uuid",
  "state": "ready"
}
```

> 状态枚举：`logging`（扫码中）/ `ready`（已登录）/ `need_login`（需扫码）/ `expired`（已失效）/ `unknown`。

**检查点**：
- [ ] `state == "ready"` 即表示已登录
- [ ] 若 `state` 为 `need_login`/`expired`：`POST /api/publish/login/qr` 生成二维码 → 用户扫码登录（二维码归属见「运营者端口矩阵」）

**步骤 F3**：创建发布任务

**请求**：`POST /api/publish/tasks`

```json
{
  "output_id": "切片输出UUID",
  "platform": "wechat",
  "video_account_id": "视频号账号UUID",
  "title": "测试视频标题",
  "description": "测试视频描述",
  "tags": ["短剧", "推荐"],
  "require_manual_confirm": true,
  "scheduled_at": null
}
```

**响应**：
```json
{
  "id": "publish_task_uuid",
  "status": "pending",
  "celery_task_id": "celery-task-uuid",
  "title": "测试视频标题"
}
```

**检查点**：
- [ ] 返回 `publish_task_id`
- [ ] `status` 为 `pending` 或 `running`

**步骤 F4**：轮询发布任务状态

**请求**：`GET /api/publish/tasks/{publish_task_id}`

**轮询间隔**：每 10 秒

**检查点**：
- [ ] `status` 从 `pending` → `running`
- [ ] 若发布完成（自动确认），`status == "published"`，获得 `published_url`
- [ ] 若需人工确认，`status` 变为 `pending_confirm`（注意是 `pending_confirm`，不是 `awaiting_confirm`），此时需执行步骤⑤

**步骤 F5**：获取发布截图（审核用）

**请求**：`GET /api/publish/tasks/{task_id}/screenshot`

**响应**：截图 URL，可下载查看。

**检查点**：
- [ ] 截图已生成，内容与预期一致

---

### ⑧ 确认发布（仅当 require_manual_confirm=true 时）

**请求**：`POST /api/publish/tasks/{task_id}/confirm`

**响应**：
```json
{
  "id": "publish_task_uuid",
  "status": "published",
  "published_url": "https://channels.weixin.qq.com/xxx",
  "published_id": "视频号视频ID"
}
```

**检查点**：
- [ ] `status == "published"`
- [ ] 已获得 `published_url` 和 `published_id`

---

### ⑨ 批量发布（多运营者场景）

**请求**：`POST /api/publish/tasks/batch`

```json
{
  "tasks": [
    {
      "output_id": "切片输出1",
      "platform": "wechat",
      "video_account_id": "账号1",
      "title": "标题1"
    },
    {
      "output_id": "切片输出2",
      "platform": "wechat",
      "video_account_id": "账号2",
      "title": "标题2"
    }
  ]
}
```

---

## 三、完整的端到端自动化脚本（一次调用走完全链路）

以下是一个伪代码/流程脚本，展示了如何用一次自动化脚本走完整流程：

```yaml
# automation_flow.yaml
# Computer-Use 自动化流程定义

workflow:
  name: "视频号素材导入到发布全自动"
  version: "1.0"

steps:
  - id: login
    name: "登录系统"
    action: api_call
    method: POST
    path: /api/auth/login
    body:
      username: "{{ENV.USERNAME}}"
      password: "{{ENV.PASSWORD}}"
    expect:
      status_code: 200
      access_token: present

  - id: import_video
    name: "导入视频号链接"
    action: api_call
    method: POST
    path: /api/wechat-dl/import
    body:
      source_url: "{{FLOW.VIDEO_URL}}"
      source_type: "self_owned"
    expect:
      status_code: 201
      task_id: present

  - id: poll_import_status
    name: "轮询下载状态"
    action: poll
    path: /api/wechat-dl/tasks/{import_video.task_id}
    interval_sec: 5
    timeout_sec: 600
    until:
      status: "completed"
    on_failed: retry_import

  - id: import_to_project
    name: "导入到切片项目"
    action: api_call
    method: POST
    path: /api/wechat-dl/tasks/{import_video.task_id}/import-to-project
    body:
      target: "new"
      project_name: "{{FLOW.PROJECT_NAME}}"
    expect:
      project_id: present
      episode_id: present

  - id: run_autoclip
    name: "启动 AI 选点"
    action: api_call
    method: POST
    path: /api/episodes/{import_to_project.episode_id}/autoclip/run
    body: {}
    expect:
      status_code: 200
      run_id: present

  - id: poll_autoclip
    name: "轮询选点进度"
    action: poll
    path: /api/episodes/{import_to_project.episode_id}/autoclip/progress
    interval_sec: 10
    timeout_sec: 3600
    until:
      status: "completed"

  - id: run_slice
    name: "执行切片"
    action: api_call
    method: POST
    path: /api/episodes/{import_to_project.episode_id}/slice/run
    body:
      mode: "standard"
      engine: "worker"
      auto_accept_all: true
      variant_count: 3
      watermark_enabled: true
    expect:
      task_id: present

  - id: poll_slice
    name: "轮询切片状态"
    action: poll
    path: /api/episodes/{import_to_project.episode_id}/slice/tasks
    interval_sec: 10
    timeout_sec: 7200
    until:
      latest_task_status: "completed"

  - id: get_outputs
    name: "获取切片输出"
    action: api_call
    method: GET
    path: /api/slice-tasks/{run_slice.task_id}/outputs
    expect:
      outputs: non_empty

  - id: get_accounts
    name: "获取视频号账号"
    action: api_call
    method: GET
    path: /api/publish/video-accounts
    expect:
      accounts: non_empty

  - id: check_login
    name: "检查登录状态"
    action: api_call
    method: GET
    path: /api/publish/login/status/{get_accounts.accounts[0].id}
    expect:
      state: "ready"
    on_failed: qr_login

  - id: create_publish_task
    name: "创建发布任务"
    action: api_call
    method: POST
    path: /api/publish/tasks
    body:
      output_id: "{{get_outputs.outputs[0].id}}"
      platform: "wechat"
      video_account_id: "{{get_accounts.accounts[0].id}}"
      title: "{{FLOW.VIDEO_TITLE}}"
      require_manual_confirm: false
    expect:
      id: present

  - id: poll_publish
    name: "轮询发布状态"
    action: poll
    path: /api/publish/tasks/{create_publish_task.id}
    interval_sec: 10
    timeout_sec: 600
    until:
      status: "published"
```

---

## 四、已识别的问题与不合理的流程

> 以下问题在梳理流程时发现。**标注 ✅已修复 的项已在 PR #177 编码落地**，可直接在测试报告中验证；其余为既有设计/安全取舍/文档建议，无需改码。

### ✅ P0-1：`/api/wechat-dl/tasks/{id}/import-to-project` 的响应缺少 HTTP 状态码

**状态**：✅ **已修复**（PR #177，补 `status_code=201`）

**问题描述**：该端点成功时返回 `200`，但 `POST` 创建类操作应返回 `201`。

**影响**：低，但不符合 RESTful 规范，可能导致自动化工具的状态码断言不准确。

**位置**：`backend/wechat_download/api.py` → `import_task_to_project`

---

### ✅ P0-2：`/api/wechat-dl/tasks/{id}/to-slice` 创建切片任务时 `subtitle_align_mask` 硬编码为 `true`

**状态**：✅ **已修复**（PR #177，暴露为请求参数，默认 True）

**问题描述**：`to_slice` 端点在创建 `SliceTask` 时，将 `subtitle_align_mask` 硬编码为 `true`，没有暴露为请求参数。

**影响**：用户无法控制该配置，且与主切片入口（`POST /api/episodes/{id}/slice/run`）行为不一致。主入口该字段默认也是 `true`，但用户可覆盖。

**位置**：`backend/wechat_download/api.py` → `to_slice`

---

### ✅ P1-1：选点候选为空时，AI 选点不报错但切片会静默回退为整片切片

**状态**：✅ **已修复**（PR #177，新增 `allow_fallback_whole_video`，置 false 时空候选明确 400）

**问题描述**：当 `auto_accept_all=true` 但候选片段列表为空时，`run_slice` 端点会**静默回退为整片切片**，输出一整段视频，而不是报错或提示。

**影响**：自动化流程会得到一个"看似成功"的结果，但输出可能是全长视频（不符合切片预期）。这会导致后续发布的内容长度不符预期。

**位置**：`backend/app/api/slice.py` → `run_slice` → fallback 逻辑

---

### P1-2：发布任务创建后立即轮询可能拿到过期状态

**状态**：🔵 **已覆盖**（发布任务响应自带 `created_at`，自动化可直接据此判超时）

**问题描述**：`POST /api/publish/tasks` 返回 `status: "pending"` 后，Celery worker 可能尚未启动，但客户端开始轮询。如果 worker 消费失败或任务被丢弃，客户端可能长时间停在 `pending`，无超时提示。

**影响**：自动化流程需要额外的超时兜底，否则可能永远卡住。

**建议**：发布任务 API 增加 `created_at` 字段的时间戳，自动化工具可根据时间戳判断是否超时。

---

### P1-3：`require_manual_confirm` 是硬编码的流程阻断点

**状态**：🟡 **安全设计保留**（默认 `true` 是发布前人工确认的护栏，不宜默认放开；全自动须显式传 `false`）

**问题描述**：发布任务的 `require_manual_confirm` 字段默认为 `true`（见 `PublishTaskCreate`），自动化流程必须显式传入 `false` 才能全自动。但许多前端路径默认是 `true`（人工审核），导致自动化流程容易遗漏。

**影响**：自动化流程必须在创建任务时**显式指定** `require_manual_confirm: false`，否则流程会在发布确认处中断。

---

### P1-4：发布截图审核需要额外 API 调用

**状态**：🟡 **设计取舍保留**（全自动设 `require_manual_confirm=false` 即可跳过截图审核）

**问题描述**：当 `require_manual_confirm=true` 时，流程需要额外调用 `GET /api/publish/tasks/{id}/screenshot` 来获取截图，然后需要人类确认。

**影响**：对于全自动场景，这形成了一个人工干预点。需要用户决策：是走全自动（`require_manual_confirm=false`），还是留人工审核环节。

---

### P2-1：下载任务的 `source_type` 字段只是审计用，不影响任何业务逻辑

**状态**：🔵 **既有设计**（代码注释明确"仅审计字段"，允许导入任意素材）

**问题描述**：`source_type`（如 `self_owned`）在创建任务时仅作为审计字段保存，不对下载行为产生任何影响。如果目标是"只允许授权素材"，这个字段没有实现任何校验。

**影响**：低（当前已明确"允许导入任意素材"），但如果未来需要加授权校验，需要补充逻辑。

---

### ✅ P2-2：批量导入创建多个任务，但缺少批量任务状态汇总接口

**状态**：✅ **已修复**（PR #177，`GET /api/wechat-dl/tasks` 新增 `ids` 参数一次拉多任务）

**问题描述**：`POST /api/wechat-dl/import/batch` 返回多个 `task_ids`，但前端需要逐个轮询每个任务的状态，没有提供批量状态查询接口。

**影响**：自动化流程需要逐个轮询，效率低。建议提供 `GET /api/wechat-dl/tasks?ids=xxx,yyy` 或 `POST /api/wechat-dl/tasks/batch-status` 接口。

---

### P2-3：切片任务轮询接口返回的是列表而非单个任务

**状态**：🔵 **已覆盖**（`GET /api/slice-tasks/{id}` 单任务查询已存在，`run_slice` 返回 `task_id` 可直接关联）

**问题描述**：`GET /api/episodes/{id}/slice/tasks` 返回该剧集下所有切片任务（含历史记录）。自动化流程需要自己判断"哪个是最新任务"，容易拿错。

**影响**：自动化脚本需要对响应做额外的过滤逻辑（取 `created_at` 最新的一条）。建议提供 `GET /api/slice-tasks/{id}` 单任务查询（已有，但创建接口返回的 `task_id` 需要正确关联）。

---

### ✅ P2-4：没有统一的"项目级工作流状态"查询接口

**状态**：✅ **已修复**（PR #177，新增 `GET /api/projects/{id}/workflow-status` 聚合接口）

**问题描述**：一个项目下可能有多个剧集，每集有独立的选点/检测/切片状态。当前没有项目级聚合接口，自动化流程需要逐个剧集去查状态。

**影响**：对多集批量处理的自动化流程，需要大量轮询调用，效率低、复杂度高。

**建议**：增加 `GET /api/projects/{id}/workflow-status` 返回项目下所有剧集各阶段状态。

---

### ✅ P3-1：下载任务失败后缺少自动重试机制

**状态**：✅ **已修复**（PR #177，新增可重试瞬态错误自动重试 + 断点续传，不可重试错误保持原行为）

**问题描述**：`wechat_dl` 下载任务失败后（如 provider 限流、链接失效），任务直接标记 `failed`，没有自动重试或降级到其他 provider 的逻辑。

**影响**：自动化流程需要自己处理失败后的重试逻辑，增加了复杂度。

---

### P3-2：切片参数过多，配置复杂

**状态**：📄 **文档建议**（自动化场景优先用批量切片 `POST /api/batch-slice/run`，配置集中在 `slice_config`）

**问题描述**：`SliceRunRequest` 有 40+ 个可选字段（水印、角标、字幕、竖转横、去重、打码等），自动化流程要"完整配置"非常复杂。批量切片配置（`BatchSliceRunRequest.slice_config`）可以一次性配置，但单集切片仍需逐项设置。

**建议**：建议在自动化场景优先使用**批量切片**（`POST /api/batch-slice/run`），将配置集中在 `slice_config` 中一次传入。

---

### ✅ P3-3：多运营者发布时，`operator_id` 的分配逻辑不透明

**状态**：✅ **已修复**（PR #177，未传 `operator_id` 时自动从绑定视频号账号的号主推导落库）

**问题描述**：`PublishTaskCreate` 有 `operator_id` 字段（可选），但自动化流程如果不传，系统会按什么规则自动分配运营者？是否需要先查 `multi-operator` 端点获取运营者列表？

**影响**：自动化流程不清楚该字段的语义，可能需要额外调研。

---

## 五、自动化测试报告模板

> 将以下报告填写完整后，发回给开发团队，由开发团队根据问题清单逐一修复。

### 测试报告模板

```markdown
# 端到端自动化测试报告

> 测试日期：____年__月__日
> 测试环境：□ 生产  □ 测试  □ 本地
> 测试人/Agent：____

---

## 一、测试结果总览

| 序号 | 流程步骤 | 结果 | 耗时 | 备注 |
|------|---------|------|------|------|
| 1 | 登录系统 | □ 通过 □ 失败 | __s | |
| 2 | 资源导入（链接） | □ 通过 □ 失败 | __s | |
| 3 | 资源导入（文件） | □ 通过 □ 失败 | __s | |
| 4 | AI 选点 | □ 通过 □ 失败 | __s | |
| 5 | 区间检测 | □ 通过 □ 失败 | __s | |
| 6 | 切片执行 | □ 通过 □ 失败 | __s | |
| 7 | 切片输出获取 | □ 通过 □ 失败 | __s | |
| 8 | 发布任务创建 | □ 通过 □ 失败 | __s | |
| 9 | 发布轮询 | □ 通过 □ 失败 | __s | |
| 10 | 确认发布 | □ 通过 □ 失败 | __s | |

**总通过率**：__/10

---

## 二、各步骤详细日志

### 步骤 2：资源导入（链接）

- **请求**：`POST /api/wechat-dl/import`
- **请求体**：`{"source_url": "https://...", "source_type": "self_owned"}`
- **响应**：`{"task_id": "...", "status": "pending"}`
- **轮询结果**：
  - 第 1 次查询（5s）：status = parsing
  - 第 2 次查询（10s）：status = downloading
  - 第 3 次查询（15s）：status = completed
- **结论**：□ 通过  □ 失败
- **问题**：___

### 步骤 3：AI 选点

- **请求**：`POST /api/episodes/{id}/autoclip/run`
- **响应**：`{"run_id": "...", "status": "running"}`
- **轮询结果**：
  - 第 1 次查询（10s）：status = running
  - ...
  - 第 N 次查询：status = completed
- **候选片段数**：__个
- **结论**：□ 通过  □ 失败
- **问题**：___

（每步骤同格式）

---

## 三、问题清单（按优先级排序）

### P0 - 阻塞性问题

| 编号 | 问题描述 | 影响 | 复现步骤 | 建议修复方案 |
|------|---------|------|---------|-------------|
| P0-1 | ... | ... | ... | ... |

### P1 - 高优先级

| 编号 | 问题描述 | 影响 | 复现步骤 | 建议修复方案 |
|------|---------|------|---------|-------------|
| P1-1 | ... | ... | ... | ... |

### P2 - 中优先级

| 编号 | 问题描述 | 影响 | 复现步骤 | 建议修复方案 |
|------|---------|------|---------|-------------|
| P2-1 | ... | ... | ... | ... |

### P3 - 低优先级

| 编号 | 问题描述 | 影响 | 复现步骤 | 建议修复方案 |
|------|---------|------|---------|-------------|
| P3-1 | ... | ... | ... | ... |

---

## 四、附：测试数据

- **测试视频链接**：___
- **测试剧集名称**：___
- **切片输出数量**：__个
- **发布目标账号**：___
- **发布结果 URL**：___
```

---

## 六、注意事项与自动化陷阱

### 6.1 Token 有效期

- `access_token` 短期有效（默认 30 分钟），长流程需调用 `POST /api/auth/refresh` 刷新。
- **刷新方式**：刷新走 **HttpOnly Cookie（`refresh_token`）无感刷新**，调用 `POST /api/auth/refresh`（`Authorization: Bearer <access_token>`）即可续期；仅当 Cookie 不可用时才在 body 传 `refresh_token` 兜底。
- **刷新时机**：建议每 20 分钟刷新一次。

### 6.2 异步任务的轮询策略

- **AI 选点**：最长可等 1 小时（ASR + LLM 耗时）
- **区间检测**：最长 30 分钟
- **切片**：最长 2 小时
- **发布**：最长 10 分钟（实际 RPA 操作 2-5 分钟）

### 6.3 数据隔离

- 每个用户只能看到自己创建的项目/素材。
- 自动化流程使用的账号需要拥有足够权限。

### 6.4 多运营者发布注意事项

- 发布前需要确认账号已登录（`GET /api/publish/login/status/{account_id}` 返回 `state == "ready"`）
- 一个账号同一时间只允许 1 个发布任务（`global_inflight_limit` 默认 4，`op_inflight_limit` 默认 1）
- 多个运营者同时发布需要确保配额充足

### 6.5 前端 UI 操作路径（供 Browser-Use 插件参考）

如果使用 Browser-Use 类插件，以下是 UI 操作路径：

| 操作 | 页面路径 | UI 元素 |
|------|---------|---------|
| 登录 | `/login` | 用户名输入框、密码输入框、登录按钮 |
| 资源导入 | `/resource-download` | Tab「链接导入」，URL 输入框，导入按钮 |
| 项目列表 | `/projects` | 项目卡片/表格，新建项目按钮 |
| 剧集详情 | `/episodes/:id` | Tab：选点 / 区间 / 切片 / 成品 |
| AI 选点 | 剧集详情 → 「AI 选点」Tab | 「开始选点」按钮，进度条 |
| 区间检测 | 剧集详情 → 「区间检测」Tab | 「开始检测」按钮 |
| 切片执行 | 剧集详情 → 「切片」Tab | 配置表单 + 「开始切片」按钮 |
| 成品库 | 剧集详情 → 「成品」Tab | 成品列表，预览/下载 |
| 发布管理 | `/publish` | 发布任务列表，新建发布任务按钮 |
| 视频号账号 | `/publish` → 「账号管理」Tab | 账号列表 |
