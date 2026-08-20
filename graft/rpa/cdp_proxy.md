# rpa/cdp_proxy.py · [[rpa-multi-operator-container]]

- _verify_token · function · L42-L67 — async def _verify_token(token: str, account_id: str) -> bool
- _pipe · function · L70-L85 — async def _pipe(src_reader, dst_writer)
- _read_head · function · L88-L101 — async def _read_head(reader) -> bytes
- _rewrite_request_host · function · L104-L114 — def _rewrite_request_host(header: bytes) -> bytes
- _extract_bearer · function · L117-L128 — def _extract_bearer(header: bytes) -> str
- _rewrite_response_body · function · L131-L135 — def _rewrite_response_body(body: bytes, orig_host: bytes) -> bytes
- _http_401 · function · L138-L144 — def _http_401(body: bytes = b"{\"error\":\"unauthorized\"}") -> bytes
- _handle · function · L147-L238 — async def _handle(target_port: int, require_auth: bool, account_id: str, client_reader, client_writer)
- main · function · L241-L282 — async def main(): # 多运营者模式：CDP_PROFILES = [{listen_port, target_port, account_id}] # 优先读 /app/profiles.json（bootstrap.py 落盘），其次读环境变量 CDP_PROFILES
