# clip-workflow 详细修复方案（代码级草案，未改动代码）

> 本方案针对 **`~/Downloads/Agent-WorkSpace/clip-workflow`**（短剧切片投放工作流），
> 配套文件：`CODE_REVIEW_REPORT.md`（审查报告 + 路线图）。
> 本文件聚焦路线图【第一批 + 第二批 + 架构项】的全部 **12 个高危项**（安全 6 / 性能 5 / 架构 1），
> 给出 `before`/`after` 代码片段、验证方法与风险。**全部为只读草案，待你确认后逐项提交（建议 PR/diff 审阅）。**

> 凭据约定：本文仅标注行号与机制，**不输出任何明文密钥/口令**。

---

## 【H1】CDP 9222 零凭据暴露浏览器 —— 安全/最高危（改动 3 行）

**定位**：`docker-compose.yml:365-369` `rpa_worker.ports` 把 Chromium 调试端口发布到宿主机 `0.0.0.0`；`rpa/cdp_proxy.py:18` `LISTEN_HOST="0.0.0.0"`；`cdp_proxy.py:60-77` 主动重写 Host 绕过 Chromium DNS-rebinding 防护。backend/worker 实际通过 docker 网络 `rpa_worker:9222` 访问（`compose:218/274` `CHROME_DEBUG_HOST=rpa_worker`），**根本不需要发布到宿主机**。

**before（docker-compose.yml:365-369）**
```yaml
    ports:
      # 绑定 0.0.0.0（勿加 127.0.0.1 前缀）：backend/worker 需通过 docker 网络
      # 访问 rpa_worker:9222 做 CDP 调试（豆包生成/一键发布链路），
      # 仅绑宿主机 loopback 会导致容器间 ECONNREFUSED
      - "${RPA_DEBUG_PORT:-9222}:9222"
```

**after（docker-compose.yml）** —— 整段删除 `ports`：
```yaml
  rpa_worker:
    # ... 其余不变，仅移除 ports 段 ...
    # 容器间经 clip-network 互访 rpa_worker:9222，不再对外暴露
    # （healthcheck 仍用 127.0.0.1:9222 自检，见 compose:371）
```

同时收紧 `rpa/cdp_proxy.py:18`：
```python
LISTEN_HOST = os.getenv("CDP_PROXY_BIND", "127.0.0.1")  # 默认仅绑 loopback
```

**验证**：`curl http://<宿主机IP>:9222/json/version` → `Connection refused`；容器内 `curl http://rpa_worker:9222/json/version` → 正常返回。
**风险**：极低。唯一依赖是 docker 网络，已具备。`RPA_DEBUG_PORT` 环境变量可整行删除。

---

## 【H2】100 个端点完全无鉴权 —— 安全/高危（改动 ~20 行）

**定位**：`backend/app/main.py:172-188` 所有 `include_router` 均无 `dependencies=`；各 `api/*.py` 是裸 `APIRouter()`。`nginx.conf` 对 `/api/` 无鉴权/无限流。`auth.py` 自带 `/api/auth` 前缀且含 login/refresh，**不能**被这个依赖包住。

**after（main.py）** —— 引入鉴权依赖并给业务路由加锁（auth/health 除外）：
```python
from app.api.auth import get_current_user   # 已有该依赖（auth.py:56/103 用 HS256 校验）

# 业务路由统一加鉴权；Worker Token 端点（slice_worker_callback）改走独立 router 不在此列
_protected = [projects, upload, autoclip, intervals, slice, preview, publications,
              config_api, publish, dashboard, workers, monitor, maintenance,
              watermark, shortdrama, publish_material]
for _r in _protected:
    app.include_router(_r.router, prefix="/api", dependencies=[Depends(get_current_user)])

app.include_router(auth.router)                       # 保持开放（login/refresh）
# health / ws 保持无依赖
```

> 注：`monitor`/`workers` 心跳等内部端点若需保留无鉴权，单独拆到 `internal.router` 并由 nginx 限 IP；不要与业务混在一起裸奔。

**验证**：`curl -o /dev/null -w '%{http_code}' localhost:8001/api/dashboard/config` → `401`；带 `Authorization: Bearer <token>` → `200`。
**风险**：需先完成 H4（密钥必填），否则 token 可被伪造。前端需统一在 axios 拦截器注入 access_token；刷新逻辑依赖 `/api/auth/refresh`。建议先对 `dashboard`/`config`/`publish`/`watermark` 4 模块灰度（先加依赖，观察前端的 token 携带）。

---

## 【H3】种子用户明文弱口令且在生产无条件执行 —— 安全/高危（改动 ~10 行）

**定位**：`backend/app/main.py:57-62` 4 个硬编码弱口令（用户名+固定数字）；`:120` `_create_seed_users()` 在 `lifespan` 无条件执行，无 `DEBUG` 守卫。admin 经 `auth.py:197 POST /api/auth/login` 可直登，无验证码/锁定/限流。

**after（main.py）** —— 仅 DEBUG 创建 + 口令必须来自环境变量（无默认值）：
```python
import os, json, logging as _log
async def _create_seed_users():
    if not settings.DEBUG:                       # 生产不自动建弱口令账号
        _log.info("非 DEBUG 环境，跳过种子用户创建（请通过注册/邀请流程开通）")
        return
    raw = os.getenv("SEED_USERS_JSON")           # 形如 [{"username":"admin","password":"<强口令>","role":"admin"}]
    if not raw:
        _log.warning("DEBUG 环境未提供 SEED_USERS_JSON，跳过种子用户")
        return
    seeds = json.loads(raw)
    async with async_session_factory() as session:
        for seed in seeds:
            # ... 同原逻辑（先查后插）...
```

并在 `config.py` 启动期加一道不安全默认值自检（`settings` 校验器）：
```python
from pydantic import field_validator
@field_validator("JWT_SECRET")
@classmethod
def _no_default_secret(cls, v):
    if not v or v == "your-secret-key-change-in-production":
        raise ValueError("生产环境必须在 .env 设置 JWT_SECRET，禁止使用默认值")
    return v
```

**验证**：`DEBUG=false` 启动 → 日志出现"跳过种子用户"；`SEED_USERS_JSON` 缺失 → 警告但不阻断。`JWT_SECRET` 留默认 → 进程启动即 `ValueError`。
**风险**：生产环境若此前依赖种子 admin 登录，需改为首次部署用一次性脚本创建 admin（或开放受保护的注册接口）。建议配套运维 SOP。

---

## 【H4】JWT / Cookie 密钥不安全默认值 —— 安全/高危（改动 ~12 行）

**定位**：`backend/app/config.py:111` `JWT_SECRET: str = "your-secret-key-change-in-production"`（占位符默认 = 公开密钥，可离线伪造任意用户）；`:116` `COOKIE_ENCRYPT_KEY: str = ""` 空默认 → `auth.py:311/320` 回退 `JWT_SECRET`，**两套密钥同源**。

**after（config.py）** —— 必填无默认 + 独立 Cookie 密钥（缺失则生成并持久化）：
```python
    # JWT
    JWT_SECRET: str                       # 必填，无默认（配合 H3 的 field_validator 启动即校验）
    JWT_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    # RPA Cookie 加密密钥（Fernet/AES-256），与 JWT_SECRET 必须不同
    COOKIE_ENCRYPT_KEY: str = ""          # 留空时由 _ensure_cookie_key() 生成并落盘
```
```python
import os, secrets, stat
from pathlib import Path
def _ensure_cookie_key() -> str:
    if settings.COOKIE_ENCRYPT_KEY:
        assert settings.COOKIE_ENCRYPT_KEY != settings.JWT_SECRET, "COOKIE_ENCRYPT_KEY 不得与 JWT_SECRET 相同"
        return settings.COOKIE_ENCRYPT_KEY
    p = Path(os.getenv("DATA_DIR", "/app/data")) / "cookie_key"
    if p.exists():
        return p.read_text().strip()
    k = secrets.token_urlsafe(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(k); os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    return k
COOKIE_ENCRYPT_KEY = _ensure_cookie_key()   # 启动时固化
```

**验证**：`.env` 无 `JWT_SECRET` → 启动 `ValueError`；`COOKIE_ENCRYPT_KEY` 与 `JWT_SECRET` 相同 → 断言失败；重启后端 `cookie_key` 文件不变 → 已存 Cookie 仍可解密。
**风险**：已加密落库的 RPA Cookie 在密钥变更后需重新登录。首次部署务必先写 `JWT_SECRET` 再起服务。

---

## 【H5】MinIO 数据面 + 控制台暴露公网，默认 AK 为公开值 —— 安全/高危（改动 ~4 行）

**定位**：`docker-compose.yml:83-84` 9000/9001 均绑 `0.0.0.0`；`config.py:24` `MINIO_ACCESS_KEY: str = "minio_admin"` 即 MinIO 众所周知的默认账号名。9001 控制台对外可达 = 可爆破 root 凭据。

**after（docker-compose.yml:82-84）** —— 删控制台映射 + 数据面绑 loopback：
```yaml
    ports:
      - "127.0.0.1:${MINIO_PORT:-9000}:9000"
      # 删除 9001 控制台映射（仅容器内部 minio_init 需要，外部无需访问）
```
**after（compose:87 / config.py:24）** —— AK 改为必填，去掉默认：
```yaml
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:?请在 .env 设置 MINIO_ROOT_USER}   # 原 ${MINIO_ROOT_USER:-minioadmin}
```
```python
    MINIO_ACCESS_KEY: str                       # 原 "minio_admin" 默认值删除，必填
```

**验证**：`curl http://<宿主机IP>:9001` → `Connection refused`；`minioadmin` 不再可用登录。
**风险**：前端 presigned 预览走 `MINIO_EXTERNAL_ENDPOINT`（compose:216，默认 `localhost:9000`），改 loopback 后浏览器仍经 nginx/后端拿 URL，不受影响。需确保 `.env` 提供非默认 `MINIO_ROOT_USER`。

---

## 【H6】Redis 暴露公网 —— 安全/高危（改动 1 行）

**定位**：`docker-compose.yml:61` `"${REDIS_PORT:-16379}:6379"` 绑 `0.0.0.0`。Redis 承载切片 Stream，payload 含 `callback_token`（`api/slice.py:415/444`）；密码泄露可读全部任务 token、伪造回调、投递恶意 payload 给 Go worker（叠加 M8 可写任意路径）。

**after（docker-compose.yml:61）** —— 加 loopback 前缀：
```yaml
    ports:
      - "127.0.0.1:${REDIS_PORT:-16379}:6379"
```
> 切片 worker / backend / beat 均经 `clip-network` 的 `redis:6379` 访问，无需宿主机端口。如其它物理机 slave 需跨机访问，应通过 VPN/SSH 隧道而非直曝。

**验证**：`redis-cli -h <宿主机IP> -p 16379 ping` → 超时/拒绝；容器内 `redis-cli -h redis ping` → `PONG`。
**风险**：极低。确认无外部 `docker run -e REDIS_URL=...:16379` 的远程 worker 依赖本机端口；`deploy_remote_worker.sh` 若直连该端口需改为隧道。

---

## 【P1】一行 SQL 错误导致全库 0 索引 —— 性能/最高危（改动 1 行 + 1 补丁脚本）

**定位**：`init.sql:273` = `CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)`，但 `users` 表（`:17-30`）**无 `email` 字段**。它是 28 条 `CREATE INDEX` 中第 1 条；`postgres:15-alpine` entrypoint 用 `psql -v ON_ERROR_STOP=1` + `set -e` → **报错即中止，后续 27 条全不执行**。连锁：`create_all` 因表已存在跳过索引（`database.py:54`）、alembic 带 `|| echo` 吞失败（`compose:184`）。净结果：业务索引 0/28，看板退化为全表扫描 + `statement_timeout=30s` → 数据量大即 30s 超时。

**after（init.sql:273）** —— 删除该行（或改为存在的列）：
```sql
-- 删除：CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
-- users 表无 email 字段，保留会令整文件索引创建中止。其余 idx_users_* 保持。
```

**存量库补索引脚本（新建 `migrations/fix_missing_indexes.sql`，用 `CONCURRENTLY` 在线加，不锁表）**：
```sql
-- 仅当 init.sql 首次失败导致索引缺失时执行；幂等（IF NOT EXISTS）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_username        ON users(username);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_role           ON users(role);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_is_active       ON users(is_active);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);
-- ... 按 init.sql:278-300 的其余 25 条 1:1 补齐 ...
-- 另补 models.py 缺失的 11 个外键索引（见下方 before/after）
```

**after（models.py 补显式 `index=True`）** —— 11 个外键缺索引：
```python
# 例如 project_members.project_id / user_id、media_assets.user_id / project_id、
# clip_tasks.user_id / project_id、clip_candidates.project_id 等 11 处
project_id = Column(UUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True)  # 原缺 index=True
```

**验证**：`EXPLAIN ANALYZE SELECT ... FROM media_assets ORDER BY created_at DESC LIMIT 20;` 修复前后对比 → 从 `Seq Scan` 变 `Index Scan`；`dashboard` 接口 P95 从 ~30s 降到毫秒级。
**风险**：`CONCURRENTLY` 不能在事务块内执行；老库大表加索引会短暂占 IO，建议在低峰期跑。新建库因 init.sql 已修，无需补。

---

## 【P2】单 Celery worker 串行吞 4 队列 —— 性能/高危（改动 ~25 行）

**定位**：`docker-compose.yml:293` `command: ["celery", ..., "worker", "--loglevel=info", "--concurrency=1"]`，**无 `-Q`** → 消费 `video_processing`/`publish`/`metrics`/`default` 全部 4 队列，全局严格串行（concurrency=1）。一个 2h 切片任务运行时，beat 持续投递，发布/指标任务被饿死（"点了发布没反应"根因）。

**after（docker-compose.yml）** —— 拆 3 个 worker 服务（复用 `clip-backend:latest`）：
```yaml
  worker-video:
    image: clip-backend:latest
    command: ["celery","-A","app.celery.tasks.celery_app","worker","-Q","video_processing","--loglevel=info","--concurrency=1"]
    # environment / volumes / depends_on 同原 worker（复制一份）
  worker-publish:
    image: clip-backend:latest
    command: ["celery","-A","app.celery.tasks.celery_app","worker","-Q","publish","--loglevel=info","--concurrency=1"]
  worker-fast:
    image: clip-backend:latest
    command: ["celery","-A","app.celery.tasks.celery_app","worker","-Q","metrics,default","--loglevel=info","--concurrency=4"]
  # 删除原单 worker 服务（或改名保留其一）
```
> 队列名需与 `tasks.py:41-46` 声明的 `@task(queue=...)` 一致；若当前未显式指定队列名，需先在 task 装饰器加 `queue=` 参数。

**验证**：并发发起 1 个切片 + 1 个发布 → `celery -A app.celery.tasks.celery_app inspect active` 两个 worker 各跑各的；发布不再排在切片后面 2 小时。
**风险**：需确认 task 已绑定队列名（否则仍进 default 被 worker-fast 吃）。`--concurrency=1` 对 video 是对的（ffmpeg 已占满 CPU）；publish 也可 1。

---

## 【P3】`_rewrite_cb` 死等 10 分钟独占唯一 worker 槽 —— 性能/高危（改动 ~20 行）

**定位**：`backend/app/celery/tasks.py:1935-1949` `deadline = time.time() + 600`，循环 `await asyncio.sleep(3)` + `_load_shortdrama_prompt`。运行在 `run_async(...)` 内，**占据唯一 worker 槽位**；豆包多轮改写可叠加 N×10min → 整站异步停摆。

**after（重构为状态机，交还槽位）** —— 写 `awaiting_rewrite` 后 `return`，由前端确认触发续跑：
```python
async def _rewrite_cb(task_id, *, max_rounds=6):
    state = await _load_shortdrama_prompt_state(task_id)
    if state.get("round", 0) >= max_rounds:
        await _set_prompt_status(task_id, "rewrite_exhausted")
        return
    # 写入"等待人工/前端确认改写"状态并立刻返回，释放 worker 槽位
    await _set_prompt_status(task_id, "awaiting_rewrite",
                             meta={"round": state.get("round", 0) + 1})
    return   # ← 关键：不再 while 死等

# 新增续跑入口（前端确认按钮调用）
@app.post("/api/shortdrama/{tid}/rewrite-resume")
async def doubao_resume_task(tid: str, user=Depends(get_current_user)):
    _enqueue_rewrite(tid)        # 重新投递一个短时 celery 任务，执行单轮改写
    return {"ok": True}
```
> 单轮改写任务本身仍受 `task_time_limit=7200` 保护，但每轮结束即释放槽位，不再长占。

**验证**：触发一次豆包改写 → worker 槽位在首轮结束后立即释放（beat 的 metrics 任务可正常排进）；前端出现"确认改写"按钮。
**风险**：需前端配合新增 `rewrite-resume` 调用（属第四批 WS/前端接线范畴）。若暂不做前端，可降级为"每轮 `await asyncio.sleep(3)` 但最多 1 轮即 return"，先止血再优化。

---

## 【P4】fast 模式无谓重编码两次 —— 性能/高危（改动 ~25 行）

**定位**：`engines/slice.py:189-202` `slice_segment` 恒走 `libx264 -preset veryfast -crf 23` 重编码，全文件无 `-c copy`；fast 模式 `vf/af` 均为 `None`（`:346-350` 仅 dedupe 赋值）却仍重编码。多段时 `concat_segments`（`:205-225`）再编码一遍 → fast 被拖慢 20–40×。

**after（slice.py）** —— fast 且无滤镜时走 `-c copy` + concat demuxer：
```python
def slice_segment(src, start, end, out, vf=None, af=None, threads=1,
                  encoder="libx264", copy_if_possible=True):
    copy_mode = copy_if_possible and not vf and not af
    cmd = ["ffmpeg", "-y", "-threads", str(threads),
           "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src]
    if copy_mode:
        cmd += ["-c", "copy", "-movflags", "+faststart"]        # 仅切割，不重编码
    else:
        cmd += build_encoder_args(encoder, threads)
        cmd += ["-c:a", "aac", "-b:a", "128k"]
        if vf: cmd += ["-vf", vf]
        if af: cmd += ["-af", af]
    cmd.append(out)
    run_ffmpeg(cmd, timeout=3600, threads=threads)

def concat_segments(parts, out, threads=1, encoder="libx264"):
    if len(parts) == 1:
        shutil.move(parts[0], out); return
    # 多段：若各段均为 copy 产出（同编码/分辨率/时基），优先 concat demuxer 免重编码
    if all(_is_copy_segment(p) for p in parts):
        _concat_demuxer(parts, out)        # ffmpeg -f concat -c copy
        return
    # 否则走原 filter_complex 重编码分支
    ...
```
> `-c copy` 要求各段编码/分辨率/时基一致。本项目 `slice_segment` copy 产出满足；若有 watermark/vert2horiz 预处理则自动回退重编码分支。

**验证**：同素材 fast 模式前后对比耗时（copy 通常 10×+ 实时）；含 `'` 目录名仍正常（copy 不经 drawtext 转义）。
**风险**：`-c copy` 对关键帧不重排，`-ss` 落在非关键帧时切点在最近关键帧（视觉可接受）。竖屏转横屏/水印场景已自动走重编码，行为不变。

---

## 【P5】全帧一次性载入内存（去水印 inpaint）—— 性能/高危（改动 ~15 行）

**定位**：`engines/seedance_wm/inpaint.py:243` `raw_imgs = [cv2.imread(...) for f in files]` 把整个帧目录读进 list，`:259-264` 再构造 `smoothed` 全量副本。15s@30fps 1080p ≈ **2.8 GB**，加 float32 缓冲峰值 >4 GB，易 OOM。

**after（inpaint.py）** —— 改为逐帧流式处理 + 写盘，不长期持有全量：
```python
def inpaint_sequence(files, mask_seq, out_dir, **kw):
    prev = None
    for i, f in enumerate(files):
        frame = cv2.imread(f)                 # 单帧进内存
        if prev is not None:
            frame = _temporal_smooth(frame, prev, alpha=0.5)   # 与上一帧轻量时域平滑
        mask = mask_seq[i]
        out = _inpaint_one(frame, mask, **kw)                  # 单帧推理
        cv2.imwrite(os.path.join(out_dir, f"f{i:05d}.png"), out)
        prev = out                                            # 仅保留上一帧用于平滑
        del frame                                            # 立即释放
    # 由调用方把 out_dir 的 PNG 序列封装为视频（改用 MJPEG/中间无损，避免 PNG 高编码成本）
```
> 时域平滑改为"仅持上一帧 + 当前帧"的滑动窗口，内存从 O(N) 降到 O(1)。若算法本身需全序列（如全局光流），则改为分块（如每 30 帧一块）处理。

**验证**：处理 15s 片段时 `docker stats` 看 slice-worker/backend 内存峰值从 >4 GB 降到 <1 GB；输出视觉无差异。
**风险**：纯时域算法改流式需确认不依赖未来帧；若依赖，退回分块方案。PNG 编解码成本高，建议中间产物用无损 MJPEG 或 NV12 临时文件。

---

## 【架构】5 套建表机制并存 → 统一为 alembic —— 架构/高危（改动 ~5 行 + 固化迁移）

**定位**：`init.sql`(含已废的 `:273`)、alembic(15 迁移，`compose:184` 带 `|| echo` 吞失败)、`create_all`(`main.py:118`)、`_apply_compat_migrations`(`database.py:129-210`，40 条硬编码 ADD COLUMN)、`_ensure_autoclip_runs_table`(`database.py:85-127`)。五套并行 → 表结构以"谁最后跑"为准，且静默失败掩盖真实错误。

**after（治理步骤）**
1. **去掉静默吞错**（`compose:184`）—— 失败必须可见：
```yaml
    command: ["sh", "-c", "alembic -c alembic/alembic.ini upgrade head"]   # 删掉 || echo ...
```
2. **alembic 为唯一权威**：删除 `init.sql` 的 DDL（保留为文档/本地开发参考，不再由 entrypoint 执行），`create_all` 改为仅开发期 `if settings.DEBUG` 兜底。
3. **40 条 ADD COLUMN 固化为 1 个 squash 迁移**：把 `_apply_compat_migrations` 的 40 条与 `_ensure_autoclip_runs_table` 的 43 行手写 DDL 合并成一个 alembic 迁移 `xxxx_squash_compat.py`，删除运行时兼容补丁。
4. **`database.py` 启动时不再执行任何 DDL**；仅保留 `asyncping` 连接校验。

**验证**：全新库 `alembic upgrade head` → `\dt` 表数与预期一致；`database.py` 无 `CREATE TABLE`/`ADD COLUMN` 运行时调用；`init.sql` 不再被 entrypoint 引用。
**风险**：高（属第四批结构治理）。需先在预发库跑 `alembic upgrade head` 校验现有 24 张表与 ORM 完全一致，再删 `init.sql` 执行链路。存量库已存在的 40 条 ADD COLUMN 在 squash 迁移里用 `IF NOT EXISTS`/先行 `has_column` 探测，保证幂等。

---

## 落地顺序建议

**第一批（今天，改动极小收益极大）**：H1 → H6 → H5 → P1（合计 <10 行配置/SQL，关掉最致命的"浏览器接管""全库 0 索引""数据面公网暴露"三个口子）。
**第二批（本周，安全止血）**：H4 → H3 → H2 → P2 → P3（密钥必填 + 鉴权接线 + Celery 拆队列；需前端配合注入 token 和 WS 接线）。
**第三批（性能与架构，需回归测试）**：P4 → P5 → 架构项（fast copy、inpaint 流式、建表统一）。

> 上述任一项需要更细的子步骤（如前端 token 注入点清单、alembic squash 迁移骨架）时，按本文件格式单独展开即可。
