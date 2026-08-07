"""Agent 编排层（可选，TRD §4）。

使用 Agno + Ollama (Qwen2.5-7B) 编排 5 个原子工具。
纯本地运行，需要: pip install seedance-wm[agent] + ollama serve

    from seedance_wm.agent import build_agent
    agent = build_agent()
    agent.print_response("去除 /data/in.mp4 的水印并输出 /data/out.mp4")
"""

from __future__ import annotations

from seedance_wm.log import get_logger

log = get_logger("agent")


def build_agent(model_id: str = "qwen2.5:7b", ollama_host: str = "http://localhost:11434"):
    """构建 Agno Agent（懒加载，避免核心依赖）。"""
    try:
        from agno.agent import Agent  # noqa: PLC0415
        from agno.models.ollama import Ollama  # noqa: PLC0415
        from agno.tools import tool  # noqa: PLC0415
    except ImportError:
        raise ImportError(
            "Agent 依赖未安装: pip install seedance-wm[agent] 且需启动 ollama serve"
        ) from None

    from seedance_wm import tools

    @tool(name="extract_frames", requires_confirmation=False)
    def extract_frames_tool(video_path: str, output_dir: str) -> dict:
        """从视频中抽帧并分离音轨。Args: video_path: 输入视频绝对路径; output_dir: 输出目录。"""
        return tools.extract_frames(video_path, output_dir)

    @tool(name="detect_watermark")
    def detect_tool(frames_dir: str, primary: str = "matchTemplate") -> dict:
        """检测 Seedance 视频水印位置。Args: frames_dir: 抽帧目录; primary: 主检测器。"""
        return tools.detect_watermark(frames_dir, primary=primary)

    @tool(name="generate_mask_sequence")
    def mask_tool(bbox: dict, frame_count: int, width: int, height: int, output_dir: str) -> dict:
        """基于 bbox 生成帧级 mask PNG 序列。"""
        return tools.generate_mask_sequence(bbox, frame_count, width, height, output_dir)

    @tool(name="inpaint_frames")
    def inpaint_tool(
        frames_dir: str, masks_dir: str, output_dir: str, device: str = "auto"
    ) -> dict:
        """逐帧修复 + 帧间平滑。Args: device: auto/cuda/cpu。"""
        return tools.inpaint_frames(frames_dir, masks_dir, output_dir, device=device)

    @tool(name="mux_video")
    def mux_tool(frames_dir: str, audio_src: str | None, output_path: str, fps: int = 30) -> dict:
        """FFmpeg 合成最终视频。"""
        return tools.mux_video(frames_dir, audio_src, output_path, fps=fps)

    agent = Agent(
        model=Ollama(id=model_id, host=ollama_host),
        tools=[extract_frames_tool, detect_tool, mask_tool, inpaint_tool, mux_tool],
        instructions=[
            "流程：抽帧 → 检测 → mask → 修复 → 时序平滑 → 合成",
            "每步必须确认输出有效再进入下一步",
            "检测失败自动降级：matchTemplate → YOLO → OCR",
            "修复失败自动降级：LaMa → cv2_telea",
            "GPU 显存不足自动切换到 CPU",
        ],
        markdown=True,
    )
    log.info("Agent 已构建: model=%s", model_id)
    return agent
