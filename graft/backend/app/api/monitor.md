# backend/app/api/monitor.py · [[maintenance-monitoring]]

- AlertRuleCreate · class · L38-L46 — Input schema for creating an alert rule, defaulting operator to '>', threshold to 0, and level to 'warning'.
- AlertRuleUpdate · class · L49-L57 — Input schema for partially updating an alert rule, with all fields optional so only provided fields are changed.
- AlertRuleResponse · class · L60-L73 — Output schema serializing an alert rule to the API client, with from_attributes mapping for ORM objects.
- AlertEventResponse · class · L76-L89 — Output schema serializing an alert event to the API client, with from_attributes mapping for ORM objects.
- AlertCheckResponse · class · L92-L96 — Output schema summarizing a manual alert-check run: counts of rules checked, triggered, notified, and any errors.
- _serialize_rule · function · L99-L112 — Converts an AlertRule ORM object into a plain dict for API responses, normalizing nullable fields to defaults.
- _serialize_event · function · L115-L128 — Converts an AlertEvent ORM object into a plain dict for API responses, normalizing nullable fields to defaults.
- health_check · function · L137-L139 — Endpoint delegating to the monitor service to report system health across database/Redis/MinIO/disk.
- get_monitor_metrics · function · L143-L145 — Endpoint delegating to the monitor service to collect current values of all monitored metrics.
- trigger_alert_check · function · L149-L153 — Admin-only endpoint that manually runs one round of alert checks against all rules.
- list_alert_rules · function · L157-L164 — Admin-only endpoint returning all alert rules ordered by creation time.
- get_alert_rule_meta · function · L168-L170 — Endpoint returning metric key/description pairs to populate the frontend rule-creation dropdown.
- create_alert_rule · function · L174-L184 — Admin-only endpoint that persists a new alert rule from the request payload and returns it.
- update_alert_rule · function · L188-L210 — Admin-only endpoint that validates the rule ID, applies only the provided fields to an existing rule, and bumps its updated_at timestamp.
- delete_alert_rule · function · L214-L232 — Admin-only endpoint that validates the rule ID and deletes the matching alert rule from the database.
- list_alert_events · function · L236-L249 — Admin-only endpoint returning recent alert events, optionally filtered by level and capped by a limit.
