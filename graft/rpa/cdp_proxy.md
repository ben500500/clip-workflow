# rpa/cdp_proxy.py · [[rpa-multi-operator-infrastructure]]

CDP reverse proxy that rewrites Host headers to localhost to bypass Chromium's DNS-rebinding protection, and rewrites localhost back to the client's original host in JSON responses so Playwright's ws URLs reconnect through the proxy; supports multi-tenant auth via single-use Redis tokens.

- _verify_token · function · L42-L67 — Validates a cdp_proxy bearer token against Redis: checks existence, expiry, and account match, then consumes it (deletes) to prevent replay attacks.
- _pipe · function · L70-L85 — Bidirectional byte pump that forwards data from one stream to another until EOF or connection error.
- _read_head · function · L88-L101 — Reads exactly up to the \r\n\r\n header terminator without consuming the body, with a fallback loop for oversized or incomplete reads.
- _rewrite_request_host · function · L104-L114 — Rewrites the request's Host header to 'localhost' so Chromium's remote-debugging Host validation passes.
- _extract_bearer · function · L117-L128 — Parses the Authorization header to extract a Bearer token string.
- _rewrite_response_body · function · L131-L135 — Replaces 'localhost' occurrences in the response body with the client's original Host so ws URLs reconnect through the proxy.
- _http_401 · function · L138-L144 — Builds a minimal HTTP 401 Unauthorized JSON response.
- _handle · function · L147-L238 — Core proxy handler: authenticates requests (except /json/version health probe), rewrites Host to localhost, forwards to the target, rewrites localhost back in the body, adjusts Content-Length, and pipes WebSocket upgrades bidirectionally.
- main · function · L241-L282 — Boots the proxy: in multi-tenant mode reads CDP_PROFILES from /app/profiles.json or env and starts one authenticated listener per profile; otherwise falls back to a single unauthenticated listener.
