# autoclip/app/services/seedance_prompt_generator.py · [[seedance-prompt-generation]]

- build_short_prompt · function · L69-L80 — Builds the short prompt by substituting the user's script text into the fixed short template, appending the placeholder if missing.
- build_long_prompt · function · L83-L93 — Builds the long prompt by substituting the user's script text into the fixed long template, appending the placeholder if missing.
- load_seedance_template · function · L96-L101 — Loads the Seedance role-prompt template file from disk, returning empty string with a warning if missing.
- _build_input · function · L104-L116 — Assembles frontend params into the model input dict, applying defaults for theme/tone and enforcing the compliance rule that real names must be replaced with aliases.
- generate_seedance_prompt · function · L119-L137 — Convenience wrapper that generates all three prompt versions and returns only the AI-generated prompt.
- generate_prompt_versions · function · L140-L195 — Orchestrates generation of all three prompt versions: builds long/short from templates without LLM, and calls the LLM for the AI version, then normalizes duration, extracts text, and appends the compliance footer.
- _normalize_duration · function · L198-L210 — Normalizes the requested duration to an integer within 3-300 seconds, falling back to 15s for invalid or out-of-range input.
- _ensure_compliance_footer · function · L221-L228 — Idempotently appends the compliance confirmation sentence to the end of the prompt if not already present.
- _extract_prompt_text · function · L231-L258 — Extracts the prompt body from the model's raw response, stripping markdown fences and parsing JSON wrappers with known keys or falling back to raw text.
- _dict_to_prompt · function · L261-L276 — Concatenates model-returned field dicts into the seven-section Seedance prompt structure, skipping empty sections.
