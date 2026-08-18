# backend/app/services/ark_client.py · [[short-drama-generation-channels]]

- _normalize_bool · function · L56-L64 — def _normalize_bool(value) -> bool
- SeedanceConfig · class · L67-L127 — class SeedanceConfig
- __init__ · method · L86-L107 — def __init__( self, *, enabled: bool = False, api_key: str = "", model: str = "seedance-1-0-pro-250528", resolution: str = "1080p", watermark: bool = True, long_duration_policy: str = LONG_DURATION_POLICY_TRUNCATE, api_base: str = ARK_BASE, timeout: int = 600, daily_quota: int = 0, )
- to_public_dict · method · L109-L121 — def to_public_dict(self) -> dict
- validate · method · L123-L127 — def validate(self) -> Optional[str]
- load_seedance_config · function · L130-L182 — def load_seedance_config(env: Optional[dict] = None, db_config: Optional[dict] = None) -> SeedanceConfig
- SeedanceClient · class · L185-L298 — class SeedanceClient
- __init__ · method · L188-L189 — def __init__(self, config: SeedanceConfig)
- _base · method · L191-L192 — def _base(self) -> str
- _headers · method · L194-L198 — def _headers(self) -> dict
- _task_url · method · L200-L201 — def _task_url(self, task_id: str) -> str
- _cancel_url · method · L203-L204 — def _cancel_url(self, task_id: str) -> str
- create_task · method · L210-L252 — async def create_task( self, prompt: str, *, duration: int = 10, resolution: Optional[str] = None, watermark: Optional[bool] = None, seed: int = 0, fps: int = 24, ) -> dict
- get_task · method · L258-L283 — async def get_task(self, task_id: str) -> dict
- cancel_task · method · L289-L298 — async def cancel_task(self, task_id: str) -> dict
- resolve_duration_policy · function · L301-L316 — async def resolve_duration_policy(config: SeedanceConfig, duration: int) -> tuple[int, Optional[str]]
- poll_task · function · L319-L379 — async def poll_task( client: SeedanceClient, task_id: str, *, progress_cb=None, cancel_check=None, poll_interval: float = 5.0, timeout: Optional[int] = None, ) -> dict
