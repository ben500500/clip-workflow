# autoclip/app/core/vision_llm_client.py

- VisionLLMClient · class · L29-L159 — class VisionLLMClient
- __init__ · method · L32-L40 — def __init__( self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None, )
- available · method · L43-L51 — def available(self) -> bool
- describe_image · method · L53-L124 — def describe_image(self, image_bytes: bytes, prompt: str) -> Optional[Dict[str, Any]]
- _parse_json · method · L127-L159 — def _parse_json(raw: str) -> Optional[Dict[str, Any]]
- get_vision_llm_client · function · L166-L171 — def get_vision_llm_client() -> VisionLLMClient
