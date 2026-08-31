# frontend/src/pages/Monitor.tsx · [[monitoring-alerting-dashboard]]

React page for the monitoring & alerting dashboard, rendering health checks, alert rules CRUD, current metrics, and alert event history, with a modal form to create/edit alert rules.

- HealthCheck · interface · L14-L18 — Type describing the health-check payload: overall status, service name, and per-check status/error/usage details.
- Monitor · function · L30-L336 — Main dashboard component that fetches all monitoring data in parallel and renders health cards, alert rule table, metrics table, and event log.
- openCreate · function · L67-L71 — Resets the form and opens the modal to create a new alert rule.
- openEdit · function · L73-L77 — Populates the form with an existing rule's values and opens the modal for editing.
- handleSave · function · L79-L94 — Validates the form and either creates or updates an alert rule via the API, then refreshes the dashboard.
- handleDelete · function · L96-L113 — Shows a confirmation dialog before deleting an alert rule via the API.
- onOk · method · L103-L111 — Performs the actual delete API call after user confirmation and refreshes the data.
- handleRunCheck · function · L115-L123 — Triggers an on-demand alert check via the API and reports how many alerts were triggered and notified.
