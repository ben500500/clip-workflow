"""
AutoClip 微服务精简配置
只保留真实 DashScope 流水线所需的常量与路径。
"""
import os
from pathlib import Path

# 应用根目录 /app/app
APP_DIR = Path(__file__).parent.parent

# 媒体目录（compose 挂载 volume，uploads 存于此）
MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", "/app/media"))
DATA_DIR = MEDIA_DIR / "data"
OUTPUT_DIR = DATA_DIR / "output"
METADATA_DIR = OUTPUT_DIR / "metadata"

# Prompt 文件路径
PROMPT_DIR = APP_DIR / "prompt"
PROMPT_FILES = {
    "outline": PROMPT_DIR / "大纲.txt",
    "timeline": PROMPT_DIR / "时间点.txt",
    "recommendation": PROMPT_DIR / "推荐理由.txt",
    "title": PROMPT_DIR / "标题生成.txt",
}

# API 配置
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
MODEL_NAME = os.getenv("API_MODEL_NAME", "qwen-plus")

# 画面理解（Frame Analysis）配置：本地 Ollama 视觉模型，默认关闭
FRAME_ANALYSIS_ENABLED = os.getenv("FRAME_ANALYSIS_ENABLED", "false").strip().lower() in ("1", "true", "yes")

# 处理参数
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "5000"))
# 注意：这里默认 0.0，评分过滤交给 clips 接口的 min_score（契约默认 60）执行，
# 避免真实流水线在 step3 内部按 0.7 预先过滤导致返回空列表。
MIN_SCORE_THRESHOLD = float(os.getenv("MIN_SCORE_THRESHOLD", "0.0"))

# 确保基础目录存在
for _d in [MEDIA_DIR, DATA_DIR, OUTPUT_DIR, METADATA_DIR, PROMPT_DIR]:
    _d.mkdir(parents=True, exist_ok=True)
