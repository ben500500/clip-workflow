# engines/seedance_wm/agent.py

- build_agent · function · L18-L71 — def build_agent(model_id: str = "qwen2.5:7b", ollama_host: str = "http://localhost:11434")
- extract_frames_tool · function · L32-L34 — def extract_frames_tool(video_path: str, output_dir: str) -> dict
- detect_tool · function · L37-L39 — def detect_tool(frames_dir: str, primary: str = "matchTemplate") -> dict
- mask_tool · function · L42-L44 — def mask_tool(bbox: dict, frame_count: int, width: int, height: int, output_dir: str) -> dict
- inpaint_tool · function · L47-L51 — def inpaint_tool( frames_dir: str, masks_dir: str, output_dir: str, device: str = "auto" ) -> dict
- mux_tool · function · L54-L56 — def mux_tool(frames_dir: str, audio_src: str | None, output_path: str, fps: int = 30) -> dict
