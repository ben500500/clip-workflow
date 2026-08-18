---
name: Docker Compose Stack Contract
slug: docker-compose-stack-contract
type: concept
sources:
  - path: scripts/logs.sh
    hash: d92bcf93e032d2422640ce07279b292fbfd13864447cf1ecbf8446d71f6e5920
  - path: scripts/restart.sh
    hash: 78e9977a5689ceb7a1feec3f8bbf0f64435883156deb8b8bfd7fbbb16df2e156
  - path: scripts/server-setup.sh
    hash: ec7a55b6eba273e5862a08bdabd7453a1c2fa223885b150d603cb9dc52901ce4
  - path: scripts/start.sh
    hash: 01e2d2f4c7ba684f76cf41f2df6fa0297c9eb8540d1b64634614148d1f9915e0
  - path: scripts/status.sh
    hash: 2ad2b1e0c9a2ff6552d5e4026d5144aa93d88a705edfe43dd71e66617dd16ead
sources_digest: 790bf97286c363f4af5adb67ab843b040b8281ff35cd5c62461d75b19c164c8d
links:
  - to: deployment-ops-scripts
    relation: part_of
    description: The contract is the shared assumption all these scripts encode.
generator:
  version: 1
covers: []
---
<!-- context:generated:start -->
## Summary

The implicit contract between the ops scripts and the compose topology: service names (postgres, redis, minio, backend, worker-video, frontend, nginx, autoclip, beat), the nginx container as the single health-check gate, and `.env` variables (NGINX_PORT, MINIO_CONSOLE_PORT, SECRET_KEY, POSTGRES_PASSWORD) that both scripts and services read. This contract is not enforced by code — it is maintained manually, so any rename breaks logs.sh filtering and health polling silently.

## Related

- part of [[deployment-ops-scripts]] — The contract is the shared assumption all these scripts encode.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
