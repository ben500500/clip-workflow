---
name: Project & Episode Management
slug: project-episode-management
type: system
sources:
  - path: frontend/src/pages/ProjectDetail.tsx
    hash: 1bbb9d15160553afd40326da2f779f08d7a9fa78c820244d2fed5a200d77cf4f
  - path: frontend/src/pages/Projects.tsx
    hash: 63f814ad98757153a1cf1b3d19b229b8f41cd92869878726676703129244773d
sources_digest: 435f0c61b6c8d8eb2345a29d05553f008ecde3905b4e1bf1b76044550a3463b6
links:
  - to: slice-configuration-presets
    relation: uses
    description: Shares batch slicing presets via localStorage key slice_presets_v1.
generator:
  version: 1
covers:
  - symbol: BatchSliceConfig
    kind: interface
    at: 'frontend/src/pages/ProjectDetail.tsx:L19-L33'
  - symbol: BatchPresetOption
    kind: interface
    at: 'frontend/src/pages/ProjectDetail.tsx:L60-L67'
  - symbol: ProjectDetail
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L70-L1035'
  - symbol: applyBatchPreset
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L109-L120'
  - symbol: fetchData
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L155-L170'
  - symbol: handleUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L179-L208'
  - symbol: submitMultiUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L211-L242'
  - symbol: handleMultiFileUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L245-L282'
  - symbol: handleTabChange
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L303-L308'
  - symbol: togglePreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L311-L351'
  - symbol: refreshPreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L353-L378'
  - symbol: renderSourcePreview
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L380-L432'
  - symbol: handleCoverUpload
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L435-L455'
  - symbol: runOneClickSlice
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L458-L478'
  - symbol: runBatchSlice
    kind: function
    at: 'frontend/src/pages/ProjectDetail.tsx:L481-L506'
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

Projects list and ProjectDetail pages manage projects and episodes: searchable/paginated table with CRUD, episode upload (single/multi-file with optional merging), batch one-click slicing across episodes, and a finished-products preview. Uses AbortController to abort in-flight uploads, lazy-loads video preview URLs to avoid stale links, and falls back to automatic AI clip when no candidates are found.

## Related

- uses [[slice-configuration-presets]] — Shares batch slicing presets via localStorage key slice_presets_v1.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
