# backend/dupload/client.py

- DuploadError · class · L44-L45 — class DuploadError(Exception)
- DuploadClient · class · L48-L205 — class DuploadClient
- __init__ · method · L51-L61 — def __init__(self, config: Optional[DuploadConfig] = None) -> None
- _get_hosts · method · L63-L98 — async def _get_hosts(self) -> list
- _resolve_targets · method · L100-L109 — async def _resolve_targets(self) -> list
- push_task · method · L111-L205 — async def push_task(self, drama_name: str, share_url: str) -> dict
- _post · function · L165-L196 — async def _post(host: str) -> dict
- get_client · function · L211-L216 — def get_client(config: Optional[DuploadConfig] = None) -> DuploadClient
