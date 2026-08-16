# backend/app/services/monitor_service.py

- ensure_default_alert_rules · function · L66-L76 — async def ensure_default_alert_rules() -> None
- _get_redis · function · L84-L86 — async def _get_redis() -> Any
- collect_metrics · function · L89-L158 — async def collect_metrics() -> dict[str, float]
- send_dingtalk_alert · function · L166-L189 — async def send_dingtalk_alert(webhook_url: str, level: str, message: str) -> tuple[bool, str]
- _evaluate · function · L197-L211 — def _evaluate(operator: str, current: float, threshold: float) -> bool
- _format_metric_value · function · L214-L222 — def _format_metric_value(value) -> str
- run_alert_checks · function · L225-L285 — async def run_alert_checks() -> dict
- check_health · function · L293-L346 — async def check_health() -> dict
