# backend/app/api/monitor.py · [[maintenance-monitoring]]

- AlertRuleCreate · class · L38-L46 — class AlertRuleCreate(BaseModel)
- AlertRuleUpdate · class · L49-L57 — class AlertRuleUpdate(BaseModel)
- AlertRuleResponse · class · L60-L73 — class AlertRuleResponse(BaseModel)
- AlertEventResponse · class · L76-L89 — class AlertEventResponse(BaseModel)
- AlertCheckResponse · class · L92-L96 — class AlertCheckResponse(BaseModel)
- _serialize_rule · function · L99-L112 — def _serialize_rule(rule: AlertRule) -> dict
- _serialize_event · function · L115-L128 — def _serialize_event(event: AlertEvent) -> dict
- health_check · function · L137-L139 — async def health_check()
- get_monitor_metrics · function · L143-L145 — async def get_monitor_metrics()
- trigger_alert_check · function · L149-L153 — async def trigger_alert_check( current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], )
- list_alert_rules · function · L157-L164 — async def list_alert_rules( current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], db: AsyncSession = Depends(get_db), )
- get_alert_rule_meta · function · L168-L170 — async def get_alert_rule_meta()
- create_alert_rule · function · L174-L184 — async def create_alert_rule( data: AlertRuleCreate, current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], db: AsyncSession = Depends(get_db), )
- update_alert_rule · function · L188-L210 — async def update_alert_rule( rule_id: str, data: AlertRuleUpdate, current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], db: AsyncSession = Depends(get_db), )
- delete_alert_rule · function · L214-L232 — async def delete_alert_rule( rule_id: str, current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], db: AsyncSession = Depends(get_db), )
- list_alert_events · function · L236-L249 — async def list_alert_events( current_user: Annotated[Any, Depends(require_roles(UserRole.admin))], level: Optional[str] = Query(None), limit: int = Query(50, le=200), db: AsyncSession = Depends(get_db), )
