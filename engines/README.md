# 引擎脚本说明文档

## 概述

引擎脚本是 Clip Workflow 中用于执行特定视频处理任务的独立可执行脚本。每个引擎脚本封装了特定的视频处理逻辑，通过 AutoClip 服务调用。

## 脚本要求

### 基本规范

1. **语言**: 脚本可以使用 Bash、Python 或其他可执行语言编写
2. **权限**: 引擎脚本必须具有可执行权限（`chmod +x`）
3. **位置**: 所有引擎脚本放置在 `engines/` 目录下
4. **命名**: 脚本名称应使用小写字母，单词间用连字符分隔，例如：`highlight-detection.sh`

### 输入输出规范

引擎脚本通过标准输入输出和环境变量进行数据交换：

**输入参数（环境变量）**:

| 环境变量 | 说明 | 示例 |
|---------|------|------|
| `INPUT_FILE` | 输入视频文件路径 | `/tmp/input.mp4` |
| `OUTPUT_DIR` | 输出目录路径 | `/tmp/output/` |
| `CONFIG_JSON` | 配置参数（JSON 格式） | `{"duration": 60}` |
| `MEDIA_ID` | 素材 ID | `uuid-string` |
| `TASK_ID` | 任务 ID | `uuid-string` |

**输出要求**:

- 脚本执行成功时，退出码为 `0`
- 执行失败时，退出码为非零
- 将处理结果输出到标准输出（JSON 格式）：

```json
{
  "status": "success",
  "output_file": "/tmp/output/result.mp4",
  "duration": 30.5,
  "metadata": {
    "key": "value"
  }
}
```

### 错误处理

- 脚本必须包含完善的错误处理逻辑
- 错误信息应输出到标准错误（stderr）
- 不支持的文件格式应返回明确的错误信息

## 可用引擎脚本

### 智能高光剪辑 (`highlight-detection.sh`)

利用 AI 模型自动识别视频中的高光时刻，并生成精彩片段合集。

**配置参数**:

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `max_duration` | int | 输出视频最大时长（秒） | 60 |
| `min_clip_duration` | int | 单个片段最小时长（秒） | 5 |
| `scene_threshold` | float | 场景切换检测阈值 (0-1) | 0.7 |

### 字幕生成 (`subtitle-generator.sh`)

自动为视频生成字幕，支持多种输出格式。

**配置参数**:

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `language` | string | 源语言 | zh |
| `model` | string | 语音识别模型 | whisper-large |
| `output_formats` | array | 输出格式列表 | ["srt"] |

### 视频摘要 (`video-summary.sh`)

将长视频自动压缩为短视频摘要。

**配置参数**:

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `target_duration_ratio` | float | 目标时长与原视频时长比例 | 0.3 |
| `keep_audio` | bool | 是否保留原音频 | true |

### 多平台适配 (`platform-adaptation.sh`)

将视频自动裁剪适配为不同平台的尺寸规格。

**配置参数**:

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `target_aspect_ratios` | array | 目标宽高比列表 | ["16:9","9:16"] |
| `keep_important_content` | bool | 是否保留重要内容区域 | true |

## 开发新的引擎脚本

### 步骤

1. 在 `engines/` 目录下创建可执行脚本文件
2. 实现标准的输入输出接口
3. 添加必要的错误处理
4. 设置可执行权限：

```bash
chmod +x engines/your-engine.sh
```

### 模板

以下是一个引擎脚本的基本模板：

```bash
#!/usr/bin/env bash
set -euo pipefail

# 引擎脚本模板
# 功能描述: [在此描述引擎功能]

# 读取输入参数
INPUT_FILE="${INPUT_FILE:-}"
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/output}"
CONFIG_JSON="${CONFIG_JSON:-{}}"

# 参数验证
if [ -z "$INPUT_FILE" ]; then
    echo "{\"status\": \"error\", \"message\": \"INPUT_FILE is required\"}" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# 处理逻辑
# [在此实现具体处理逻辑]

# 输出结果
echo "{\"status\": \"success\", \"output_file\": \"$OUTPUT_FILE\"}"
exit 0
```

## 注意事项

1. **资源限制**: 引擎脚本在执行时受到 CPU 和内存限制，请避免资源密集型操作
2. **临时文件**: 使用 `$OUTPUT_DIR` 存放临时文件，避免使用系统临时目录
3. **日志输出**: 使用标准错误输出（stderr）记录日志，避免干扰标准输出
4. **超时处理**: 引擎脚本应设置合理的超时机制，避免长时间无响应
5. **兼容性**: 确保脚本在 Docker 容器环境（Alpine Linux）中正常运行
## 切片引擎 (`slice.py`)

Clip Workflow 的切片引擎（ffmpeg 封装），支持快速/去重/挖洞三种模式，以及动态文字水印。

**用法**:

```bash
python slice.py <source> <cutlist> <output_dir> --mode fast|dedupe|scrub [--intervals FILE] [--cpu-percent N] [--watermark JSON]
```

**参数**:

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `--mode` | string | 切片模式：fast（快速）/ dedupe（去重）/ scrub（挖洞） | fast |
| `--intervals` | string | 挖洞模式使用的区间文件（每行 `start end`） | - |
| `--cpu-percent` | int | CPU 资源分配比例（1~100），限制 ffmpeg 线程数 | 50 |
| `--watermark` | string | 动态文字水印配置 JSON | - |

**水印 JSON 结构**:

```json
{
  "text": "自定义水印文字（支持 {title} {date} {datetime} 占位符）",
  "font_size": 28,
  "opacity": 0.5,
  "position": "bottom"
}
```

- `text`: 水印文字内容（留空默认用剧集标题 + 日期）
- `font_size`: 字号（12~120，默认 28）
- `opacity`: 透明度（0.05~1.0，默认 0.5）
- `position`: 位置（`bottom` 底部 / `top` 顶部，默认 bottom）

**动态效果**：文字从左侧缓缓滑向右侧（`mod(2*t, w+tw)-tw`）+ 透明度呼吸闪烁（`0.4+0.3*sin(2*PI*t)`），用于防搬运/标识来源。

## 去水印引擎（`seedance_wm_runner.py`）

集成自 [ben500500/remover](https://cnb.cool/ben500500/remover) 仓库的 5 阶段去水印流水线
（seedance_wm 包），作为独立可执行脚本放置在 `engines/` 下。

**用法**:

```bash
python engines/seedance_wm_runner.py <input.mp4> -o <output.mp4> [options]
```

**参数**:

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `-o, --output` | string | 输出视频路径 | `<input>_clean.mp4` |
| `-r, --region` | string | 手动水印区域 `x,y,w,h`（跳过自动检测） | 自动检测 |
| `--backend` | string | 修补后端：`auto`/`lama`/`migan`/`cv2`（CPU） | auto |
| `--segments` | int | 分段检测段数（水印移动时调大） | 4 |
| `--detector` | string | 主检测器：`matchTemplate`/`yolov8_seg`/`paddleocr` | matchTemplate |
| `--inpainter` | string | 主修复器：`lama`/`cv2_telea`/`cv2_ns` | 按 config.yaml |
| `--config` | string | YAML 配置文件路径 | 内置 config.yaml |
| `--no-audio` | - | 合成时不保留原音轨 | 保留 |
| `--yes` | - | 跳过免责声明确认（无人值守） | 需确认 |

**5 阶段流水线**: 抽帧(FFmpeg) → 检测(matchTemplate→YOLO→OCR 降级链) → mask 序列 →
修复(LaMa→cv2)+时序平滑 → 合成(FFmpeg)。

**进度上报**: 遵循引擎脚本规范，在处理过程中向 stdout 输出 `PROGRESS:<pct>` 行，
由 `backend/app/engines/watermark_runner.py` 的 `_run_cmd` 解析后写入数据库。

**依赖**: `numpy` / `opencv-python-headless` / `ffmpeg-python` / `PyYAML`
（已在 `backend/requirements.txt` 中补齐）。

## 去水印引擎（`remove_mask_remover.py`）

集成自 [ben500500/remove-mask](https://cnb.cool/ben500500/remove-mask) 仓库的
「ROI + cv2.inpaint(NS/TELEA)」方案，作为独立可执行脚本放置在 `engines/` 下。

**v7 核心升级（同步 remove-mask 上游更新）**：处理前**自动分析任意视频**，不再局限于
固定视频。每次处理都会先做水印检测分析，再给出最佳方案执行：

1. 均匀抽帧，逐帧提取"半透明白色"水印像素（min 通道高 + 低饱和 + 局部亮度增强）
2. 对四个角（TL/TR/BL/BR）分别检测水平文字带，对候选框做 **y 直方图峰值聚类 + 带内 x 聚类**（v10）
3. 多候选合并成完整覆盖框，检测不到时回退"全角大框"（顶部/底部各 20%/13%）
4. 输出【分析报告】：检测到的水印位置 + 置信度 + 推荐方案

**v8~v11 后续同步（remove-mask 上游）**：
- v8：同一侧支持多个水印带（TL/TL2/TL3、BR/BR2…），水印分段出现不漏盖；置信度按真实覆盖帧比例计算
- v9：新增**时间一致性过滤**（剔除白发/人脸等移动亮色主体误判）+ **文字带高度守卫**（≤110px）
- v10：自动检测改为**四角分别检测**，可检出右上/右下等非贴边水印；收紧半透明白字判定；
  **文件名匹配支持中文/UUID**（如 `爷孙重逢.mp4` 能正确命中预置 ROI）；爷孙重逢 ROI 修正为
  **右上 TR + 右下 BR**（实测位置，不再误伤老人头部/白发）
- v11：自动检测改用**四角时间一致性热力图 + 边缘先验**（解决 v10 逐帧聚类对弱/淡色水印漏检，
  如爷孙重逢右上 TR）；爷孙重逢预置 ROI 补上**左上角 TL** 水印覆盖（修复 TL 漏除）

**原理**: 不区分“哪些像素是水印”，直接把整个水印 ROI 矩形当掩码，用
cv2.inpaint（NS 纳维-斯托克斯 / TELEA 快速行进法）从 ROI 边界向内插值填充。按视频文件名匹配内置
ROI 表（覆盖 Seedance 左上/右上/右下角规律），参数保真（保留原始分辨率/帧率，
音频流复制零损耗）。

**两种去水印模式（`--mode` 切换，同步 remove-mask 上游更新）**:
- `inpaint`（默认）：ROI + 插值修复，保留原始构图，水印区域被插值填充
- `crop`：裁切去水印，裁掉包含水印的上下水平带，剩余画面等比放大回原分辨率、
  左右居中裁回原宽。画面无修复痕迹，但构图有裁剪/放大（适合画面上下无重要内容）

**预设方案（`--preset`，依据《引擎排名结论.md》按排名排序）**:
| 排名 | 预设 | 算法 | ROI | 半径 | 去除率 |
|---|---|---|---|---|---|
| ① | `ns_small_r5`（最优） | NS | small | 5 | 87.1% |
| ② | `teela_small_r5` | TELEA | small | 5 | 86.4% |
| ③ | `ns_small_r3` | NS | small | 3 | 86.0% |
| ④ | `ns_large_r3` | NS | large | 3 | 85.6% |
| ⑤ | `teela_small_r3` | TELEA | small | 3 | 84.2% |
| ⑥ | `teela_large_r3` | TELEA | large | 3 | 83.3% |
| ⑦ | `auto` | 自动检测 ROI（兜底新视频） | - | 5 | 75.4~78.8% |
| ⑧⑨ | `crop_small`/`crop_large` | 裁切去水印（不推荐，画面损失大） | - | - | 52~56% |

> 依据《引擎排名结论.md》：**NS + small 预置 + radius=5（ns_small_r5）为最优**，水印去除率 87.1%、
> 画面几乎无损；radius=5 全面优于 radius=3；修复 TL 后预置精调 ROI 全面反超自动检测。

**用法**:

```bash
python engines/remove_mask_remover.py <input.mp4> -o <output.mp4> [options]
# 只做自动水印分析，输出检测报告（不处理）
python engines/remove_mask_remover.py <input.mp4> -o <output.mp4> --analyze-only
# 强制走自动检测（跳过预置 ROI），适合自定义新视频
python engines/remove_mask_remover.py <input.mp4> -o <output.mp4> --auto
# 指定预设方案（按排名最优为默认）
python engines/remove_mask_remover.py <input.mp4> -o <output.mp4> --preset ns_small_r5
```

**参数**:

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `-o, --output` | string | 输出视频路径 | `<input>_clean.mp4` |
| `-r, --region` | string | 手动水印区域 `x,y,w,h`（覆盖文件名匹配） | 按文件名匹配 |
| `--preset` | string | 预设方案（按《引擎排名结论》排序，见上表） | 空（按单项默认，等价 ns_small_r5） |
| `--algo` | string | 插值算法：`ns`（推荐）/ `telea` | `ns` |
| `--radius` | int | 修补半径（1~20，仅 inpaint 模式） | 5 |
| `--iterations` | int | 修补迭代次数（1~5，仅 inpaint 模式） | 1 |
| `--scope` | string | 水印 ROI 范围：`small`=收紧贴合水印文字（默认，遮盖面积小）；`large`=整角大框（覆盖更彻底） | `small` |
| `--mode` | string | 去水印模式：`inpaint`=插值修复保留原构图（默认）；`crop`=裁切去水印（等比缩放切掉水印） | `inpaint` |
| `--source-name` | string | 原始文件名（用于匹配内置 ROI 表） | 输入文件 basename |
| `--analyze-only` | flag | 只分析不处理，输出水印检测报告 | 关闭 |
| `--auto` | flag | 强制走自动检测（跳过预置 ROI） | 关闭 |

**内置 ROI 表**: `648BC321` / `C0CC0472` / `0270150E` / `3906E761` / `爷孙重逢`
（基于全视频 OCR + 时序分析确认）；命中预置 ROI 时优先使用人工精调框，
**其他任意视频自动走检测分析**（检测不到回退全角大框）。

**进度上报**: 向 stdout 输出 `PROGRESS:<pct>` 行，由
`backend/app/engines/watermark_runner.py` 的 `_run_cmd` 解析后写入数据库。

## remove-mask 经验库共享（`remove_mask_rois.py`）

remove-mask 的「ROI 经验」被抽取为 `engines/remove_mask_rois.py` 共享模块，
供全部去水印引擎复用。ROI 表同步 remove-mask 上游更新，提供 **small / large 两套范围**：

- `small`（默认）：收紧 ROI，严格贴合水印文字 + 6px buffer，遮盖面积小、对画面干预少
- `large`：旧版整角大框，覆盖更彻底，但遮盖面积明显更大

| 引擎 | 借用方式 |
|------|---------|
| `remove_mask` | 直接按文件名匹配内置 ROI 表（原逻辑） |
| `seedance_wm` | 自动检测基础上**合并**经验 ROI（可一次覆盖左上+右下）；自动检测全失败时回退到经验位置 |
| `seedance` | 分段检测基础上**合并**经验 ROI |
| `remove_ai` | RAiW 厂商检测失败时，回退到经验位置重试（委托 seedance 区域擦除） |

后端 `watermark_runner.py` 通过 `source_name` 把每条视频的原始文件名透传给
各引擎，命中内置 ROI 经验库时自动生效，无需用户额外操作。
