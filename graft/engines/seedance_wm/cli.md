# engines/seedance_wm/cli.py · [[video-processing-engines]]

- _parse_bbox · function · L52-L62 — def _parse_bbox(text: str) -> list[int] | None
- build_parser · function · L65-L113 — def build_parser() -> argparse.ArgumentParser
- _apply_cli_overrides · function · L116-L143 — def _apply_cli_overrides(config: Config, args: argparse.Namespace) -> None
- _confirm_disclaimer · function · L146-L152 — def _confirm_disclaimer() -> bool
- _print_metrics · function · L155-L168 — def _print_metrics(result) -> None
- run · function · L171-L243 — def run(args: argparse.Namespace) -> int: # 加载配置
- main · function · L246-L253 — def main(argv: list[str] | None = None) -> int
