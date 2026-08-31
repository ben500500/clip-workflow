# slice-worker/engine_update.go · [[engine-update-versioning]] [[slice-worker-node]]

Engine update module: computes a content-hash engine version, lists distributable files excluding caches, pulls and safely extracts tar.gz engine packages from the backend, and parses Redis update commands.

- nodeUpdateCommand · struct · L33-L36 — Data holder for the Redis node-update command payload (target version and requested time).
- ComputeEngineVersion · function · L41-L60 — Computes a deterministic engine version by hashing relative paths and contents of all deployable files, taking the first 12 hex chars of the SHA256.
- listEngineFiles · function · L63-L89 — Recursively enumerates regular files under the engine directory, skipping excluded cache/build/doc entries and sorting results for deterministic ordering.
- PullEngineUpdate · function · L95-L130 — Downloads the latest engine tar.gz package from the backend over HTTP, extracts it into the engine directory, and returns the resulting new version.
- extractTarGz · function · L134-L198 — Safely extracts a tar.gz byte stream into a destination directory, blocking path traversal and writing files atomically via temp-file rename.
- readUpdateCommandJSON · function · L201-L210 — Parses a Redis update command JSON string and rejects commands that lack a target version.
