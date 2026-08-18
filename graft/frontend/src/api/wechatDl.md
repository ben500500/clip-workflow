# frontend/src/api/wechatDl.ts · [[frontend-api-client-layer]]

API client module for WeChat download tasks, providing endpoints for single/batch import, task listing, slicing, project import, and provider info.

- WechatDlTask · interface · L3-L20 — Data shape describing a WeChat download task with its status, progress, source metadata, and error info.
- WechatDlTaskList · interface · L22-L25 — Pagination wrapper holding a list of WeChat download tasks and the total count.
- WechatDlImportResult · interface · L27-L33 — Result of a single WeChat link import, reporting the created task id, status, and source authorization info.
- WechatDlBatchImportResult · interface · L35-L41 — Result of a batch WeChat import, summarizing created/skipped counts and per-item skip reasons.
- WechatDlImportInput · interface · L43-L48 — Input payload for importing a single WeChat source URL, with optional project and authorization note.
- WechatDlImportToProjectInput · interface · L50-L54 — Input for routing a downloaded task into a new or existing project, carrying the target project name or id.
- WechatDlImportToProjectResult · interface · L56-L60 — Result of routing a task into a project, returning the created project and episode ids.
- WechatDlProviderInfo · interface · L62-L71 — Metadata about a WeChat download provider including channel name, homepage, rechargeability, and balance.
