# autoclip/app/utils/llm_client.py

- LLMCallError · class · L38-L43 — class LLMCallError(RuntimeError)
- LLMClient · class · L46-L280 — class LLMClient
- __init__ · method · L49-L51 — def __init__(self)
- call · method · L53-L68 — def call(self, prompt: str, input_data: Any = None) -> str
- call_with_retry · method · L70-L86 — def call_with_retry(self, prompt: str, input_data: Any = None, max_retries: int = 3) -> str
- _preprocess_llm_response · method · L88-L112 — def _preprocess_llm_response(self, response: str) -> str
- _auto_fix_response · method · L114-L125 — def _auto_fix_response(self, response: str) -> str
- _validate_json_structure · method · L127-L152 — def _validate_json_structure(self, parsed_data: Any) -> bool
- parse_json_response · method · L154-L276 — def parse_json_response(self, response: str) -> Any
- sanitize_string · function · L165-L173 — def sanitize_string(s: str) -> str
- fix_common_json_errors · function · L175-L219 — def fix_common_json_errors(json_str: str) -> str
- get_current_provider_info · method · L278-L280 — def get_current_provider_info(self) -> Dict[str, Any]
