# scripts/cleanup_orphans.py

- human_size · function · L49-L55 — def human_size(n: int) -> str
- media_path_size · function · L58-L75 — def media_path_size(p: Path) -> int
- _collect_valid · function · L78-L102 — async def _collect_valid() -> tuple[set[str], set[str], set[str]]
- _scan_raw · function · L105-L113 — async def _scan_raw(valid_raw_keys: set[str]) -> tuple[list[dict], int]
- _scan_sliced · function · L116-L128 — async def _scan_sliced(valid_episode_ids: set[str]) -> tuple[list[dict], int]
- _scan_media · function · L131-L158 — def _scan_media(valid_media_ids: set[str]) -> tuple[list[tuple[Path, int]], int]
- _remove_media · function · L161-L173 — def _remove_media(p: Path) -> bool
- main · function · L176-L246 — async def main() -> int
