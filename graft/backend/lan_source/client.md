# backend/lan_source/client.py

- LanSourceError · class · L22-L23 — class LanSourceError(Exception)
- CdnEpisode · class · L26-L35 — class CdnEpisode
- __init__ · method · L31-L35 — def __init__(self, episode, url, title=None, size=None)
- ManageDrama · class · L38-L47 — class ManageDrama
- __init__ · method · L43-L47 — def __init__(self, name, drama_id=None, total=None, desc=None)
- LanSourceClient · class · L50-L149 — class LanSourceClient
- __init__ · method · L53-L60 — def __init__(self, config: Optional[LanSourceConfig] = None) -> None: # 未显式注入时回退到 settings(.env) 默认值，保证向后兼容
- _get_json · method · L62-L77 — async def _get_json(self, url: str, *, base: Optional[str] = None) -> dict
- discover_dramas · method · L80-L104 — async def discover_dramas(self) -> list[ManageDrama]
- _drama_path · method · L109-L113 — def _drama_path(self, drama_name: str) -> str
- fetch_episodes · method · L115-L149 — async def fetch_episodes(self, drama_name: str) -> list[CdnEpisode]
- get_client · function · L155-L160 — def get_client(config: Optional[LanSourceConfig] = None) -> LanSourceClient
