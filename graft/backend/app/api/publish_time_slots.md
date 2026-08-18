# backend/app/api/publish_time_slots.py · [[publish-tasks-scheduling]]

- PublishTimeSlotCreate · class · L38-L42 — Request schema for creating a custom publish time window.
- PublishTimeSlotUpdate · class · L45-L49 — Request schema for partially updating a custom publish time window.
- PublishTimeSlotResponse · class · L52-L62 — Response schema serializing a publish time window for API output.
- _serialize_slot · function · L65-L75 — Converts a PublishTimeSlot ORM object into the API response dict, normalizing defaults and timestamps.
- _validate_time_range · function · L78-L89 — Validates HH:MM time format and enforces start < end, rejecting cross-midnight windows to keep offset selection simple.
- list_publish_time_slots · function · L93-L103 — Lists all time windows ordered preset-first by start time, optionally filtering to enabled slots for the publish dialog.
- create_publish_time_slot · function · L107-L126 — Creates a new custom (non-preset) publish time window after validating its time range.
- update_publish_time_slot · function · L130-L158 — Partially updates a custom time window, forbidding edits to preset slots and re-validating the range when times change.
- delete_publish_time_slot · function · L162-L179 — Deletes a custom time window while blocking deletion of preset slots.
- resolve_scheduled_at · function · L182-L227 — Resolves a time window or explicit timestamp into a concrete UTC publish moment, picking a random point today (or tomorrow if today's window passed) to spread publishes.
- _random_in_window · function · L207-L216 — Picks a random minute within the window's start/end range on a given local day and converts it back to UTC for storage.
