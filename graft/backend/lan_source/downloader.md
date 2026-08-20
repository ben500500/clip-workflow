# backend/lan_source/downloader.py

- LanSourceDownloadError · class · L19-L20 — class LanSourceDownloadError(Exception)
- LanSourceDownloader · class · L23-L64 — class LanSourceDownloader
- __init__ · method · L26-L29 — def __init__(self, config: Optional[LanSourceConfig] = None) -> None
- download_to_file · method · L31-L64 — async def download_to_file(self, url: str, local_path: str) -> int
- get_downloader · function · L70-L74 — def get_downloader(config: Optional[LanSourceConfig] = None) -> LanSourceDownloader
- probe_file_size · function · L77-L90 — async def probe_file_size(url: str) -> Optional[int]
- run_bounded_downloads · function · L93-L115 — async def run_bounded_downloads(url_path_pairs: list[tuple[str, str]], concurrency: Optional[int] = None) -> list[str]
- _one · function · L105-L113 — async def _one(pair)
