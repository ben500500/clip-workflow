---
name: Worker Packaging & Deployment
slug: worker-packaging-deployment
type: system
sources:
  - path: slice-worker/macos/build_mac.sh
    hash: 0f5ac41c41a794f0047630176946b4fcf4a24555ab6bbf6d181b1dfcbaf84637
  - path: slice-worker/macos/launchd_worker.sh
    hash: a56be874578d7ae002b2a20097b63aa6a9be69284303507161b739318f930004
  - path: slice-worker/macos/manage_worker.sh
    hash: 0aefdfaae7e585c1aa09da09ef9ea3d2ca695ddbb92240eb91589b254a7b4a67
  - path: slice-worker/ubuntu/build_package.sh
    hash: ffaa306a0945e020c9e256d8ce39e3a9fa13cdd3f231dfaee9e5c90ed6b3de3f
  - path: slice-worker/ubuntu/deploy_ubuntu.sh
    hash: 6f7f31649b776481e70c179395b73307c9629d46a868cee815a0dc870bbbd06f
sources_digest: efd815d6b6cba9fff947d840bfc3e9f7b7f3debc70d3add3dd5849a98f8a756e
links:
  - to: engine-update-versioning
    relation: uses
    description: >-
      Packages bundle the engines/ directory so workers can run before any
      update is pushed.
  - to: slice-worker-node
    relation: configures
    description: Generate worker.json config and register the binary with launchd/systemd.
generator:
  version: 1
covers: []
---
<!-- context:generated:start -->
## Summary

The build and deployment tooling for shipping the worker to macOS and Ubuntu targets: build_mac.sh (cgo build for the Cocoa tray, launchd login item), manage_worker.sh (launchctl lifecycle with bootstrap/bootout), build_package.sh (static CGO_ENABLED=0 tarballs bundling engines), and deploy_ubuntu.sh (systemd service, dependency install, worker.json generation). These are offline/self-contained deployment paths distinct from the Docker Compose stack.

## Related

- uses [[engine-update-versioning]] — Packages bundle the engines/ directory so workers can run before any update is pushed.
- configures [[slice-worker-node]] — Generate worker.json config and register the binary with launchd/systemd.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
