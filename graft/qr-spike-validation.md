---
name: QR Spike Validation
slug: qr-spike-validation
type: file
sources:
  - path: scripts/qr_render_spike.py
    hash: 1ac4ad6ef2c1b75e981d23c0fd8add47d01eeae962cf58e7a9f686524f9849d0
sources_digest: 9f2f605b4931ffc8610ba004a724b5fa1da495e42856ec753658bca6adbe0eb1
links:
  - to: deployment-ops-scripts
    relation: part_of
    description: Lives in scripts/ as a validation artifact for a planned feature.
generator:
  version: 1
covers:
  - symbol: run_spike
    kind: function
    at: 'scripts/qr_render_spike.py:L27-L95'
  - symbol: main
    kind: function
    at: 'scripts/qr_render_spike.py:L98-L110'
---
<!-- context:generated:start -->
## Summary

A standalone spike script validating the R7 QR-rendering plan: headless Chromium via CDP navigates to the WeChat Channels creator platform, locates the QR with a prioritized selector list, and screenshots it. Exit code 0 enables the 'CDP extract QR → encrypt to MinIO → self-service scan' pipeline; exit 1 falls back to 'local browser scan + cookie injection'. It is a decision gate, not part of the runtime stack.

## Related

- part of [[deployment-ops-scripts]] — Lives in scripts/ as a validation artifact for a planned feature.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
