# autoclip/app/core/ollama_client.py · [[llm-manager-provider-abstraction]]

- OllamaClient · class · L32-L142 — class OllamaClient
- __init__ · method · L35-L37 — def __init__(self, host: Optional[str] = None, model: Optional[str] = None)
- available · method · L40-L52 — def available(self) -> bool
- describe_image · method · L54-L104 — def describe_image(self, image_bytes: bytes, prompt: str) -> Optional[Dict[str, Any]]
- _parse_json · method · L107-L142 — def _parse_json(raw: str) -> Optional[Dict[str, Any]]
- get_ollama_client · function · L149-L154 — def get_ollama_client() -> OllamaClient
