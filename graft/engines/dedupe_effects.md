# engines/dedupe_effects.py

- _sprite_available · function · L52-L60 — def _sprite_available() -> bool
- _write_png · function · L63-L68 — def _write_png(path: str, rgba: "np.ndarray") -> None
- generate_star_sprite · function · L71-L92 — def generate_star_sprite(size: int = DEFAULT_SPRITE) -> str
- build_sparkle_filter · function · L95-L153 — def build_sparkle_filter( cfg: dict, width: int = 0, height: int = 0, base_path: str | None = None, ) -> list[str]
- _build_pos_expression · function · L156-L177 — def _build_pos_expression(positions: list[tuple[float, float]], interval: float) -> tuple[str, str]
- chain · function · L163-L174 — def chain(series: list[tuple[float, float]]) -> str
- build_face_watermark_filter · function · L180-L269 — def build_face_watermark_filter( cfg: dict, video_path: str, width: int = 0, height: int = 0, ) -> str | None
- _chain_expr · function · L272-L283 — def _chain_expr(series: list[tuple[float, float]]) -> str
- _ffprobe_size · function · L286-L300 — def _ffprobe_size(path: str) -> tuple[int, int] | None
- _fps_approx · function · L303-L324 — def _fps_approx(path: str) -> float
- _resolve_font · function · L327-L338 — def _resolve_font() -> str
- crop_inpaint_roi · function · L341-L372 — def crop_inpaint_roi(image, mask, radius=3)
