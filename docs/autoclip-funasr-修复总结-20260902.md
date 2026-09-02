# clip-workflow 40 生产 ASR（FunASR）故障修复总结

> 整理时间：2026-09-02 ｜ 涉及：40 生产 autoclip 容器 / `docker-compose.yml`
> 结论先行：**问题根因是「autoclip 镜像按构建参数条件安装 funasr」+「40 上 funasr 只被临时装进容器运行时目录」，一重建就丢，表现为时好时坏**。已通过①固定 compose 构建参数、②用内置 funasr 的镜像重建容器根治。

---

## 一、现象

用户反馈 40 生产上 ASR 的 funasr 模型「又不行了」。日志表现为**时好时坏**：

```text
autoclip.main ERROR 语音识别失败: FunASR 运行时缺少依赖（No module named 'funasr'）。请安装 funasr / modelscope / torch 后再试。
```

同一时段内既有失败（14:20 / 14:29），也有成功（14:38，funasr 1.4.12 + Paraformer-Large 正常出字幕）。

---

## 二、根因（双层）

### 2.1 autoclip 镜像条件安装 funasr

`autoclip/Dockerfile` 用构建参数决定是否安装本地 FunASR 重依赖（torch / torchaudio / funasr / modelscope，约 190MB CPU 轮子）：

```dockerfile
ARG ENABLE_FUNASR=false   # 默认 false，避免构建超时（CNB runner 10min 无输出会被杀）
...
if [ "$ENABLE_FUNASR" = "true" ]; then
    pip install --no-cache-dir -r requirements-funasr.txt
fi
```

**凡是不带 `--build-arg ENABLE_FUNASR=true` 的重建/部署，新镜像就没有 funasr → ASR 必挂。**

### 2.2 40 运行容器是「无 funasr 旧镜像 + 运行时临时安装」

排查证据链：

| 检查项 | 结果 |
|---|---|
| 运行容器创建时间 | 2026-09-01 17:50（旧容器，非今天重建） |
| 运行容器所用镜像 | `e455871f` —— **`import funasr` 失败（镜像内无 funasr）** |
| 容器内 funasr 实际位置 | `/app/.local/lib/python3.11/site-packages/funasr` |
| funasr 安装时间（mtime） | **2026-09-02 14:28:37**（今天临时 pip install --user 装进去的） |
| 容器 14:37:33 重启后 | funasr 生效，14:38 ASR 成功 |
| 正确镜像 | `clip-autoclip:latest`=fcd73（14:37:27 对修复后容器的 docker commit 快照，内含 funasr）—— 但当时没被用于运行 |

→ 40 上的 funasr 依赖只是**临时装进容器运行文件系统**的，容器一重建/换镜像即丢。这就是「修好了又坏」的根源。

---

## 三、修复方案（已实施）

### 3.1 根治：compose 固定 funasr 构建参数

`docker-compose.yml` 的 autoclip build 段增加：

```yaml
  autoclip:
    build:
      context: ./autoclip
      dockerfile: Dockerfile
      # ASR 默认 funasr_local(Paraformer-Large)，funasr/torch 必须烤进镜像
      args:
        ENABLE_FUNASR: "true"
    image: clip-autoclip:latest
```

效果：以后任何 `docker compose build / up -d --build autoclip` 都会自动把 funasr 烤进镜像，不再依赖手工传参。

### 3.2 让运行容器落到「内置 funasr」的镜像上

- 将 40 的 `docker-compose.yml` 做**定点同步**（只改 autoclip build 段，保留 40 与本地在 RPA 健康检查段的既有差异——RPA 停用中未动）。
- 清理重建中断产生的杂散容器后，用 `docker compose up -d autoclip` 从 `clip-autoclip:latest`（fcd73，含 funasr）重建容器。

### 3.3 相关提交

| commit | 内容 |
|---|---|
| `76b6f4b` | fix(autoclip): compose 固定 ENABLE_FUNASR=true 构建参数，防止重建镜像丢 funasr 导致 ASR 故障（已推 cnb main） |

---

## 四、验收（Grade）

| 项 | 结果 |
|---|---|
| 容器状态 | `clip-autoclip` Up / healthy |
| ASR 配置 | `AUTOCLIP_ASR_METHOD=funasr_local` + Paraformer-Large（环境变量未变，符合默认） |
| funasr 可用性 | `import funasr` → 1.4.12 ✓ |
| 模型真实加载 | Paraformer-Large + VAD + 标点模型加载成功（22.8s，走缓存）✓ |
| 代码一致性 | `llm_providers / step3_scoring / speech_recognizer / llm_client` 4 文件 md5 == cnb main（此前 docker cp 的热修复不丢）✓ |
| 模型缓存 | `/app/.cache` 为 bind 挂载（`hf-cache`，含 2GB modelscope），重建容器不重下模型 ✓ |
| 全栈健康 | 40 上 18 个容器全部 healthy ✓ |

---

## 五、踩坑与经验

1. **判断镜像里有没有 funasr，不能只看 `docker images` 构建时间**。`clip-autoclip:latest` 是 docker commit 快照，`docker history` 的 pip 层仍显示 `ENABLE_FUNASR=false`，但内容物其实在 `/app/.local`。要实测：
   ```bash
   docker run --rm --entrypoint python clip-autoclip:latest -c "import funasr; print(funasr.__version__)"
   ```
2. **运行中容器的依赖 ≠ 镜像依赖**。`pip install --user` 只改容器运行文件系统，容器 recreate 后全部丢失。镜像内依赖必须以 Dockerfile/构建参数形式固化。
3. **autoclip 容器重建的代价**：会丢内存中的选点项目状态（已知问题，重建后需重新触发选点）。本次重建前确认无进行中任务，模型缓存为 bind 挂载故无损。
4. **`docker compose up` 重建中断会留杂散容器**（本次出现 `elegant_leakey` / `60cfbe..._clip-autoclip` Created 态残留），先 `docker rm -f` 清理再重拉即可。
5. **`docker exec` 传 heredoc 跑 python 必须加 `-i`**，否则 stdin 为空、python 空跑退出码 0 无输出（会误判为成功）。

---

## 六、遗留建议（可选）

- 当前运行的 `clip-autoclip:latest`（fcd73）是 docker commit 快照，功能正常但不是纯 Dockerfile 构建产物。**下次正常发版时**跑一次 `docker compose build autoclip`（compose 已带 `ENABLE_FUNASR=true`）即可产出干净的正式镜像（funasr 会装进系统 site-packages）。
- 40 与本地 compose 的 RPA 健康检查段差异仍未同步（RPA 停用中，按用户要求暂不动）。
