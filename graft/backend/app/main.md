# backend/app/main.py · [[fastapi-application-wiring]]

- _create_seed_users · function · L33-L73 — Creates seed users from SEED_USERS_JSON env var only in DEBUG mode, skipping existing usernames to avoid weak-password accounts in production.
- _create_seed_platform_profiles · function · L76-L96 — Idempotently preloads default platform dedupe profiles (video/douyin/kuaishou) into the database if they don't already exist.
- _create_seed_alert_rules · function · L99-L101 — Idempotently ensures default alert rules exist by delegating to the monitor service.
- lifespan · function · L105-L119 — Application lifecycle hook that initializes the database and seeds users, platform profiles, and alert rules on startup, then closes DB on shutdown.
- websocket_wechat_dl · function · L149-L186 — Streams wechat-download task progress to the frontend by subscribing to a Redis pub/sub channel and forwarding messages filtered by task_id.
- health_check · function · L215-L217 — Lightweight health endpoint returning a static ok status for Docker healthchecks.
- health_check_detailed · function · L221-L224 — Enhanced health check that delegates to the monitor service to verify database/Redis/MinIO/disk status.
