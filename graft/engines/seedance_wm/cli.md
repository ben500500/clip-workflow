# engines/seedance_wm/cli.py · [[seedance-watermark-removal-engine]]

- _parse_bbox · function · L52-L62 — def _parse_bbox(text: str) -> list[int] | None
- build_parser · function · L65-L112 — def build_parser() -> argparse.ArgumentParser
- _apply_cli_overrides · function · L115-L140 — def _apply_cli_overrides(config: Config, args: argparse.Namespace) -> None
- _confirm_disclaimer · function · L143-L149 — def _confirm_disclaimer() -> bool
- _print_metrics · function · L152-L165 — def _print_metrics(result) -> None
- run · function · L168-L240 — def run(args: argparse.Namespace) -> int: # 加载配置
- main · function · L243-L250 — def main(argv: list[str] | None = None) -> int
