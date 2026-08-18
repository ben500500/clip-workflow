---
name: Git Remote Sync
slug: git-remote-sync
type: file
sources:
  - path: scripts/sync_remotes.sh
    hash: e4a2c0ea76d9148f917a9d3985165af81986cc8acb2439ada4638f818d3e8473
sources_digest: 6552f04aab69cb38b8fd7031be5ef958562cb3c835412c117b7ec8cb599cf37f
links: []
generator:
  version: 1
covers: []
---
<!-- context:generated:start -->
## Summary

Pushes the current branch to the cnb primary remote first, then origin (GitHub) as backup, aborting if the primary fails so the backup never runs ahead. Pins HTTP/1.1 to avoid macOS Secure Transport HTTP/2 framing errors.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
