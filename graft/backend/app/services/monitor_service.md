# backend/app/services/monitor_service.py · [[monitoring-alerting-service]]

- ensure_default_alert_rules · function · L66-L76 — async def ensure_default_alert_rules() -> None
- _get_redis · function · L84-L87 — async def _get_redis() -> Any
- collect_metrics · function · L90-L157 — async def collect_metrics() -> dict[str, float]
- send_dingtalk_alert · function · L165-L188 — async def send_dingtalk_alert(webhook_url: str, level: str, message: str) -> tuple[bool, str]
- _evaluate · function · L196-L210 — def _evaluate(operator: str, current: float, threshold: float) -> bool
- _format_metric_value · function · L213-L221 — def _format_metric_value(value) -> str
- run_alert_checks · function · L224-L284 — async def run_alert_checks() -> dict
- check_health · function · L292-L343 — async def check_health() -> dict
