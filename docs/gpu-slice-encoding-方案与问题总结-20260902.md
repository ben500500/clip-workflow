# clip-workflow 切片 GPU 加速（NVENC）— 方案与问题总结

> 整理时间：2026-09-02 ｜ 涉及版本：slice-worker Dockerfile 改造（commit `43f3bd8` ~ `900f0c4`）
> 结论先行：**引擎已具备「有 GPU 用 nvenc、无 GPU 自动回退 libx264」的通用能力**，163（无 GPU）已验证自动走 CPU；40 已透传 GPU，但因 **alpine(musl) 无法加载 glibc 的 NVIDIA 驱动库**，nvenc 实际仍加载失败、走 CPU。要真正用上 GPU 需把 slice-worker 运行时换成 glibc 基础镜像（Debian），属较大改动（见文末选项）。

---

## 一、目标

让切片编码**通用**：部署机有 GPU 时优先用 NVENC 硬编，无 GPU 时自动回退 CPU 软编（libx264），两端行为一致、无需分别配置。

## 二、现状（改造前）

| 项 | 40（生产） | 163（测试） |
|---|---|---|
| 宿主 GPU | ✅ RTX 2070 SUPER | ❌ 无 |
| slice-worker 容器 GPU 透传 | ❌ 未启用 | ❌ 无 |
| 容器内 ffmpeg | Alpine 自带包，**无 nvenc** | 同左 |
| 实际编码 | **libx264（CPU）** | libx264（CPU） |

引擎 `engines/slice.py` 的 `detect_best_encoder()` **本就通用**：探测 `ffmpeg -encoders` → 优先 nvenc/videotoolbox → 额外做**运行时编码测试**（无 GPU 时跳过）→ 兜底 libx264；`SLICE_ENCODER` 环境变量可强制指定。**缺的只是镜像里没有 nvenc 的 ffmpeg + GPU 没透传。**

## 三、改动方案（已实施并进 cnb）

### 1. `slice-worker/Dockerfile`：多阶段自编译 ffmpeg 6.1.1
- 新增 `ffmpeg-nvenc` 构建阶段：`--enable-nvenc --enable-ffnvcodec`（GPU）+ `--enable-libx264 --enable-libx265`（CPU 回退，**必需**）+ `--enable-libass --enable-libfreetype --enable-libharfbuzz --enable-libfribidi`（ass/subtitles/drawtext 滤镜，引擎依赖）。
- 版本对齐当前 Alpine 包自带的 **ffmpeg 6.1.1**，降低行为差异。
- nv-codec-headers（`n12.1.14.0`）**打进仓库**（`slice-worker/nv-codec-headers/`，含 5 个头文件 + `ffnvcodec.pc`），构建时免网络依赖。
- 运行时阶段：**保留 `apk add ffmpeg`**（提供自编译二进制动态依赖的共享库），再用自编译 nvenc 二进制覆盖 `/usr/bin/ffmpeg|ffprobe`。

### 2. `docker-compose.gpu.yml`：修复 GPU overlay
- 原文件服务名写在顶层（无 `services:` 包装），compose 合并必失败，**GPU 透传从未真正生效过**。
- 补 `services:` 包装 + 服务名正确缩进后，`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d slice-worker slice-worker-2` 可正常应用（给 slice-worker/slice-worker-2/autoclip/ollama 透传 GPU）。

### 3. 40 生产启用 GPU overlay
- 用 GPU overlay 重建 slice-worker/slice-worker-2，`docker inspect` 确认 `DeviceRequests: [nvidia]`，GPU 已透传进容器。

## 四、验证结果

| 场景 | 结果 |
|---|---|
| **163（无 GPU）**：容器内 `ffmpeg -encoders` | nvenc×3、libx264/x265×3、libass 滤镜 ✓ |
| **163** 引擎 `detect_best_encoder()` | 探测 hevc_nvenc → 运行时测试失败 → **自动回退 libx264（CPU）** ✓ 符合预期 |
| **163** CPU 编码实测 | libx264 出片正常 ✓ |
| **40（有 GPU）**：GPU 透传 | `DeviceRequests: [nvidia]` ✓ |
| **40** 引擎 `detect_best_encoder()` | 仍回退 libx264（原因见「关键问题」）|
| **40** CPU 编码 / 容器健康 | 正常 ✓（功能安全）|

## 五、遇到的问题与解决（含未解决）

| # | 问题 | 根因 | 解决 |
|---|---|---|---|
| 1 | FFmpeg/nv-codec-headers 下载失败 | 国内访问 GitHub 大仓库/文件 SSL 断流（`curl 92` / `SSL_read eof`）| FFmpeg 源码改用 **Gitee 镜像**（`gitee.com/mirrors/FFmpeg`，n6.1.1 可用）；nv-codec-headers 本地经 `raw.githubusercontent.com` 下载后**打进仓库** |
| 2 | configure 报 `nvenc requested, but not all dependencies are satisfied: ffnvcodec` | nv-codec-headers master（API 13.1）与 ffmpeg 6.1.1（2023，配 12.x）版本不匹配 | 换用 **n12.1.14.0** 头文件（NVENC API 12.1，ffmpeg 6.1.1 同期配对）|
| 3 | 同上 ffnvcodec 校验失败 | ffmpeg configure 用 **pkg-config** 查 `ffnvcodec >= 版本`，缺 `ffnvcodec.pc` | 补 `ffnvcodec.pc`（Version 12.1.14.0）装入 `/usr/lib/pkgconfig/` |
| 4 | 容器内 ffmpeg 启动报 `libass.so.9 not found` | 自编译 ffmpeg 对 libass/x264/x265/freetype/glib/xcb 等是**动态链接**（非全静态），runtime 删了 `apk add ffmpeg` 导致缺共享库 | runtime **保留 `apk add ffmpeg`**（提供同版本共享库），再 COPY 自编译二进制覆盖 |
| 5 | 构建慢/误判卡死 | runtime 的 `apk add py3-opencv` 拉 gstreamer 等 ~224-252 包，下载慢（~30min）| 耐心等待（层缓存后不再重复）；曾误 kill 一次已重启恢复 |
| 6 | GPU overlay 合并失败 `additional properties not allowed` | `docker-compose.gpu.yml` 服务名在顶层、缺 `services:` 包装，且未缩进 | 补 `services:` + 正确缩进（`900f0c4`）|
| 7 | **❌ 40 上 nvenc 仍加载失败（未解决）**：ffmpeg 报 `Cannot load libnvidia-encode.so.1` | **alpine(musl) 容器无法 dlopen glibc 构建的 NVIDIA 驱动库**（libnvidia-encode.so.1 等是 glibc 产物），musl 进程加载即失败 | **需要把 slice-worker 运行时从 alpine 换成 glibc 基础镜像（Debian）**，属较大改动，尚未实施 |

## 六、相关提交（cnb main）

| commit | 内容 |
|---|---|
| `43f3bd8` | slice-worker: ffmpeg 自编译带 NVENC（初版，源码 git clone）|
| `f1e443a` | 改用 Gitee + 仓库内置 nv-codec-headers（规避 GitHub 断流）|
| `4f04556` | nv-codec-headers 直接拷到 /usr/include/ffnvcodec |
| `b28869b` | nv-codec-headers 换 n12.1.14.0 + 补 ffnvcodec.pc |
| `c1066fe` | runtime 保留 apk ffmpeg（提供动态依赖共享库）|
| `1170450` / `900f0c4` | docker-compose.gpu.yml 补 services 包装 + 正确缩进 |

## 七、现状小结与后续选项

**当前状态（安全）**：40/163 切片都走 CPU（libx264），功能正常；镜像已带 nvenc 能力 + GPU 已透传，只差 glibc 运行时就能真正用 GPU。

| 选项 | 说明 | 风险/成本 |
|---|---|---|
| **A. 换 glibc 基座（Debian）** | slice-worker 运行时 + ffmpeg 构建阶段都换成 glibc（apt 装 python3/opencv/字体），nvenc 才能加载 NVIDIA 库 | 改动大、40 生产重建、需重新验证 CPU 回退与字幕滤镜 |
| **B. 保持现状（CPU）** | 当前通用镜像 + 自动回退已进 cnb；GPU 暂不用 | 零风险，但 40 的 RTX 2070 继续闲置 |
| **C. 委托 CodeBuddy** | 把「glibc 基座改造」作为独立大任务，交给 CNB CodeBuddy 出方案/PR，本侧负责构建验证与验收 | 符合「大活委派」原则 |

> 备注：本方案的目标（引擎通用检测）已达成并验证；剩余唯一硬骨头是 **alpine→glibc 运行时切换**（问题 #7），决定 40 能否真正用上 GPU。
