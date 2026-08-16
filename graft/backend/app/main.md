# backend/app/main.py

- ConnectionManager · class · L26-L52 — class ConnectionManager
- __init__ · method · L29-L30 — def __init__(self)
- connect · method · L32-L36 — async def connect(self, task_id: str, websocket: WebSocket)
- disconnect · method · L38-L42 — def disconnect(self, task_id: str, websocket: WebSocket)
- send_progress · method · L44-L52 — async def send_progress(self, task_id: str, progress: float, message: str = "")
- _create_seed_users · function · L65-L105 — async def _create_seed_users()
- _create_seed_platform_profiles · function · L108-L128 — async def _create_seed_platform_profiles()
- _create_seed_alert_rules · function · L131-L133 — async def _create_seed_alert_rules()
- lifespan · function · L137-L151 — async def lifespan(app: FastAPI)
- websocket_progress · function · L181-L190 — async def websocket_progress(websocket: WebSocket, task_id: str)
- websocket_wechat_dl · function · L194-L231 — async def websocket_wechat_dl(websocket: WebSocket, task_id: str)
- health_check · function · L255-L257 — async def health_check()
- health_check_detailed · function · L261-L264 — async def health_check_detailed()
