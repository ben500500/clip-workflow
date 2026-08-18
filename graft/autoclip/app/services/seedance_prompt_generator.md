# autoclip/app/services/seedance_prompt_generator.py · [[autoclip-auxiliary-services]]

- build_short_prompt · function · L69-L80 — def build_short_prompt(text: str, template: Optional[str] = None) -> str
- build_long_prompt · function · L83-L93 — def build_long_prompt(text: str, template: Optional[str] = None) -> str
- load_seedance_template · function · L96-L101 — def load_seedance_template() -> str
- _build_input · function · L104-L116 — def _build_input(text: str, duration: int, params: Optional[Dict[str, Any]]) -> Dict[str, Any]
- generate_seedance_prompt · function · L119-L137 — def generate_seedance_prompt( text: str, duration: int = 15, params: Optional[Dict[str, Any]] = None, max_retries: int = 3, ) -> str
- generate_prompt_versions · function · L140-L195 — def generate_prompt_versions( text: str, duration: int = 15, params: Optional[Dict[str, Any]] = None, max_retries: int = 3, templates: Optional[Dict[str, str]] = None, ) -> Dict[str, str]
- _normalize_duration · function · L198-L210 — def _normalize_duration(duration: int) -> int
- _ensure_compliance_footer · function · L221-L228 — def _ensure_compliance_footer(prompt: str) -> str
- _extract_prompt_text · function · L231-L258 — def _extract_prompt_text(raw: str) -> str
- _dict_to_prompt · function · L261-L276 — def _dict_to_prompt(data: Dict[str, Any]) -> str
