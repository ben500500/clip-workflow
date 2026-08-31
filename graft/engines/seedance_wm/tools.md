# engines/seedance_wm/tools.py · [[seedance-wm-engine]]

Agent tool registration layer exposing 5 atomic watermark-removal operations (extract, detect, mask, inpaint, smooth, mux) plus metadata probing for Agno Agent registration.

- extract_frames · function · L15-L26 — Delegates frame extraction and audio separation to the ffmpeg_io backend, exposing a thin agent-callable wrapper.
- detect_watermark · function · L29-L42 — Delegates watermark detection with an automatic fallback chain to the detect module, exposing it as an agent tool.
- generate_mask_sequence · function · L45-L51 — Delegates bbox-to-frame-mask PNG sequence generation to the mask module as an agent tool.
- inpaint_frames · function · L54-L65 — Delegates per-frame inpainting plus inter-frame smoothing to the inpaint module as an agent tool.
- temporal_smooth · function · L68-L72 — Delegates in-place weighted frame averaging to the inpaint module's temporal_smooth as an agent tool.
- mux_video · function · L75-L83 — Delegates final FFmpeg video composition to the ffmpeg_io backend as an agent tool.
- video_meta · function · L86-L96 — Probes a video and reshapes its metadata into a flat dict of fps, dimensions, duration, audio presence, and frame count for agent consumption.
