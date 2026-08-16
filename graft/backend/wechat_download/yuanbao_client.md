# backend/wechat_download/yuanbao_client.py

- ParseResult · class · L27-L38 — class ParseResult
- YuanbaoParseError · class · L41-L42 — class YuanbaoParseError(Exception)
- YuanbaoClient · class · L45-L124 — class YuanbaoClient
- __init__ · method · L52-L61 — def __init__(self) -> None
- close · method · L63-L64 — async def close(self) -> None
- parse · method · L66-L95 — async def parse(self, share_url: str) -> ParseResult
- _normalize · method · L97-L124 — def _normalize(self, data: dict, raw: str = "") -> ParseResult
- get_yuanbao_client · function · L131-L135 — def get_yuanbao_client() -> YuanbaoClient
