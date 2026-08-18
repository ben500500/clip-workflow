# scripts/qr_render_spike.py · [[qr-spike-validation]]

R7 spike script that verifies whether headless Chromium can render and capture the WeChat login QR code via CDP, deciding between the CDP-QR-to-MinIO flow and the fallback local-browser+cookie-injection approach.

- run_spike · function · L27-L95 — Connects to a Chromium debug port via CDP, navigates to the WeChat creator login page, tries a list of selectors to screenshot a QR code, and returns 0 if a >=500-byte QR PNG is captured, 1 on failure, 2 if playwright is missing.
- main · function · L98-L110 — Parses CLI arguments (port/host/timeout) and runs the spike asyncio loop, mapping KeyboardInterrupt to exit code 130.
