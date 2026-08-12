# 鉴权与安全盲区复核报告

> 复核基线：`34a88cd`（2026-08-12，main）｜ 复核人：CodeBuddy
> 目的：对 `docs/reviews/CODE_REVIEW_REPORT.md`（08-10 基线）遗留的高危/中危项做**逐项复核**，确认当前代码是否已修复，避免误信过时结论。

---

## 一、结论速览

| 原报告项 | 原结论 | 现状 | 说明 |
|---------|--------|------|------|
| **H2** · 100 端点零鉴权 | 高危 | ✅ **已修复** | `main.py:197` 业务路由统一 `dependencies=[Depends(get_current_user)]`；auth/worker 回调走独立 router 各自鉴权 |
| **H1** · CDP 9222 公网暴露 | 高危 | ✅ **已修复** | `docker-compose.yml` rpa_worker 已删除 `ports` 映射，仅经 `clip-network` 内网访问 |
| **H3** · 种子弱口令 | 高危 | ✅ **已修复** | `main.py:_create_seed_users()` 仅 `DEBUG` 环境执行，且口令来自 `SEED_USERS_JSON`，无硬编码默认值 |
| **H4** · JWT/Cookie 密钥默认值 | 高危 | ✅ **已修复** | `config.py` `JWT_SECRET` 必填且 `field_validator` 拒绝占位/默认值；`COOKIE_ENCRYPT_KEY` 与 JWT 分离且自动生成落盘 |
| **全库 0 索引** | 高危 | ✅ **已修复** | `init.sql:273` 错误语句已删除；新增 `migrations/fix_missing_indexes.sql` 存量补丁；Alembic 22 个迁移 |
| **P2** · 单 worker 串行吞 4 队列 | 中危 | ✅ **已修复** | 已拆分为 `worker-video` / `worker-publish` / `worker-fast`（分别消费 `video_processing`/`publish`/`metrics,default`） |
| **H5/H6** · MinIO/Redis 暴露 | 中危 | ⚠️ **部分保留（有密码）** | 保留 `0.0.0.0` 供远程 slice-worker 跨机访问，但均需密码；建议如无需远程节点可收紧到内网 |
| **M4** · WebSocket 无鉴权 | 中危 | ⚠️ **未修复（低风险）** | `/ws/progress/{task_id}` 仍无鉴权，仅暴露任务进度，不涉数据/操作；建议后续按需加 token |
| **L4** · monitor 健康端点 | 中危 | ✅ **已修复** | monitor 整体已纳入 `get_current_user` 保护 |

---

## 二、当前鉴权拓扑（实测 `main.py`）

```
main.py
├── 17 个业务 router（projects/upload/autoclip/intervals/slice/preview/
│     publications/config/publish/dashboard/workers/monitor/maintenance/
│     watermark/shortdrama/publish_material/batch_slice）
│      └─ include_router(prefix="/api", dependencies=[Depends(get_current_user)])   ← 统一用户 JWT 鉴权
├── auth.router（prefix="/api/auth"）→ 各自内部鉴权
│      ├─ login / refresh / register → 开放（设计如此；register 现限 admin）
│      └─ logout / me / profile / users* → get_current_user / require_roles(admin)
├── slice.worker_router（prefix="/api"）→ 供 Go slice-worker 回调
│      └─ X-Worker-Token 鉴权（_verify_worker_token：每任务随机 token + TTL + compare_digest
│          + basename/path 前缀锁定）
├── workers.internal_router（prefix="/api"）→ 供 Worker 心跳/管理
│      └─ 管理端点 require_roles(admin)；⚠️ heartbeat 无 Token（见下）
├── GET /api/health、/api/health/detailed → 开放（Docker healthcheck / 外部探活）
└── WS /ws/progress/{task_id} → 开放（仅进度，无鉴权）
```

### 2.1 业务 router 全端点覆盖核对

由于 17 个业务 router 在 `include_router` 时整体挂了 `Depends(get_current_user)`，其**内部所有端点均被 JWT 保护**，逐模块核对结果如下：

| 模块 | 端点数 | 鉴权 | 说明 |
|------|-------|------|------|
| projects / upload / autoclip / intervals / preview / publications / config / publish / dashboard / workers / monitor / maintenance / watermark / shortdrama / publish_material / batch_slice / slice（主 router） | 全部 | ✅ 统一 JWT | `main.py:197` 统一接线 |

### 2.2 需人工鉴权/开放端点清单

| 端点 | 鉴权方式 | 判定 |
|------|---------|------|
| `POST /api/auth/login` | 开放（用户名+密码） | ✅ 设计如此 |
| `POST /api/auth/refresh` | 开放（refresh cookie + jti 会话校验） | ✅ 设计如此 |
| `POST /api/auth/register` | `require_roles(admin)` | ✅ 已收紧为仅管理员 |
| `POST /api/slice-tasks/{id}/upload-url` | X-Worker-Token | ✅ |
| `POST /api/slice-tasks/{id}/callback` | X-Worker-Token | ✅ |
| `POST /api/slice-tasks/{id}/progress` | X-Worker-Token | ✅ |
| `POST /api/workers/heartbeat` | **无 Token** | ⚠️ 遗留，见 §三 |
| `GET /api/health`、`/api/health/detailed` | 开放 | ✅ Docker healthcheck 需要 |
| `WS /ws/progress/{task_id}` | 开放 | ⚠️ 低风险，见 §三 |

---

## 三、仍待关注的低风险遗留项（非阻塞）

### 3.1 `POST /api/workers/heartbeat` 无 Token 校验（低风险）
- **现状**：`workers.py:107` 的 `internal_router` heartbeat 端点无任何 Token 校验，任何人可伪造节点心跳/状态写入 DB。
- **影响**：仅能伪造 `worker_node` 表节点状态（制造假节点），**不能**直接派发任务或读写业务数据。真正的任务下发走 `slice.worker_router`（X-Worker-Token 保护）。
- **建议**（可选）：为 heartbeat 增加共享 `WORKER_TOKEN`（环境变量）校验，或校验来源 IP 为内网网段。
- **是否阻塞**：❌ 否。当前不构成可利用的数据/操作风险。

### 3.2 `WS /ws/progress/{task_id}` 无鉴权（低风险）
- **现状**：`main.py:158` WebSocket 仅凭 `task_id` 即可订阅进度。
- **影响**：可被未授权者监听已知 task_id 的进度消息（进度数值/消息文本），不泄露账号、密钥或源数据。
- **建议**（可选）：在 WS query 中附加短期 token（随任务创建签发）校验。
- **是否阻塞**：❌ 否。

---

## 四、结论

- **08-10 审查报告中所有高危项（H1~H4、全库 0 索引）均已修复并核实。**
- 中危项中「单 worker 串行」「monitor 健康端点泄露」已修复；「MinIO/Redis 暴露」为远程节点所需（有密码）；「WebSocket 无鉴权」与「heartbeat 无 Token」为**低风险遗留**，建议后续按需优化，**不阻塞**本期发布。
- **`docs/reviews/CODE_REVIEW_REPORT.md` / `FIX_PLAN.md` 中「100 端点零鉴权」「CDP 9222 暴露」「种子弱口令」「单 worker 串行」等过时结论请勿再引用**，以本报告为准。
