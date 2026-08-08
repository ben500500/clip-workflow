"""Python SDK（API 文档 §4）。

    from seedance_wm import Remover, Config

    remover = Remover()
    result = remover.process('input.mp4', 'output.mp4')

    config = Config.from_yaml('./config.yaml')
    remover = Remover(config)
    results = remover.batch(input_dir='./in', output_dir='./out', workers=4)
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path

from seedance_wm.config import Config
from seedance_wm.ffmpeg_io import SUPPORTED_EXTENSIONS
from seedance_wm.log import get_logger
from seedance_wm.pipeline import ProcessResult, process_video

log = get_logger("remover")


@dataclass
class BatchResult:
    input_dir: str
    output_dir: str
    results: list[ProcessResult] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> list[ProcessResult]:
        return [r for r in self.results if not r.success]


class Remover:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()

    # ---------- 单文件 ----------
    def process(
        self,
        input_file: str,
        output_file: str,
        bbox: list[int] | None = None,
        bboxes: list[list[int]] | None = None,
    ) -> ProcessResult:
        return process_video(input_file, output_file, self.config, bbox=bbox, bboxes=bboxes)

    # ---------- 批量 ----------
    def batch(
        self,
        input_dir: str,
        output_dir: str,
        workers: int = 1,
        skip_existing: bool = False,
        retry_failed: int = 0,
        failed_log: str = "failed.log",
        extensions: list[str] | None = None,
    ) -> BatchResult:
        src = Path(input_dir)
        dst = Path(output_dir)
        if not src.exists():
            raise FileNotFoundError(f"输入目录不存在: {src}")
        dst.mkdir(parents=True, exist_ok=True)

        exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (extensions or [])}
        exts = exts or SUPPORTED_EXTENSIONS
        files = sorted(
            [p for p in src.iterdir() if p.is_file() and p.suffix.lower() in exts]
        )
        if not files:
            log.warning("输入目录中无匹配文件: %s (extensions=%s)", src, sorted(exts))

        log.info("批量处理开始: %d 个文件, workers=%d", len(files), workers)

        # 初始化失败日志
        flog = Path(failed_log)
        flog.parent.mkdir(parents=True, exist_ok=True)
        flog.write_text("", encoding="utf-8")

        results: list[ProcessResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {}
            for f in files:
                out = dst / f.name
                if skip_existing and out.exists():
                    r = ProcessResult(
                        input_file=str(f), output_file=str(out), success=True
                    )
                    r.error = "skipped (output exists)"
                    results.append(r)
                    continue
                future = executor.submit(self._process_one, f, out, retry_failed)
                future_map[future] = (f, out)

            for future in concurrent.futures.as_completed(future_map):
                f, out = future_map[future]
                try:
                    r = future.result()
                except Exception as e:  # noqa: BLE001
                    r = ProcessResult(input_file=str(f), output_file=str(out))
                    r.success = False
                    r.error = str(e)
                    r.exit_code = 10
                results.append(r)
                if not r.success:
                    flog.open("a", encoding="utf-8").write(f"{f}\t{r.error}\n")
                    log.error("批量失败: %s -> %s", f, r.error)
                else:
                    log.info("批量成功: %s -> %s", f, out)

        results.sort(key=lambda r: r.input_file)
        br = BatchResult(input_dir=str(src), output_dir=str(dst), results=results)
        log.info(
            "批量处理完成: 成功 %d/%d",
            br.success_count,
            len(br.results),
        )
        if br.failed:
            log.warning("失败 %d 个，详见 %s", len(br.failed), failed_log)
        return br

    def _process_one(self, src: Path, dst: Path, retry: int) -> ProcessResult:
        attempt = 0
        while True:
            try:
                return process_video(str(src), str(dst), self.config)
            except Exception as e:  # noqa: BLE001
                attempt += 1
                if attempt > retry:
                    r = ProcessResult(input_file=str(src), output_file=str(dst))
                    r.success = False
                    r.error = str(e)
                    r.exit_code = 10
                    return r
                log.warning("重试 %s (%d/%d): %s", src, attempt, retry, e)
