# backend/lan_source/config.py

- LanSourceConfig · class · L41-L74 — class LanSourceConfig
- __post_init__ · method · L53-L57 — def __post_init__(self) -> None: # 统一收尾：base 去掉尾部斜杠，prefix 去掉首尾斜杠
- to_public_dict · method · L59-L70 — def to_public_dict(self) -> dict
- to_db_dict · method · L72-L74 — def to_db_dict(self) -> dict
- _as_bool · function · L77-L86 — def _as_bool(value) -> bool
- _as_int · function · L89-L95 — def _as_int(value, default: int) -> int
- load_lan_source_config · function · L98-L175 — def load_lan_source_config( db_config: Optional[dict] = None, env: Optional[dict] = None, ) -> LanSourceConfig
- _env_get · function · L121-L128 — def _env_get(key: str)
