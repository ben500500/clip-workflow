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
# 纯 CPU 部署：
docker compose up -d
docker compose ps   # 等待所有服务 healthy（首启约 1-3 分钟）

# GPU 加速部署（可选，见下方「GPU 加速」小节）：
#   docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

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

## 六.5、GPU 加速部署（可选，三期效率优化）

在带 NVIDIA GPU（如 RTX 2070 8G）的部署机上开启硬件加速，为三类负载提速：

| 负载 | 涉及服务 | 收益 |
|------|---------|------|
| 切片 NVENC 编码 | slice-worker / slice-worker-2 | 重编码/加角标/烧字幕提速 3~5× |
| Whisper ASR | autoclip | 1 小时音频从 10+ 分钟降到 1~2 分钟 |
| Ollama 画面理解 | ollama | MiniCPM-V 视觉描述从秒级降到毫秒级 |

**前提（部署机一次性配置）：**

```bash
# 1. 安装 NVIDIA 驱动（RTX 2070 属 Turing 架构，支持 CUDA 12.x / NVENC）
# 2. 安装 nvidia-container-toolkit 并配置 Docker runtime
sudo apt install nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
# 3. 验证 GPU 透传
sudo docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

**启用（用 GPU overlay 覆盖默认纯 CPU 配置）：**

```bash
# 构建 GPU 版 autoclip 镜像（含 faster-whisper 的 CUDA 后端）
docker compose build autoclip \
  && docker build --build-arg ENABLE_CUDA=true -t clip-autoclip:latest ./autoclip

# .env 中开启 Whisper CUDA（RTX 2070 8G 建议 fp16）
#   WHISPER_DEVICE=cuda
#   WHISPER_COMPUTE_TYPE=float16

# 带 GPU overlay 启动（纯 CPU 机器不要加本文件）
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

**自检：**

```bash
# NVENC 编码器（worker 节点界面「硬件编码」列应出现 h264_nvenc 等）
docker exec clip-slice-worker ffmpeg -hide_banner -encoders | grep -i nvenc
# Whisper 设备（autoclip 日志应显示 device=cuda）
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs autoclip | grep -i "device=cuda"
# Ollama GPU
nvidia-smi | grep clip-ollama
```

> ⚠️ 注意：8G 显存下建议同一时刻只跑 1~2 个 GPU 任务，避免并发 OOM。
> 「去水印（LaMa）」在本期不启用 GPU（CPU 已够用），不在 overlay 覆盖范围内。
> 本 overlay 中的 `encoder_capabilities` 字段为「GPU 节点自动分派」预留的接口，当前单机自动模式仅作能力展示。

## 七、日常运维要点

- **更新流程**：`git pull` → 同步变更文件到服务器 → `docker compose build` 相关服务 → `docker compose up -d --force-recreate` 受影响容器 → 检查 alembic 新列
- **删除剧集**：后端会自动清理 MinIO（源素材/切片成品）+ media 卷（源副本/选点产物/ASR 缓存/帧缓存）+ 孤儿兜底清扫，无需手动
- **批量切片**：源视频 rsync 到 `/home/<用户名>/videos/<剧名拼音>/`，JSON 的 `path` 填对应路径；`auto_delete_source: true` 处理完自动删源
- **磁盘告警**：关注 `docker system df`；MinIO 与 media 卷是空间大头

## 八、备份与回滚（批 M·评审一 P1-5 落地）

### 8.1 备份（一键）

`scripts/backup_server.sh` 在服务器本机跑：pg_dump 整库（custom 格式）＋ `.env` 快照
（chmod 600）＋ `pg_restore --list` 完整性自检＋保留期清理（默认 14 天）。

```bash
# 手动跑一次
bash scripts/backup_server.sh
# 自定义目录/保留期
BACKUP_DIR=/data/backup KEEP_DAYS=30 bash scripts/backup_server.sh
```

挂 cron（每日 03:40，错开整点高峰）：

```cron
40 3 * * * cd /home/cc12703/clip-workflow && bash scripts/backup_server.sh >> logs/backup.log 2>&1
```

⚠️ 本脚本只管**数据库＋部署变量**。MinIO 媒体卷（raw-footage/sliced/previews 等桶）
与 media 卷体积大、再生成本各不相同，不在本脚本范围——按卷快照另行处理
（丢失后果见下表，先想清楚再决定快照频率）。

| 数据 | 位置 | 丢了的后果 | 兜底 |
|---|---|---|---|
| 业务库 | pg_dump（本脚本） | 台账/审计/文案全没了 | 每日备份 |
| 部署变量 | .env 快照（本脚本） | 全站失联 | 每日备份 |
| 媒体文件 | MinIO 卷 | 成片/素材没了，库里的键悬空 | 按卷快照（另行） |
| 缓存/中间产物 | media 卷 | 可再生（抽帧/ASR/预览重跑） | 可不备 |

### 8.2 回滚步骤（按事故类型对号入座）

**A. 只回代码（发版翻车，库没动）**

```bash
cd /home/cc12703/clip-workflow
git log --oneline -5                 # 找上一个已知好的 commit
git checkout <good-sha>              # 或者 git revert 坏提交
bash scripts/deploy_server.sh        # 或手动 docker compose up -d --build 受影响服务
docker compose ps && docker compose logs --since 2m backend | grep -iE 'error|traceback'
```

注意：alembic 迁移**不做 downgrade**（163 部署链路走 stamp＋database.py 补列，
见 alembic/versions 各文件头说明）。回退代码前先确认旧代码与新库结构兼容——
本仓迁移全部「可空加列」，旧代码读新库是安全的；反向（新代码读旧库）由
database.py 的 ADD COLUMN 清单兜底。

**B. 库坏了（误删/迁移事故），从备份恢复**

```bash
# 1) 停写入方（backend/celery workers/beat），只留 postgres
docker compose stop backend worker-beat worker-fast worker-remotion worker-wechat-dl clip-backend 2>/dev/null

# 2) 恢复（覆盖式：先 drop 再建，确认库名！）
docker compose exec -T postgres pg_restore -U clipworkflow -d clipworkflow \
  --clean --if-exists < /home/cc12703/clip-backups/clip-db-<stamp>.dump

# 3) 起回来 + 冒烟
docker compose up -d
docker compose exec -T backend curl -sf http://localhost:8080/api/health && echo OK
```

⚠️ `--clean` 会先删现有对象再建——**先备份当前这份坏库**（万一只是部分坏，
drop 之后没有回头路），再执行恢复。

**C. .env 事故（变量丢失/写错）**

```bash
# 找最近一份快照，diff 出差异再整份还原（别盲抄——快照里的旧密码可能已轮换过）
ls -t /home/cc12703/clip-backups/env-*.snapshot | head -3
diff /home/cc12703/clip-backups/env-<stamp>.snapshot /home/cc12703/clip-workflow/.env
cp /home/cc12703/clip-backups/env-<stamp>.snapshot /home/cc12703/clip-workflow/.env
docker compose up -d --force-recreate   # env 变了必须重建容器
```

### 8.3 纪律

- **先备份再动库**：任何手工 SQL、迁移演练、大批量删改之前，先跑一次备份脚本。
- **备份要演练**：每季度拿最新 dump 在本机起个一次性 postgres 跑一遍 8.2-B，
  备份没被恢复过的＝没有备份。
- 服务器上的备份目录别和被备份物同盘（`BACKUP_DIR` 默认在 home 下，机器挂了就一起没了——
  有条件就再 rsync 一份到 NAS/另一台机）。
