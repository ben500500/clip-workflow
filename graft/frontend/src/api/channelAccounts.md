# frontend/src/api/channelAccounts.ts · [[frontend-api-layer]]

API client module for channel account ledger CRUD and operator management, including one-click registration from the video account library.

- ChannelAccountInput · interface · L4-L17 — Payload shape for creating/updating a channel account ledger entry, carrying channel identity, verification, cooperation mode, and optional binding to an existing video account.
- ChannelAccountFromVideoAccountInput · interface · L19-L29 — Payload for registering a ledger entry directly from an existing video account, auto-filling name/wechat id and making the account owner the first operator.
- OperatorInput · interface · L31-L35 — Payload for adding or updating an operator, supporting either an existing user id or externally hand-entered name and phone.
