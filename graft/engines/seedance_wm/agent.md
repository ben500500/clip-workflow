# engines/seedance_wm/agent.py · [[video-processing-engines]]

- build_agent · function · L18-L71 — Lazily constructs an Agno Agent that chains the five watermark-removal tools with fallback and validation instructions, raising a clear error if agent deps are missing.
- extract_frames_tool · function · L32-L34 — Exposes frame extraction as an Agno tool by delegating to the core extract_frames function.
- detect_tool · function · L37-L39 — Exposes watermark detection as an Agno tool by delegating to the core detect_watermark function.
- mask_tool · function · L42-L44 — Exposes mask sequence generation as an Agno tool by delegating to the core generate_mask_sequence function.
- inpaint_tool · function · L47-L51 — Exposes frame inpainting with device selection as an Agno tool by delegating to the core inpaint_frames function.
- mux_tool · function · L54-L56 — Exposes final video muxing as an Agno tool by delegating to the core mux_video function.
