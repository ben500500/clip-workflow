# 部署手册（clip-workflow）

> 目标：把本系统部署到一台全新服务器时，避免历史踩坑。
> 更新时间：2026-08-12（沉淀自实际部署与运维问题）

## 一、环境要求

| 项 | 要求 |
|----|------|
| 服务器 | Linux（本仓库按 Ubuntu/Debian 系验证），Docker + docker compose v2 |
| 磁盘 | 至少 50GB（源视频 + MinIO + 数据库 + 模型缓存） |
| 内存 | ≥ 16GB（AI 选点 + 切片 ffmpeg 并行） |
| 网络 | 能访问 docker 镜像源；**离线环境**需预置 hf-cache 与镜像源 |
| 本机工具 | `rsync`（传源视频）、`expect`（可选，自动化） |

## 二、部署步骤

```bash
# 1. 克隆（CNB 私有仓库）
git clone https://cnb.cool/<user>/clip-workflow.git && cd clip-workflow

# 2. 配置 .env（复制 .env.example，填写全部密码/地址）
cp .env.example .env
vi .env   # POSTGRES_PASSWORD / REDIS_PASSWORD / OLLAMA_HOST / MINIO 等必填

# 3. 预置离线模型缓存（若服务器无法访问外网）
#    - hf-cache/：去水印 ONNX 模型
#    - 参考 .env 中 HF_HUB_OFFLINE=1

# 4. 构建镜像（国内网络建议先配 docker 镜像加速器）
docker compose build

# 5. 创建源视频目录并放宽权限（重要，见下方权限清单）
mkdir -p /home/<用户名>/videos && chmod 777 /home/<用户名>/videos

# 6. 修改 docker-compose.yml 中的硬编码路径（见下方第 2 节）

# 7. 启动
docker compose up -d
docker compose ps   # 等待所有服务 healthy（首启约 1-3 分钟）

# 8. 验证
curl http://<服务器IP>/api/health        # backend
curl -I http://<服务器IP>/               # 前端
docker compose ps | grep -c healthy      # 应等于服务数
```

## 三、⚠️ 硬编码项清单（换服务器必改）

| 位置 | 硬编码值 | 说明 |
|------|---------|------|
| `docker-compose.yml`（4 处） | `/home/cc12703/videos` | 批量切片源视频目录，**换成新服务器的实际路径**（bind mount 需保持容器内外同路径） |
| `slice-worker/worker.json.template` | node-id 等 | 一般无需改，多机部署时注意 node-id 唯一 |

改完执行：`docker compose up -d --force-recreate backend worker-fast worker-video worker-publish slice-worker slice-worker-2`

## 四、权限清单（历史踩坑）

| 场景 | 问题 | 对策 |
|------|------|------|
| rsync 传源视频 | 默认保留 700 权限 → 容器用户（uid 999）读不了 | `rsync -avz --chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r 源/ 目标/` 或传完 `chmod -R a+r` |
| batch 删除源视频 | 需要**目录**写权限（不是文件权限） | `chmod 777 /home/<用户名>/videos`（compose 已注释说明） |
| 中文目录/文件名 | rsync 传输转义失败 `\#351\#273\#204` | 目录用英文/拼音（如 `dramaA`），`drama` 字段填中文剧名即可 |
| media 卷文件 | 属主 uid 1000（autoclip 写入），其他容器 uid 不同 | 清理 media 一律用 `clip-autoclip` 容器执行 |

## 五、已知坑与对策（代码已修复，仅说明机制）

| 坑 | 机制 | 对策（新部署时） |
|----|------|------------------|
| celery 默认队列无人消费 | 未配 task_routes 的任务进 `celery` 队列 | 已在 compose 给 worker-fast 加 `-Q metrics,default,celery`，勿移除 |
| Redis 分库 | celery broker=db1 / slice worker=db0 / result=db2 | 查队列用 `redis-cli -n 1`；勿混用 |
| alembic 迁移不生效 | 此项目 alembic 一直跳过，靠 ORM 补列 | 每次带 `alembic/versions/` 的更新，启动后检查新列，缺失则手动 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |
| fontTools 缺失 | 引擎固定文字 SC 提取依赖 fonttools | 已装 `py3-fonttools`（slice-worker）与 `fonttools`（backend requirements），镜像重建时勿精简 |
| 引擎 stderr 被丢弃 | worker 执行引擎时 `io.Discard` stderr，失败无详情 | 排查引擎失败看 worker 日志的退出码 + 手动跑引擎复现 |
| slice-worker 重启强杀任务 | 旧版本直接 SIGKILL 留下临时目录 | 已实现优雅退出 + `stop_grace_period: 15m`，勿移除 |

## 六、初始化自检清单

```bash
# 1. 目录与权限
ls -ld /home/<用户名>/videos            # 应为 drwxrwxrwx
# 2. 源文件可见性（在 worker 容器内）
docker exec clip-worker-fast ls /home/<用户名>/videos/
# 3. 字体环境
docker exec clip-slice-worker python3 -c "import fontTools; print(fontTools.version)"
docker exec clip-slice-worker python3 -c "import sys; sys.path.insert(0,'/app/engines'); import slice; print(slice._resolve_drawtext_font())"
#    期望输出：:fontfile=/tmp/NotoSansCJKsc-Regular-*.ttf（SC 单字体）
# 4. 数据库迁移列
docker exec clip-postgres psql -U clipworkflow -d clipworkflow -c "\d batch_slice_items" | grep detect_task_id
# 5. 队列通畅（发布一个任务后）
docker exec clip-redis redis-cli -a <pass> -n 1 LLEN celery    # 不应持续堆积
# 6. Ollama / 画面理解
docker exec clip-ollama ollama list
```

## 七、日常运维要点

- **更新流程**：`git pull` → 同步变更文件到服务器 → `docker compose build` 相关服务 → `docker compose up -d --force-recreate` 受影响容器 → 检查 alembic 新列
- **删除剧集**：后端会自动清理 MinIO（源素材/切片成品）+ media 卷（源副本/选点产物/ASR 缓存/帧缓存）+ 孤儿兜底清扫，无需手动
- **批量切片**：源视频 rsync 到 `/home/<用户名>/videos/<剧名拼音>/`，JSON 的 `path` 填对应路径；`auto_delete_source: true` 处理完自动删源
- **磁盘告警**：关注 `docker system df`；MinIO 与 media 卷是空间大头
