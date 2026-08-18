---
name: Project & Episode Management
slug: project-episode-management
type: system
sources:
  - path: frontend/src/pages/ProjectDetail.tsx
    hash: 9f46b2301f189ebf50fbf53d4e85de4acc9dc779bb39f4b1bfb5339ec6446089
  - path: frontend/src/pages/Projects.tsx
    hash: 63f814ad98757153a1cf1b3d19b229b8f41cd92869878726676703129244773d
sources_digest: 478a08048bcdf7c990c4bac68850c17246d7d62d76f27c23884d359560b96b7d
links:
  - to: episode-production-pipeline-pages
    relation: produces
    description: >-
      Episodes created/uploaded here are the entry point for the
      autoclip→interval→slice pipeline.
  - to: frontend-api-layer
    relation: uses
    description: Uses projectApi and uploadApi.
generator:
  version: 1
covers:
  - symbol: ProjectDetail
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L16-L341'
  - symbol: fetchData
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L47-L62'
  - symbol: handleUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L68-L97'
  - symbol: submitMultiUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L100-L131'
  - symbol: Projects
    kind: function
    at: 'frontend/src/pages/Projects.tsx:L14-L227'
  - symbol: handleSearch
    kind: function
    at: 'frontend/src/pages/Projects.tsx:L44-L48'
  - symbol: handleCreate
    kind: function
    at: 'frontend/src/pages/Projects.tsx:L50-L54'
  - symbol: handleEdit
    kind: function
    at: 'frontend/src/pages/Projects.tsx:L56-L64'
  - symbol: handleDelete
    kind: function
    at: 'frontend/src/pages/Projects.tsx:L66-L74'
  - symbol: handleSubmit
    kind: function
    at: 'frontend/src/pages/Projects.tsx:L76-L95'
---
<!-- context:generated:start -->
## Summary

Projects is a searchable paginated list with create/edit/delete and a manual refresh trigger in handleSearch because the useEffect on page won't fire when already on page 1. ProjectDetail shows metadata, an episode table, and two upload paths: single-file with AbortController abort support, and multi-file that can optionally merge videos into a new project (with a warning about matching codecs/resolution/framerate); aborts in-flight uploads on unmount.

## Related

- produces [[episode-production-pipeline-pages]] — Episodes created/uploaded here are the entry point for the autoclip→interval→slice pipeline.
- uses [[frontend-api-layer]] — Uses projectApi and uploadApi.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
