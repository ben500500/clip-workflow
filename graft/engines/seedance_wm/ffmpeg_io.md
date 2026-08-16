# engines/seedance_wm/ffmpeg_io.py

- check_ffmpeg · function · L32-L36 — def check_ffmpeg() -> None
- _parse_rational · function · L39-L47 — def _parse_rational(value: str) -> float
- VideoMeta · class · L51-L57 — class VideoMeta
- probe_video · function · L60-L95 — def probe_video(video_path: str | Path) -> VideoMeta
- extract_frames · function · L98-L161 — def extract_frames( video_path: str | Path, output_dir: str | Path, fps: float | None = None, threads: int = 0, ) -> dict
- mux_video · function · L164-L228 — def mux_video( frames_dir: str | Path, audio_src: str | Path | None, output_path: str | Path, fps: int | float = 30, crf: int = 18, codec: str = "libx264", pix_fmt: str = "yuv420p", movflags: str = "+faststart", keep_audio: bool = True, ) -> dict
- get_available_disk_gb · function · L231-L234 — def get_available_disk_gb(path: str | Path) -> float
- run_cmd · function · L237-L238 — def run_cmd(args: list[str]) -> subprocess.CompletedProcess
