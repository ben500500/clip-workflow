# backend/app/models/monitor.py · [[audit-observability]] [[orm-model-registry]]

- WorkerNode · class · L25-L55 — ORM model registering worker node metadata (host, capabilities, heartbeat) and operational state (enabled, cpu_percent, status, task counters) used for task dispatch and health tracking.
- __repr__ · method · L54-L55 — Debug string representation of a worker node showing its node_id and status.
- AlertRule · class · L58-L80 — ORM model defining alert rules that pair a monitored metric with an operator, threshold, and severity level to drive the monitoring/alerting system.
- __repr__ · method · L79-L80 — Debug string representation of an alert rule showing its id, metric, and threshold.
- AlertEvent · class · L83-L103 — ORM model recording each alert trigger occurrence with its rule reference, metric, level, current value, and notification status.
- __repr__ · method · L102-L103 — Debug string representation of an alert event showing its id, rule name, and level.
- RiskEvent · class · L106-L127 — ORM model recording risk-control restriction events (login_restricted, publish_limited, captcha, ban, etc.) with disposition and linked account/operator/actor, feeding graduation-threshold statistics.
- __repr__ · method · L126-L127 — Debug string representation of a risk event showing its id, risk type, and account.
