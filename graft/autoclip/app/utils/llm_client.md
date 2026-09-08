# autoclip/app/utils/llm_client.py · [[llm-manager-client-compatibility]]

- LLMCallError · class · L38-L43 — class LLMCallError(RuntimeError)
- _escape_in_string_quotes · function · L46-L83 — def _escape_in_string_quotes(json_str: str) -> str
- LLMClient · class · L86-L330 — class LLMClient
- __init__ · method · L89-L91 — def __init__(self)
- call · method · L93-L108 — def call(self, prompt: str, input_data: Any = None) -> str
- call_with_retry · method · L110-L126 — def call_with_retry(self, prompt: str, input_data: Any = None, max_retries: int = 3) -> str
- _preprocess_llm_response · method · L128-L152 — def _preprocess_llm_response(self, response: str) -> str
- _auto_fix_response · method · L154-L165 — def _auto_fix_response(self, response: str) -> str
- _validate_json_structure · method · L167-L192 — def _validate_json_structure(self, parsed_data: Any) -> bool
- parse_json_response · method · L194-L326 — def parse_json_response(self, response: str) -> Any
- sanitize_string · function · L205-L213 — def sanitize_string(s: str) -> str
- fix_common_json_errors · function · L215-L269 — def fix_common_json_errors(json_str: str) -> str
- get_current_provider_info · method · L328-L330 — def get_current_provider_info(self) -> Dict[str, Any]
