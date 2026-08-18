# backend/wechat_download/downloader.py · [[wechat-download-pipeline]]

- DownloadError · class · L26-L27 — class DownloadError(Exception)
- WechatDownloader · class · L30-L119 — class WechatDownloader
- __init__ · method · L33-L35 — def __init__(self) -> None
- download_to_file · method · L37-L47 — async def download_to_file(self, play_url: str, local_path: str) -> int
- _download_direct · method · L49-L81 — async def _download_direct(self, url: str, local_path: str) -> int
- _download_hls · method · L83-L119 — async def _download_hls(self, master_url: str, local_path: str) -> int
- get_downloader · function · L125-L129 — def get_downloader() -> WechatDownloader
