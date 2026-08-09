# Seedance 模型直连生成 · 提前部署方案

> 文档版本：v1.1 ｜ 提出人：Benny ｜ 状态：**已落地（PR #39）**
>
> 背景：目前「短片制作」的成片生成依赖 **豆包网页端 RPA**（Playwright 打开豆包 → 贴提示词 → 等生成 → 下载成片）。
> 已按本方案**提前落地 Seedance 官方 API 直连通道**，与豆包 RPA 并行、开关控制（默认关闭）。
>
> **落地说明**：
> - 新增 `backend/app/services/ark_client.py`（火山方舟 HTTP 客户端，与豆包 RPA 逻辑完全隔离）；
> - 新增 Celery 任务 `seedance_generate_task`（queue=publish，普通 worker 即可消费，不依赖 rpa_worker）；
> - 新增 4 个后端 API：`GET /shortdrama/seedance/config`、`POST/POST/GET /shortdrama/prompts/{id}/seedance/generate|cancel|status`；
> - 总开关默认**关闭**：`system_config.shortdrama_seedance_config.enabled=false` / 环境变量 `SEEDANCE_ENABLED=false`，未开启时接口返回 403、前端不展示按钮；
> - 前端「提示词生成历史」新增 **Seedance 任务** 状态列与「Seedance 生成」按钮，成片来源以 `gen_channel`（doubao_rpa / seedance_api / manual）追溯；
> - 数据库：Alembic 迁移 `0014_seedance_generate` + 老库兼容迁移兜底。

---

## 一、目标

1. **提前打通官方 API 通道**：在现有「提示词生成 → 出片 → 去水印 → 发布」工作流中，新增 **Seedance 官方 API 直连出片** 通道，与豆包 RPA 并行可切换。
2. **复用现有链路，零改造下游**：生成的成片仍回填 `shortdrama_prompts` 的 `video_*` 字段，下游「一键导入去水印 / 去水印 / 发布」完全复用，无需改动。
3. **为后续模型升级留好接口**：火山方舟后续上线更长时长 / 更高清版本时，只改配置、不动代码即可平滑升级。

---

## 二、现状分析

### 2.1 当前成片生成链路（豆包 RPA）

```
前端 ShortDrama.tsx（① 提示词生成历史，点「一键豆包生成」）
  → POST /api/shortdrama/prompts/{id}/doubao/generate
  → Celery 任务 doubao_generate_task（queue=publish）
  → rpa_worker 容器 Chromium（CDP 9222）打开 https://www.doubao.com/chat/
  → 检测登录（扫码）/ 贴提示词 / 等生成 / 被拒改写确认
  → 下载成片 → 上传 MinIO(watermark-raw) → 回填 video_* 字段
```

**痛点**：
- 依赖浏览器自动化：页面改版即挂、选择器维护成本高；
- 需要**扫码登录**（Cookie 落盘），多实例 / 无人值守难；
- 有**风控**（随机延迟、请求频率受限）；
- 被拒时进入「改写确认」人工环节，无法全自动；
- 长耗时：一次生成 3~10 分钟，且失败率高。

### 2.2 可复用的资产

| 资产 | 说明 | 复用方式 |
|------|------|---------|
| `ShortdramaPrompt` 表 + `video_*` 字段 | 成片回填、预览、导入去水印 | 直接复用，新增 `seedance_*` 字段并存 |
| MinIO `watermark-raw` 桶 | 成片存储 | 直接复用 |
| Celery `publish` 队列 | 任务异步调度 | 复用或新增 `seedance` 队列 |
| 前端历史操作列（fixed right） | 按钮区 | 新增「Seedance 生成」按钮 |
| `_sync_doubao_video()` | 下载成片→上传 MinIO→回填 | 抽象成通用 `_sync_generated_video()` |

---

## 三、Seedance 官方 API 能力与限制

Seedance 由字节跳动提供，通过**火山方舟（Volcano Ark）**开放平台以 HTTP API 调用，与现有阿里百炼 DashScope 是两个独立平台，需单独开通与 Key。

### 3.1 核心 API（HTTP 直连，无需浏览器）

| 操作 | 方法 & 路径 |
|------|-------------|
| 创建生成任务 | `POST {ARK_BASE}/contents/generations/tasks` |
| 查询任务状态 | `GET  {ARK_BASE}/contents/generations/tasks/{task_id}` |
| 取消任务 | `POST {ARK_BASE}/contents/generations/tasks/{task_id}/cancel` |

> ARK_BASE = `https://ark.cn-beijing.volces.com/api/v3`
> 认证：`Authorization: Bearer ${ARK_API_KEY}`

### 3.2 创建任务请求体（关键字段）

```json
{
  "model": "seedance-1-0-pro-250528",
  "content": [
    { "type": "text", "text": "<长/短/AI 提示词>" }
  ],
  "resolution": "1080p",
  "duration": "10s",
  "watermark": true,
  "fps": 24,
  "seed": 0
}
```

### 3.3 ⚠️ 关键限制（决定方案形态）

| 限制项 | Seedance 1.0（当前） | 影响 |
|--------|---------------------|------|
| **时长** | 仅支持 **5s / 10s** | 提示词支持 10/15/20/25/30s/自定义 → 需「截断/拆段/提示」策略 |
| 分辨率 | 480p / 720p / 1080p | 满足 9:16 竖屏，1080p 足够 |
| 计费 | 按**生成秒数**计费（以官方定价为准） | 成本可预估 |
| 异步 | 创建后轮询，单任务约 1~5 分钟 | 与现有 Celery 轮询模型完全契合 |

> 时长是最大约束：**Seedance 1.0 只出 10s**。方案内置两种策略（见 5.5），后续 Seedance 1.5+/2.x 支持更长时长时，仅需换 `model` 配置。

---

## 四、总体架构（新增部分）

```
前端 ShortDrama.tsx（① 提示词生成历史，点「Seedance 生成」）
  │
  ▼
后端 FastAPI：POST /api/shortdrama/prompts/{id}/seedance/generate   ← 新增
  │
  ▼
Celery 任务 seedance_generate_task（queue=seedance，可放 publish）  ← 新增
  │
  ├─▶ 火山方舟 Ark API（HTTP 直连，无浏览器）
  │     POST   contents/generations/tasks        → 创建任务，拿 task_id
  │     GET    contents/generations/tasks/{id}   → 轮询（queued/running/succeeded/failed）
  │     POST   contents/generations/tasks/{id}/cancel（取消时）
  │
  ├─▶ 成功后拿 video_url → 下载成片
  │
  └─▶ 上传 MinIO(watermark-raw) → 回填 seedance_* + video_* 字段
        ↓
  下游完全复用：成片预览 / 一键导入去水印 / 发布素材（零改动）
```

---

## 五、详细设计

### 5.1 新增配置（.env / docker-compose）

```env
# ==================== Seedance 直连（火山方舟）====================
# 火山方舟 API Key（https://console.volcengine.com/ark）
SEEDANCE_API_KEY=
# 模型名或推理接入点 ID（ep-xxx）。Seedance 1.0 仅支持 5s/10s
SEEDANCE_MODEL=seedance-1-0-pro-250528
# API Base（默认即可）
SEEDANCE_API_BASE=https://ark.cn-beijing.volces.com/api/v3
# 出片分辨率：480p / 720p / 1080p
SEEDANCE_RESOLUTION=1080p
# 是否加水印（建议 true，避免被平台判搬运）
SEEDANCE_WATERMARK=true
# 生成超时（秒）
SEEDANCE_TIMEOUT=600
# 时长超 10s 的处理策略：truncate(截成10s) / block(拒绝并提示) / split(拆段, 二期)
SEEDANCE_LONG_DURATION_POLICY=truncate
# 独立队列（可与 publish 合并）
SEEDANCE_CELERY_QUEUE=seedance
```

### 5.2 数据库（Alembic 迁移 0013）

`shortdrama_prompts` 表**新增并行字段**（与豆包 RPA 字段并存，互不干扰）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `seedance_status` | String(50) | none / pending / running / completed / failed / cancelled |
| `seedance_task_id` | String(100) | 火山方舟任务 id（cgt-xxx） |
| `seedance_message` | Text | 实时进度/消息 |
| `seedance_error_message` | Text | 失败原因 |
| `seedance_resolution` | String(20) | 本次生成分辨率 |
| `gen_channel` | String(20) | 记录成片来源：doubao_rpa / seedance_api（便于追溯） |

> 成片仍写回 `video_file_*` / `video_status` 字段，下游零感知。

### 5.3 后端 API（backend/app/api/shortdrama.py）

| 接口 | 说明 |
|------|------|
| `POST /shortdrama/prompts/{id}/seedance/generate` | 启动直连生成（校验无进行中任务 → 置 pending → 派发 Celery） |
| `GET  /shortdrama/prompts/{id}/seedance/status` | 返回 seedance_* + video_* 状态（供前端轮询） |
| `POST /shortdrama/prompts/{id}/seedance/cancel` | 取消（调方舟 cancel API + 置 cancelled） |
| `GET  /shortdrama/seedance/config` | 返回模型/时长能力/分辨率/是否已配 Key |

### 5.4 Celery 任务 seedance_generate_task

```
状态机：pending → running → completed / failed / cancelled

1. 加载记录，校验无进行中任务
2. 组装提示词：AI 提示词优先；若 AI 为空回退 prompt_text
3. 时长策略（SEEDANCE_LONG_DURATION_POLICY）：
   - truncate：duration > 10s → 按 10s 生成，并在 message 提示「已按 10s 生成」
   - block：拒绝并提示「Seedance 1.0 仅支持 10s，请用豆包 RPA 或缩短时长」
4. 调方舟 API 创建任务 → 拿 task_id
5. 轮询（每 5s，指数退避）：
   - queued → running → succeeded / failed
   - 更新 seedance_message 进度
6. succeeded：拿 video_url → 下载 → 上传 MinIO(watermark-raw)
   → 回填 video_* + seedance_status=completed + gen_channel=seedance_api
7. failed：记录 seedance_error_message，指数退避重试 3 次
8. 异常兜底：超时/网络错误 → failed + 可重试
```

**取消**：任务中收到取消标记 → 调 `tasks/{id}/cancel`，清理临时文件。

### 5.5 前端（ShortDrama.tsx）

- 历史操作列（已 fixed right）在「一键豆包生成」旁新增 **「Seedance 生成」** 按钮（绿色，标记"官方API"），更醒目、优先推荐；
- 生成中显示状态 Tag（轮询 `/seedance/status`），失败显示「重试」；
- 生成成功自动刷新成片预览（复用现有 video 预览逻辑）；
- ① 提示词生成卡片顶部增加「生成通道」说明：`Seedance API 直连（10s 内）/ 豆包 RPA（免费/包月，最长 30s）`，引导用户按时长选择；
- 时长 >10s 时，Seedance 按钮 hover 提示「Seedance 1.0 仅支持 10s，将按 10s 生成或改用豆包」。

### 5.6 与豆包 RPA 的并行策略

| 维度 | Seedance API 直连 | 豆包 RPA（现状） |
|------|------------------|-----------------|
| 稳定性 | ★★★★★（官方 API） | ★★（页面改版/风控） |
| 人工介入 | 无（全自动） | 需扫码、被拒需确认改写 |
| 时长 | ≤10s（1.0 版本） | free≤10s / pro≤30s |
| 成本 | 按量付费 | 免费/包月额度 |
| 适用 | 10s 内短视频、规模化、无人值守 | 长时长、有会员、临时 |

**建议**：两通道**并行保留**。前端按时长智能推荐；后续 Seedance 支持更长时长后，豆包 RPA 逐步降级为兜底通道。

---

## 六、成本与配额（预估）

- Seedance 1.0 按生成秒数计费（约 **¥0.03/秒** 量级，**以火山方舟官方定价为准**）；
- 一条 10s 视频 ≈ **¥0.3** 上下；
- 建议在 `system_config` 增加**日配额/月配额**（如每日 50 条），前端展示已用配额，避免超支；
- 方舟控制台可设置**预算告警**，上线前建议开启。

---

## 七、部署步骤（实施阶段）

1. **火山方舟**：开通 Seedance 模型、创建 API Key、确认模型 ID / 推理接入点（可选创建 `ep-xxx`）。
2. **配置**：`.env` 增加 5.1 节配置项；`docker-compose.yml` 的 backend/worker 注入 `SEEDANCE_*` 环境变量。
3. **数据库**：新增 Alembic 迁移 `0013_seedance_generate`（5.2 字段）+ `init.sql` + 老库兼容迁移兜底。
4. **后端**：新增 5.3 四个 API + 5.4 Celery 任务；注册到 `celery_app`（queue=seedance 或 publish）；`_sync_doubao_video` 抽象复用。
5. **前端**：5.5 按钮与状态展示；`shortdrama.ts` 新增 4 个 API 封装。
6. **验证**：Python 语法编译 + `tsc && vite build`；用一条真实 Key 走通「提示词 → 直连生成 → 成片回填 → 一键导入去水印」全链路。
7. **上线**：`docker compose build backend worker && up -d`，执行 `alembic upgrade head`。

---

## 八、风险与对策

| 风险 | 对策 |
|------|------|
| Seedance 1.0 仅 10s，与多时长提示词冲突 | 内置 truncate / block 策略 + 前端引导；长时长走豆包 RPA |
| API Key 泄露 | 仅存后端环境变量；前端只读"是否已配置"，不展示 Key |
| 计费失控 | system_config 日/月配额 + 方舟预算告警 |
| 方舟接口字段随版本变化 | 封装 `ark_client.py` 单点适配，其余代码不感知 |
| 并发过高排队 | Celery 独立 `seedance` 队列 + worker 并发控制 |
| 生成失败率 | 指数退避重试 3 次 + 失败原因落库 + 前端一键重试 |
| 合规（代称/侵权） | 生成用提示词已含合规约束；成片仍需人工抽检 |

---

## 九、演进路线

```
Phase 1（本次方案）：Seedance API 直连 10s 出片，与豆包 RPA 并行
Phase 2：长时长支持（Seedance 新版本 / 多段拼接 + 音频对齐）
Phase 3：批量生成流水线（一次多提示词排队出片，配额管理）
Phase 4：图生视频 / 首帧图生（方舟 content 支持 image_url）
Phase 5：成片自动抽帧审核 + 合规检查后直接进入去水印
```

---

## 十、结论

**建议提前部署。** 理由：

1. **打通通道成本低**：现有 Celery + MinIO + 提示词链路已完备，Seedance 直连只是"把 RPA 环节换成 HTTP 调用"，增量改动小（约 4 API + 1 Celery 任务 + 1 前端按钮）。
2. **稳定性收益大**：摆脱扫码、风控、页面改版，为规模化无人值守出片打基础。
3. **前瞻性**：方舟后续版本（更长时长/更高清/图生）上线时，只需改 `SEEDANCE_MODEL` 与 `ark_client.py`，即插即用。
4. **与豆包 RPA 互补不冲突**：10s 内直连优先，长时长/会员场景保留 RPA，双通道随时切换。

> 唯一硬约束是 **Seedance 1.0 只支持 10s**，方案已内置策略化解；若业务必须 >10s，可先只部署"通道 + 配置"，等官方长时长版本发布后再放开。
