# autoclip/app/core/vision_llm_client.py

- VisionLLMClient · class · L30-L160 — class VisionLLMClient
- __init__ · method · L33-L41 — def __init__( self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None, )
- available · method · L44-L52 — def available(self) -> bool
- describe_image · method · L54-L125 — def describe_image(self, image_bytes: bytes, prompt: str) -> Optional[Dict[str, Any]]
- _parse_json · method · L128-L160 — def _parse_json(raw: str) -> Optional[Dict[str, Any]]
- get_vision_llm_client · function · L167-L172 — def get_vision_llm_client() -> VisionLLMClient
