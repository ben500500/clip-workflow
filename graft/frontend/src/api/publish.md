# frontend/src/api/publish.ts · [[frontend-api-client-layer]]

API client module exposing all publish-domain endpoints (task CRUD, scheduling, video accounts, batches, mini-programs, audit, login QR) via a single publishApi object.

- PublishTaskCreate · interface · L4-L22 — Payload shape for creating a publish task, supporting either a time-slot window or a specific scheduled time for timed publishing.
- PublishTaskScheduleInput · interface · L24-L29 — Input for rescheduling a task, allowing a new time, a time slot, immediate publish, or cancellation.
- PublishTimeSlotInput · interface · L31-L36 — Payload for creating/updating a named time window with start/end times and an enabled flag.
- VideoAccountInput · interface · L38-L51 — Payload for creating/updating a video account, including its publish-jump target (native vs mini-program) and operator assignment.
- PublishTaskAssignInput · interface · L53-L64 — Payload for assigning a publish task to accounts/operators with a routing strategy for multi-operator batches.
- MiniProgramInput · interface · L66-L73 — Payload for creating/updating a mini-program link entry in the link library.
