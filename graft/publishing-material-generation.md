---
name: Publishing Material Generation
slug: publishing-material-generation
type: system
sources:
  - path: frontend/src/pages/PublishMaterialTab.tsx
    hash: c09b76e07e6415de73660b4cc06721106c475ac3f3007244b88ad44cd706b1e7
sources_digest: 1b69aba59841a96f0ad31249bc484c58c0ad73f4f5385992881b4d4dbe2e8bb2
links:
  - to: publishing-output-hub
    relation: uses
    description: >-
      OutputPreview calls publishMaterialApi to auto-generate material from
      outputs.
  - to: short-drama-generation-workflow
    relation: uses
    description: >-
      Imports source text from shortdrama prompt history via
      ShortdramaPromptRecord.
generator:
  version: 1
covers:
  - symbol: PublishMaterialTab
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L59-L736'
  - symbol: importPromptRecord
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L148-L159'
  - symbol: handleGenerate
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L162-L190'
  - symbol: handleCopy
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L192-L222'
  - symbol: clearForm
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L224-L234'
  - symbol: deleteRecord
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L236-L244'
  - symbol: buildFullCopy
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L247-L264'
  - symbol: versionLabel
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L266-L273'
  - symbol: renderMaterialContent
    kind: function
    at: 'frontend/src/pages/PublishMaterialTab.tsx:L276-L443'
---
<!-- context:generated:start -->
## Summary

PublishMaterialTab generates and manages short-drama publishing materials (titles, captions, tags, comments) for Douyin/Kuaishou from a story synopsis, with three caption versions (suspense_hook, concise_viral, emotional) switchable via tabs and a 'copy full copy' builder. Includes a clipboard fallback using document.execCommand for non-HTTPS environments and can auto-fill from a pending prompt record ID (e.g., from a watermark-removal task).

## Related

- uses [[publishing-output-hub]] — OutputPreview calls publishMaterialApi to auto-generate material from outputs.
- uses [[short-drama-generation-workflow]] — Imports source text from shortdrama prompt history via ShortdramaPromptRecord.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
