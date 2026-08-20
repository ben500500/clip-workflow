# backend/app/api/dedupe.py

- _resolve_engines_dir · function · L203-L206 — def _resolve_engines_dir() -> str
- _load_dedupe_presets · function · L209-L227 — def _load_dedupe_presets() -> dict
- _dedupe_presets_payload · function · L230-L239 — def _dedupe_presets_payload() -> dict
- get_dedupe_presets · function · L243-L247 — def get_dedupe_presets( current_user: Annotated[User, Depends(get_current_user)] = None, )
- upload_dedupe_video · function · L251-L303 — async def upload_dedupe_video( file: UploadFile = File(...), current_user: Annotated[User, Depends(get_current_user)] = None, )
