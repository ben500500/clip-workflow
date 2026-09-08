# clip-workflow 整体代码评审报告（2026-09-08）

> 评审对象：`clip-workflow` 全仓库（短剧切片投放工作流）
> 评审基线：`f3d828a`（feat: 剧场列表读接口全员可见）
> 评审方式：三路并行只读静态评审（① API/RBAC 层 ② 异步任务链/服务层 ③ 前端/部署配置），全部结论带 `file:line` 证据，均经亲自读码核实
> 前置参考：`docs/reviews/CODE_REVIEW_REPORT.md`（08-10 基线）、`docs/reviews/AUTH_AUDIT.md`（08-12 CodeBuddy 复核）
> 同步发布：cnb issue（@codebuddy 召集专家讨论）

---

## 0. 总览

| 分区 | 高危 | 中危 | 低危 | 小计 |
|---|---|---|---|---|
| ① API / RBAC 层 | 5 | 9 | 5 | 19 |
| ② 异步任务链 / 服务层 | 3 | 13 | 4 | 20 |
| ③ 前端 / 部署配置 | 5 | 10 | 5 | 20 |
| **合计** | **13** | **32** | **14** | **59** |

**一句话结论**：架构骨架健康（统一 JWT 保护、分布式锁、回调幂等、迁移有 downgrade），但三类系统性短板突出 —— **① 对客户端输入过度信任**（任意本地 path 可致任意文件读/删、operator_id 可伪造、配置接口明文回显密钥）；**② 跨进程顺序假设脆弱**（beat 非原子 claim、acks_late 无 visibility_timeout、finally 误删源文件，均可在正常并发下触发双跑/丢数据）；**③ 部署面密钥失守**（JWT_SECRET 占位值入库 + 弱口令 + 生产 compose 对 postgres/backend 绑 0.0.0.0，构成「仓库泄露→生产沦陷」完整链路）。

**与 08-12 审计对照（遗留未修，本次全部确认仍在）**：

| 遗留项 | 现状 |
|---|---|
| `/api/workers/heartbeat` 无 token | ❌ 仍在（workers.py:127） |
| WS `/ws/progress` 无鉴权 | ❌ 仍在，且**新增** `/ws/wechat-dl`、`/ws/lan-source` 两处（main.py:153-191） |
| autoclip 内存态 projects dict 重启丢进度 | ❌ 仍在（autoclip/app/main.py:82） |
| alembic 失败被 `\|\| echo` 吞掉 | ❌ local compose 仍在（docker-compose.local.yml:16），deploy/ 版已修但两版不一致 |
| compat 硬编码 ADD COLUMN | ❌ 仍在且增长至 40+ 条（database.py:208-296） |

---

## ① API / RBAC 层（19 条）

### 高危

1. **`backend/app/api/batch_slice.py:46` + `backend/app/celery/tasks.py:167,886` — 客户端任意本地路径 → 任意文件读取与删除**。`BatchEpisodeItem.path` 为任意字符串直接落库，worker 端 `_ensure_source_video` 用 `os.path.isfile()` 直接采用，批次默认 `auto_delete_source=True` 处理完 `os.unlink` —— 登录用户可让服务器读取并删除任意可写文件（含配置/密钥）。建议：path 限制在专用白名单目录内做 realpath 前缀校验，删除动作同样校验。
2. **`backend/app/api/slice.py:484-503` — `/episodes/{id}/slice/run` 的 `video_path` 同类路径穿越**。直接探测客户端路径且 400 消息回显「文件不存在」，可作任意文件存在性 oracle。建议与 batch-slice 收敛为同一白名单校验函数。
3. **`backend/app/api/config.py:349-355,372-431` — 系统配置接口无角色限制且敏感键明文回显**。`llm_api_key`、`dupload app_secret`、`auth_headers` 任何登录 operator 均可读取与篡改。建议：配置读写限 admin，序列化对敏感键掩码。
4. **`backend/app/api/workers.py:127` — 心跳接口无 token（08-12 遗留未修）**。未认证者可伪造 worker 节点注册/状态/容量干扰调度。建议复用 `_verify_worker_token`（slice_helpers.py:1673 已有现成实现）。
5. **`backend/app/api/dramas.py:1010-1018` — 导入确认日志泄漏网盘提取码 + ValidationError 变 500**。`logger.info` 打印完整请求体（含 `material_link_pwd`）；解析失败直接 500。建议删请求体级日志、显式转 422。

### 中危

6. **`backend/app/main.py:153-191,268-271` — 无鉴权暴露面扩大**。新增 `/ws/wechat-dl/{task_id}`、`/ws/lan-source/{task_id}` 均无鉴权且每连接新建 Redis 连接；`/api/health/detailed` 暴露 DB/Redis/MinIO/磁盘细节。建议 WS 握手校验 JWT，health/detailed 挂鉴权或限内网。
7. **`backend/app/api/shortdrama.py:419-475` — 提示词记录无归属隔离**。模型无 `created_by`，任何用户可遍历/删除他人提示词及成片。建议补 `created_by` 并按数据范围过滤。
8. **`backend/app/api/publish_tasks.py:120-134,404-441` — 发布任务创建不校验 output 归属、列表无分页**。operator 可借他人 `output_id` 创建发布任务。建议按 output→task→episode→project 链路校验访问权。
9. **`backend/app/api/projects.py:630,692,729,762`、`api/preview.py:55` — 孤儿记录跳过数据隔离**。`if proj and not _check_project_access(...)` 在项目已删而 episode/output 残留时短路放行。建议 proj 为空直接 404。
10. **`backend/app/api/dramas.py:439`、`api/theaters.py:130` — `operator_id` 由客户端指定可伪造归属**。operator 可把剧目/剧场归属到他人名下；导入自动建剧场（dramas.py:786-808）也绕过剧场写权限。建议服务端强制 `operator_id = current_user.id`（仅 admin 可代指）。
11. **`backend/app/api/dashboard.py:478,490,502,583,595,604` — 看板指标导入类写接口无角色限制**。任何角色可导入/覆盖全量营收与跑量指标。建议限 admin/publisher。
12. **`backend/app/api/publish_login_qr.py:243-267` — 扫码回调可伪造登录态**。不校验当前账号是否 logging 状态与回调者身份，任意用户可对任意 account_id 直接置 ready。建议校验 Redis login_state 与 claim 的 operator 一致。
13. **`backend/app/api/shortdrama.py:970-990` — 任意用户可清除全局共享豆包登录态**（672-701 全局模板同理可改）。建议此类全局资源操作限 admin。
14. **`backend/app/api/dramas.py:437`、`api/auth.py:426-427` — 未捕获 UUID 解析 → 500**。建议统一走带 400 转换的 `_parse_uuid`。
15. **`backend/app/api/auth.py:143` — refresh cookie 硬编码 `secure=False`**。7 天有效期 Cookie 永不带 Secure。建议按环境决定 `secure=True`。

### 低危

16. **`backend/app/api/dramas.py:330-394,524-603`、`api/batch_slice.py:295-376` — 列表无分页 + presigned URL N+1**。数据量增长后延迟线性恶化。建议分页 + 批量预签名。
17. **`backend/app/api/channel_accounts.py:684-688` — 越权返回 403 与全站 404 防枚举语义不一致**。建议统一 404。
18. **`backend/app/api/watermark.py:391-402` — `file_keys` 未校验归属**。可把他人上传的源视频纳入自己任务。建议上传时登记 key→owner 映射。
19. **`backend/app/api/dramas.py:1341-1356` — 剧集批量绑定中途 commit 且解绑不校验归属**，失败产生半提交。建议解绑加归属过滤并单事务。
20. （并入 16 计）胖 API 层延续 08-10 结论：slice.py 60 次 DB 直操、publish.py 60 次、dashboard.py 50 次，service 层形同虚设。

### 09-08 放开决策（剧目库/剧场读全员可见）复核

- ✅ dramas.py / theaters.py 读接口（列表/详情/切片状态）已彻底放开，写操作 `_can_manage`/`_check_access` 完整保留；
- ⚠️ 配套边界需要跟上：第 10 条（operator_id 客户端可指定）在「读放开」后风险放大 —— 任何人可把记录归属写到他人名下，建议尽快收紧为服务端强制；
- ⚠️ material 角色前端无剧目库菜单入口（见 ③-15），前后端口径未同步。

---

## ② 异步任务链 / 服务层（20 条）

### 高危

1. **`backend/app/services/batch_decoupled_service.py:274-342` — dispatch_ready_slices 非原子 claim**。先 SELECT 后关闭会话，无锁循环内做长耗时区间检测等待后才置 `phase=slicing`，下一 beat 周期 `batch_slice_dispatch`（celery/tasks.py:344-355 无锁）会重复投递同一批。建议改 `UPDATE ... WHERE phase='ready_slice'` 原子抢占并检查 rowcount。
2. **`backend/app/celery/tasks.py:35` — `task_acks_late=True` 未配 `visibility_timeout`**。Redis broker 默认 3600s，切片 ffmpeg 超时恰为 3600s（engines/slice.py:733），seedance/去水印更长，超时未 ack 即被重投另一 worker 双跑。建议显式配置 visibility_timeout > 最长任务，或超长任务独立队列+心跳续期。
3. **`backend/app/celery/tasks.py:167-168,204-207,300-305` — finally 无条件 unlink 误删调用方原始源文件**。`_ensure_source_video` 对已存在本地路径原样返回，finally 直接删除 —— autoclip 以本地文件触发时删的是用户原始素材。建议仅对 `/tmp/source_videos/` 前缀的下载副本清理。

### 中危

4. **`backend/app/api/slice.py:824-827,1176-1217` — run_slice 同剧集防重缺失**，重复点击/并发双跑互相覆盖候选。建议按 `episode_id` 条件更新或分布式锁去重。
5. **`slice-worker/task_executor.go:199-230` — Go worker 字幕 bold 透传丢失（确认仍在）**。后端已下发 `cfg["bold"]`（slice_helpers.py:813-814、1242），Go 端逐字段提取无 bold 分支，粗体静默失效。建议补 `--subtitle-bold` 透传。
6. **`autoclip/app/main.py:82-83,897-904` — 内存态 projects dict 重启丢进度（历史问题仍在）**，且 `WORKER_CONCURRENCY>1` 时多进程各自持有 dict，请求打到非创建进程即 404。建议落 Redis/DB 或强制单 worker。
7. **`backend/app/celery/remotion_tasks.py:79-81` — "rendering" 状态 flush 后未 commit，会话关闭即回滚**，`:152-174` 僵死恢复任务按该状态扫描永远匹配不到。建议该状态变更单独 commit。
8. **`docker-compose.local.yml:16` — alembic 失败被 `|| echo` 吞掉（仍在）**；根 `docker-compose.yml:283` stamp 同类；`deploy/docker-compose.yml:236` 已修但两版不一致。建议统一失败即退出。
9. **`backend/app/database.py:208-296` — compat 迁移 40+ 条硬编码 ADD COLUMN（仍在）**，与 alembic 双轨漂移。建议收敛进 alembic，compat 只留兜底白名单。
10. **`backend/app/services/publish_service.py:74,97-131,207,477-489` — Playwright tab 泄漏 + `_PENDING_TABS` 无 TTL**。只 `browser.close()` 断 CDP，page 永留常驻 Chromium；旧 tab 释放 fire-and-forget。建议关 page 后再断连，缓存加 TTL 同步等待。
11. **`autoclip/app/main.py:383-399,519-526` — `_run_pipeline` 全局 os.environ 快照/恢复**，并发运行互相污染（A 的恢复抽掉 B 的配置）。建议改显式参数传递。
12. **`backend/app/services/batch_slice_service.py:235,241,300,306` — async 函数内阻塞 `time.sleep()`**，周期性冻结整个事件循环。建议 `await asyncio.sleep()`。
13. **`backend/app/engines/watermark_runner.py:45-49,119-125`、`services/remotion_renderer.py:217-228` — 子进程超时裸 kill 不杀进程树**，remotion 的 node/Chromium 全成孤儿。建议复用 slice_service.py:26,73-92 的进程组终止封装。
14. **渲染/变体临时产物只增不删**：`celery/remotion_tasks.py:94-111`、`services/variant_service.py:543,584-622` 失败/重试路径不清理，磁盘持续堆积。建议上传成功即删 + 定时清扫。
15. **`backend/app/celery/shortdrama_tasks.py:136-140,546-550` — 整视频 `resp.content` 读入内存**，并发 OOM 风险。建议流式 `iter_content` 落盘。
16. **`backend/app/celery/tasks.py:2533-2540` — watermark 进度回写 fire-and-forget**，异常无人消费且用弃用的 `asyncio.get_event_loop()`。建议保存 task 引用记录异常。

### 低危

17. **`backend/app/celery/variant_tasks.py:58-67` — 重试路径未重新获锁**，与手动触发并发可能双跑同一 output。
18. **`backend/app/services/publish_service.py:742-744,805-812` — 硬编码桶名 `"raw-footage"`** 应为 `settings.MINIO_BUCKET_RAW`；截图/封面临时文件从不清理。
19. **`backend/app/api/slice.py:1103-1173` — regenerate 死角仅补丁式修复**，「删旧候选」应延后到新候选成功落库之后。
20. **`backend/app/services/fingerprint_service.py:109-127` — Popen 超时不 kill 泄漏 ffmpeg**；`engines/slice.py:4617` concat 的 `subprocess.run` 无 timeout。

### 任务链整体评价

分布式锁（SET NX + Lua 比对删除）、切片回调幂等（终态去重 + file_key 去重 + 进度单调）、slice_service 进程组终止等基础件是过硬的。短板集中在「跨进程边界的顺序假设」：高危 1-3 都能在正常负载并发下触发任务双跑或数据丢失，应最优先修复。状态机存在「写状态不提交」这类低级但后果严重的缺陷（remotion 僵死恢复形同虚设）。资源治理（Playwright tab、临时文件、孤儿进程）普遍缺生命周期终点，适合引入统一清理守护。

---

## ③ 前端 / 部署配置（20 条）

### 高危

1. **`deploy/env.deploy:16,164` — `SECRET_KEY` 与 `JWT_SECRET` 均为同一占位 UUID 且已提交仓库**。任何能读仓库者可离线伪造任意角色（含 admin）JWT。建议立即轮换随机高强度密钥，仓库只留 `.template`，真实 env 移出版本控制。
2. **`deploy/env.deploy:21,27,37,51` — 弱口令明文入库**：`admin/admin123`、`POSTGRES_PASSWORD=123456`、`REDIS_PASSWORD=123456`、`MINIO_ROOT_PASSWORD=minioadmin123456`。建议首部署强制改密，启动时拒绝默认弱口令。
3. **`deploy/docker-compose.yml:82,244` — 生产 compose 中 postgres（12543）与 backend（12808）绑 `0.0.0.0`**（根 compose 同类服务均 127.0.0.1）。二者无远程访问需求。建议改回 loopback 或删映射。
4. **`frontend/src/components/AuthGuard.tsx:8-25,78-80` — 路由白名单大面积缺失**：`ROUTE_TO_MENU_KEY` 缺 `/dramas`、`/publish`、`/channel-accounts`、`/batch-slice`、`/watermark`、`/resource-download` 等，返回 null 时直接放行，按角色路由控制形同虚设。建议补全映射或改「默认拒绝」。
5. **`frontend/src/components/AppLayout.tsx:166` + `backend/app/api/workers.py:188-190` — 全角色每 15s 轮询 admin 专属 `GET /workers`**，publisher/material 登录期间持续 403 噪音。建议按角色条件渲染或后端返回精简状态。

### 中危

6. **`frontend/src/contexts/AuthContext.tsx:66,121` — access_token 存 localStorage**，一次 XSS 即可窃取重放 JWT。建议迁移内存存储 + HttpOnly Cookie 静默刷新，短期以 CSP + 输出转义缓解。
7. **`frontend/src/components/AuthGuard.tsx:61-83` — early return 之后再次调用 `useAuth()`**，违反 Hooks 规则（当前未崩溃但脆弱）。建议合并到所有 return 之前。
8. **`deploy/nginx.conf:49-52` 及各 location、`frontend/nginx.conf:39-41` — 安全头因 nginx `add_header` 继承规则在实际流量路径全部丢失**，且无 CSP。建议收敛为 include 片段逐 location 补齐。
9. **`deploy/nginx.conf` — 全文无 `limit_req`/`limit_conn`**，登录接口可不限速暴力尝试。建议至少对 `/api/auth/` 限流。
10. **`scripts/deploy_server.sh:56-64` — tar 管道原地覆盖生产目录，无版本目录、无备份、无回滚**，中途失败留半新半旧。建议时间戳目录发布 + symlink 原子切换 + 保留 N 版。
11. **`scripts/deploy_server.sh:15,22,168` — 无 `set -e`、`StrictHostKeyChecking=no` 放弃指纹校验、管道吞掉 db_sync_columns 退出码**。建议补 `-e`、固定 known_hosts、检查 `PIPESTATUS`。
12. **`frontend/src/pages/DramaLibrary.tsx:182-196,754` — 关键词击键即发请求无防抖**，且挂载时两个 effect 双重请求。建议 300ms 防抖并合并初始化 effect。
13. **9 个页面超 1000 行**：EpisodeDetail 3691、ShortDrama 1918、PublishManagement 1431、DramaLibrary 1360、BatchSlice 1333、SliceTasks 1279、Watermark 1276、ProjectDetail 1189、OutputPreview 1063。建议按筛选/表格/弹窗/轮询拆分并设行数红线。
14. **`docker-compose.yml:283` vs `deploy/docker-compose.yml:236` — alembic 失败处置两版不一致**（开发版吞错、生产版一次 stamp 异常永久阻塞）。建议统一失败即退出并由部署脚本显式检查退出码。
15. **`frontend/src/contexts/AuthContext.tsx:6-50` — material 角色 `ROLE_PERMISSIONS` 无 `/dramas` 菜单入口**，与后端读放开口径不同步。建议同步开放。

### 低危

16. **`frontend/package.json:20` — `zustand` 声明但全库零引用**，死依赖。建议移除。
17. **`frontend/src/pages/PublishManagement.tsx:229,255,277` — `setTimeout(fetchTasks, 3000)` 未清理**，卸载后仍触发请求与 setState。
18. **`frontend/src/pages/ShortDrama.tsx:262-330` — 轮询 effect 依赖含 Set 状态对象**，状态变更即销毁重建 interval（无泄漏但抖动）。
19. **`frontend/src/pages/IntervalDetection.tsx:41-54` — 挂载即无条件 3s 轮询 progress**，空闲页面常驻无效请求。
20. **`backend/requirements.txt:17` — `python-jose>=3.3.0` 低于漏洞修复版 3.4.0 且无上限**。建议 `python-jose[cryptography]>=3.4.0` 并接入依赖自动更新。

### 前端与部署整体评价

前端底子不错：client.ts 401 无感刷新带并发排队、轮询普遍有 cleanup、无 dangerouslySetInnerHTML/eval、axios/vite 均为已含修复的新版。主要短板在权限防御深度：AuthGuard 白名单缺失 + localStorage 存 token + 全角色轮询 admin 接口，前端 RBAC 目前更像 UI 提示而非安全边界。部署侧风险最重（高危 1-3），构成「仓库泄露→生产沦陷」完整链路，应最优先处理。alembic 质量良好（抽查 0036/0039/0043/0049/0050 均有 downgrade、幂等检查、无长锁数据迁移）。

---

## 修复优先级 Top 10（建议两周内）

| # | 问题 | 类型 | 预估 |
|---|---|---|---|
| 1 | 轮换 JWT_SECRET/SECRET_KEY、清弱口令、env 移出版本控制 | 部署 | 0.5 天 |
| 2 | batch_slice/slice 的客户端 path 白名单校验（任意文件读/删） | API+任务链 | 1 天 |
| 3 | 生产 compose postgres/backend 改回 loopback 绑定 | 部署 | 0.5 小时 |
| 4 | dispatch_ready_slices 原子 claim（UPDATE...WHERE 抢占） | 任务链 | 0.5 天 |
| 5 | visibility_timeout 配置（acks_late 双跑） | 任务链 | 0.5 小时 |
| 6 | config 接口限 admin + 敏感键掩码 | API | 0.5 天 |
| 7 | operator_id 服务端强制（读放开后的配套收紧） | API | 0.5 天 |
| 8 | heartbeat/3 个 WS 补鉴权（08-12 遗留清算） | API | 1 天 |
| 9 | _ensure_source_video finally 只清理下载副本 | 任务链 | 0.5 天 |
| 10 | deploy_server.sh 原子发布 + 回滚；alembic 失败两版统一 | 部署 | 1 天 |

## 机制性建议（治本）

1. **输入信任边界**：集中收敛「路径白名单校验、operator_id 强制、敏感键掩码、UUID 解析转 400」为路由级依赖/帮助函数，杜绝各文件复制粘贴漏挂。
2. **开放路由白名单进 CI**：把「允许无鉴权的路由清单」固化为测试断言，新增 WS/端点必须显式登记，防止 08-12 遗留在两个月内不仅未修还扩面的情况重演。
3. **状态迁移规约**：任务状态变更「必须 commit + 必须有超时兜底」，用 lint/评审清单强制。
4. **资源生命周期**：为 Playwright tab、临时视频文件、子进程树建立统一清理守护（beat 定时清扫 + finally 规约）。
