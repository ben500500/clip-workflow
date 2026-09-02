# clip-workflow 切片 GPU 加速（NVENC）— 方案与问题总结（已落地版）

> 整理时间：2026-09-02 ｜ 版本状态：**alpine→glibc 迁移已落地（commit `5c363f2`，09:51）并在 40 生产验证通过**
> 修订说明：本文档初版（`2788567`，10:20）写于迁移落地的**前一刻**，属"迁移前快照"（误把已办结的 Option A 写成待办）。经 CodeBuddy 专家评审（Issue #344）指正后，本版已与代码对账修订为**落地结论**。
>
> 结论先行：**40 生产已用上 NVENC（RTX 2070 SUPER 实测 h264_nvenc 编码通过）**；163（无 GPU）自动回退 libx264（CPU）。引擎「有 GPU 用硬编、无 GPU 走软编」的通用能力端到端成立。

---

## 一、目标

让切片编码**通用**：部署机有 GPU 时优先用 NVENC 硬编，无 GPU 时自动回退 CPU 软编（libx264），两端行为一致、无需分别配置。

## 二、最终状态（现状，2026-09-02）

| 项 | 状态 |
|---|---|
| slice-worker 运行时 / ffmpeg 构建基座 | `debian:bookworm-slim`（**glibc**，替换原 alpine/musl）|
| ffmpeg | 自编译 6.1.1：`--enable-nvenc --enable-ffnvcodec`（GPU）+ `--enable-libx264 --enable-libx265`（CPU 回退，必需）+ `--enable-libass/--enable-libfreetype/--enable-libharfbuzz/--enable-libfribidi`（ass/subtitles/drawtext）|
| apt ffmpeg | 保留，仅作**共享库提供者**（自编译 ffmpeg 对 libass/x264/glib/xcb 等为动态链接）；自编译二进制覆盖 `/usr/bin/ffmpeg\|ffprobe` |
| 引擎通用检测 | `engines/slice.py::detect_best_encoder()` 三重保障：`SLICE_ENCODER` 强制覆盖 → 运行时 1 帧实测 → libx264 兜底（与基座无关）|
| **40 生产** | GPU 透传 + **h264_nvenc 实测编码通过**（RTX 2070 SUPER，`5c363f2` 提交信息记录）|
| **163** | 无 GPU → 自动回退 libx264（CPU）；**glibc 镜像兼容性待验**（见 §七 收尾）|

## 三、关键根因（为什么必须换 glibc）

- 宿主机经 `nvidia-container-toolkit` 透传进容器的 NVIDIA 驱动**用户态库**（`libnvidia-encode.so.1` 等）是 **glibc ELF**。
- **alpine(musl) 进程 dlopen 必然失败**（glibc 特有符号 / ld.so 依赖），ffmpeg 报 `Cannot load libnvidia-encode.so.1`，`detect_best_encoder()` 永远回退 libx264。
- 换 **glibc 基座**是让 NVENC 真正可用的**唯一正解**（业界公认，非"选项"而是"墙"）。gcompat/libc6-compat 兼容层对 NVIDIA 驱动库**不可靠**，不采用。

## 四、演进过程与踩坑记录

### 4.1 alpine 阶段：自编译 NVENC ffmpeg（commit `43f3bd8` ~ `900f0c4`）

在 alpine 基座内自编译带 nvenc 的 ffmpeg，打通了"镜像带 nvenc 能力 + GPU 透传"，但 musl 无法加载 NVIDIA 库，实际仍走 CPU。

### 4.2 遇到的问题与解决

| # | 问题 | 根因 | 解决 |
|---|---|---|---|
| 1 | FFmpeg/nv-codec-headers 下载失败 | 国内访问 GitHub 大文件 SSL 断流（curl 92）| FFmpeg 源码用 **Gitee 镜像**；nv-codec-headers 打进仓库（`slice-worker/nv-codec-headers/`，n12.1.14.0 + `ffnvcodec.pc`）|
| 2 | configure 报 `nvenc requested, but not all dependencies are satisfied: ffnvcodec` | headers master(API 13.1) 与 ffmpeg 6.1.1 不匹配 | 换 **n12.1.14.0**（API 12.1，与 6.1.1 同期配对）|
| 3 | ffnvcodec 校验失败 | 缺 `ffnvcodec.pc`（pkg-config 查版本）| 补装 `/usr/lib/pkgconfig/ffnvcodec.pc` |
| 4 | ffmpeg 启动报 `libass.so.9 not found` | 自编译 ffmpeg 对 libass/x264 等**动态链接** | runtime 保留 apt `ffmpeg` 提供共享库，再 COPY 自编译二进制覆盖 |
| 5 | 构建慢/误判卡死 | runtime apt 拉 ~224-252 包下载慢 | 耐心等待（层缓存后不重复）|
| 6 | GPU overlay 合并失败 `additional properties not allowed` | `docker-compose.gpu.yml` 服务名缺 `services:` 包装/未缩进 | 补 `services:` + 正确缩进（`900f0c4`）|
| **7** | **nvenc 仍加载失败 `Cannot load libnvidia-encode.so.1`** | **alpine(musl) 无法 dlopen glibc 构建的 NVIDIA 驱动库** | **✅ 换 glibc 基座解决（见 §五，`5c363f2`）** |

## 五、落地：alpine→glibc 迁移（commit `5c363f2`，2026-09-02 09:51）

`slice-worker/Dockerfile` 改动（唯一文件）：

- `ffmpeg-nvenc` 构建段与运行段均换 `debian:bookworm-slim`，apt 源切 aliyun（`/etc/apt/sources.list.d/debian.sources`）。
- 构建段补 `ca-certificates`（git https clone gitee 需要）。
- 自编译 ffmpeg 保持 **n6.1.1 + nv-codec-headers n12.1.14.0** 与 configure 旗标不变（刻意降行为差异）。
- 运行段 apt 依赖：`ffmpeg`、`python3`、`python3-opencv`、`fontconfig`、`fonts-noto-cjk`、`fonts-droid-fallback`、`python3-fonttools`、`procps`、`gettext`、`tzdata`、`bash`、`ca-certificates`。
- **python 版本 3.12（alpine）→ 3.11（Debian），与 backend/autoclip 完全对齐**（引擎在 backend 已验证过），是迁移的加分项而非风险。
- 验证：**40 生产已重建，两个 worker h264_nvenc 实测编码通过（RTX 2070 SUPER）**；libx264/libx265 CPU 回退、libass 字幕滤镜链保留。

## 六、相关提交（cnb main）

| commit | 内容 |
|---|---|
| `43f3bd8` | slice-worker: ffmpeg 自编译带 NVENC（初版）|
| `f1e443a` | 改用 Gitee + 仓库内置 nv-codec-headers（规避 GitHub 断流）|
| `4f04556` / `b28869b` | nv-codec-headers 直拷 + 换 n12.1.14.0 + 补 ffnvcodec.pc |
| `c1066fe` | runtime 保留 apt ffmpeg（提供动态依赖共享库）|
| `1170450` / `900f0c4` | docker-compose.gpu.yml 补 services 包装 + 正确缩进 |
| **`5c363f2`** | **运行时与 ffmpeg 构建基座 alpine(musl) → Debian(glibc)，NVENC 真正可用（40 已验）** |

## 七、专家评审与收尾（CodeBuddy Issue #344）

> CodeBuddy 专家评审（架构/容器/GPU 编码三方向，流水线 `cnb-epo-1k1ge7ov0`，2026-09-02）结论：
> ① glibc 迁移方向唯一正确、已实证；② 风险可控（最高 R1）；③ 保留自编译 ffmpeg 判定正确（deb-multimedia/jellyfin 不带 libass/新 x264，不换）；④ 备选（gcompat/distroless/独立容器）均不推荐；⑤ 批准验收，剩余 ~0.5–1 人日收尾。

### 收尾清单进度

| # | 项 | 状态 |
|---|---|---|
| 1 | 本文档对账为落地结论 | ✅ 本次修订 |
| 2 | `docker-compose.gpu.yml` 清理"仍需宿主机 ffmpeg 带 NVENC"过时注释 | ✅ 本次修订 |
| 3 | 163 无 GPU 兼容性验证（glibc 镜像跑 CPU 回退 / 字幕滤镜 / 竖转横）| 🔄 进行中（163 先行验证，40 不动）|
| 4 | 引擎热更链路 `engine_update.go` 在新镜像回归一次 | ⏳ 待 |
| 5 | 镜像体积优化（`--strip` / 裁剪 noto-cjk 子集，可选）| ⏳ 可选 |

### 遗留风险 R1（中，未处理）

`deploy_remote_worker.sh` 的 `base-images-arm64.tar.gz` 仍只打包 `golang:1.22-alpine` / `alpine:3.19`；新 Dockerfile 已引入 `debian:bookworm-slim`（双段），**arm64 离线远程节点**会去 Docker Hub 拉 debian → 国内/离线超时，与"免 Hub"初衷冲突。处理：后续把 `debian:bookworm-slim` 加进该离线包。
