# engines/seedance_wm/remover.py · [[seedance-wm-engine]]

Public SDK entry point exposing single-file and batch watermark removal via the Remover class and Config.

- BatchResult · class · L28-L39 — Aggregates per-file processing outcomes for a batch run, exposing success counts and failed results.
- success_count · method · L34-L35 — Counts how many processed files succeeded.
- failed · method · L38-L39 — Filters out the list of results that did not succeed.
- Remover · class · L42-L143 — Facade that orchestrates single-file and parallel batch watermark removal over a directory of media files.
- __init__ · method · L43-L44 — Stores the processing configuration, defaulting to a fresh Config when none is supplied.
- process · method · L47-L54 — Delegates a single input/output file pair to the underlying pipeline for watermark removal.
- batch · method · L57-L128 — Discovers matching media files in a directory and processes them concurrently, honoring skip-existing and retry policies while logging failures.
- _process_one · method · L130-L143 — Runs watermark removal on one file with bounded retries, returning a failure result once retries are exhausted.
