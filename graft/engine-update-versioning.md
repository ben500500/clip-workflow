---
name: Engine Update & Versioning
slug: engine-update-versioning
type: concept
sources:
  - path: scripts/sync-engines-to-worker.sh
    hash: 95b20e3f9b46d0cc958f3a2261639bf88f0958f9b105fc4e50ab6ede6f6854d6
  - path: slice-worker/engine_update_test.go
    hash: 519be92d75c872b6a6506e264dc61f6803a7039ad6af102cbe3686871e723001
  - path: slice-worker/engine_update.go
    hash: 59175cd03940a01762ab1ebbdced7caaf95e90a65e875fb5c955f62f49bc2f55
sources_digest: d240583b64d264ec92f5f3f128a0dbc677ffc92b3fbb1c0e18205dfd0a047873
links:
  - to: redis-task-coordination-contract
    relation: uses
    description: Update commands arrive as Redis instructions parsed by nodeUpdateCommand.
  - to: slice-worker-node
    relation: part_of
    description: Engine update is a subsystem of the worker node.
generator:
  version: 1
covers:
  - symbol: nodeUpdateCommand
    kind: struct
    at: 'slice-worker/engine_update.go:L33-L36'
  - symbol: ComputeEngineVersion
    kind: function
    at: 'slice-worker/engine_update.go:L41-L60'
  - symbol: listEngineFiles
    kind: function
    at: 'slice-worker/engine_update.go:L63-L89'
  - symbol: PullEngineUpdate
    kind: function
    at: 'slice-worker/engine_update.go:L95-L130'
  - symbol: extractTarGz
    kind: function
    at: 'slice-worker/engine_update.go:L134-L198'
  - symbol: readUpdateCommandJSON
    kind: function
    at: 'slice-worker/engine_update.go:L201-L210'
  - symbol: TestComputeEngineVersionStable
    kind: function
    at: 'slice-worker/engine_update_test.go:L12-L49'
  - symbol: TestExtractTarGz
    kind: function
    at: 'slice-worker/engine_update_test.go:L51-L70'
  - symbol: TestExtractTarGzPathTraversal
    kind: function
    at: 'slice-worker/engine_update_test.go:L72-L85'
---
<!-- context:generated:start -->
## Summary

The mechanism by which engine scripts are versioned and pushed to workers without redeployment. ComputeEngineVersion hashes all non-excluded files (SHA256, 12 hex chars) and must stay synchronized with the backend's `_ENGINE_EXCLUDE` list; the backend pushes update commands via Redis and serves tar.gz packages. Extraction is hardened against path traversal and uses atomic temp-file writes. The sync-engines-to-worker.sh script exists because the slice-worker Docker build context can't COPY the root engines/ dir, so it's copied in pre-build.

## Related

- uses [[redis-task-coordination-contract]] — Update commands arrive as Redis instructions parsed by nodeUpdateCommand.
- part of [[slice-worker-node]] — Engine update is a subsystem of the worker node.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
