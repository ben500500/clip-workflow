# engines/tests/test_subtitle_mask_regression.py · [[subtitle-mask-regression-test]]

Regression test suite that synthesizes a video+SRT and verifies PR #148 acceptance criteria: dynamic mask region height ≤9% screen height and source subtitle text density drop ≥60%.

- _have · function · L47-L48 — Checks whether a CLI tool is available on PATH to decide if the test can run.
- _have_py · function · L51-L56 — Checks whether a Python module can be imported to decide if the test can run.
- make_video · function · L59-L83 — Synthesizes a test video with a persistent gold subtitle overlay using ffmpeg lavfi color source and drawtext filter.
- make_srt · function · L86-L92 — Writes a 3-window SRT file whose subtitle text spans multiple time windows to exercise dynamic region detection.
- run · function · L95-L102 — Runs a subprocess command, returning success and printing stderr tail on failure.
- text_density · function · L105-L126 — Extracts a frame at a timestamp and computes the fraction of gold/white subtitle-colored pixels inside a given box, mirroring slice.py's detect color logic.
- main · function · L129-L198 — Orchestrates the two acceptance tests: asserts detected dynamic regions stay ≤9% screen height and that applying the mask filter drops subtitle text density ≥60%.
