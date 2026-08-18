---
name: Frontend Build & Dev Server
slug: frontend-build-dev-server
type: file
sources:
  - path: frontend/vite.config.ts
    hash: 3d17d684c6130bf76421b56eea915d0b1c99c599711dba2002a1c31c3377dd18
sources_digest: 35f9220082ae3a5e4dcf8598a02c59649a878474c65bb9d1503a28394fd464d1
links: []
generator:
  version: 1
covers: []
---
<!-- context:generated:start -->
## Summary

Vite config for the React frontend: dev server on port 3000 proxying /api to localhost:8080 (the backend) with changeOrigin, build to dist with sourcemaps disabled. The proxy assumes the backend runs locally on port 8080 during development.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
