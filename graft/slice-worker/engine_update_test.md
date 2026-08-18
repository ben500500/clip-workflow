# slice-worker/engine_update_test.go

Test file covering engine version computation determinism and tar.gz extraction safety, including path traversal protection.

- TestComputeEngineVersionStable · function · L12-L49 — Verifies ComputeEngineVersion is deterministic for identical content, changes with content changes, and ignores cache directories.
- TestExtractTarGz · function · L51-L70 — Verifies extractTarGz correctly decompresses a gzipped tar archive into the destination directory with proper file contents.
- TestExtractTarGzPathTraversal · function · L72-L85 — Verifies extractTarGz rejects archive entries containing path traversal sequences like ../.
