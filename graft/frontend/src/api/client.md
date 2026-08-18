# frontend/src/api/client.ts · [[frontend-api-client-layer]]

Configures the shared axios HTTP client with automatic Bearer token injection and silent token-refresh on 401 responses, redirecting to login when refresh fails.

- refreshAccessToken · function · L27-L39 — Calls the auth refresh endpoint with credentials to obtain a new access token, returning null on any failure.
