# eval/grade_highlight_llm.py · [[autoclip-llm-evaluation-harness]]

- time_to_seconds · function · L37-L48 — def time_to_seconds(s: str) -> float
- srt_block_end · function · L51-L57 — def srt_block_end(srt_text: str) -> float
- load_prompt · function · L60-L62 — def load_prompt(path: str) -> str
- extract_json · function · L65-L92 — def extract_json(text: str)
- call_llm · function · L98-L123 — def call_llm(prompt_text: str, input_obj, model: str, api_key: str, temperature: float = 0.2)
- iou · function · L129-L132 — def iou(a_s, a_e, b_s, b_e)
- grade_timeline · function · L135-L213 — def grade_timeline(case, pred, cfg)
- grade_scoring · function · L216-L276 — def grade_scoring(case, pred, cfg)
- _is_num · function · L279-L284 — def _is_num(x)
- main · function · L290-L348 — def main()
