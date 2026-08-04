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