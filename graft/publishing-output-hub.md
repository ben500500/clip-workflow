---
name: Publishing & Output Hub
slug: publishing-output-hub
type: system
sources:
  - path: frontend/src/pages/OutputPreview.tsx
    hash: 1d94981e928e40a70ad1a32d812ddcdeba4f25cf4aae18a97fbcf893864c7935
  - path: frontend/src/pages/PublishManagement.tsx
    hash: f6feabff263cb962500f480410449e4c20525a3874e55c4e2375f8eb6e8f38b7
sources_digest: 5ccce62ceb424e9b7c34cde9fe0ebad635ea630c4422002a277c62ad624b9f7f
links:
  - to: episode-production-pipeline-pages
    relation: uses
    description: >-
      Consumes slice tasks/outputs produced by the episode pipeline; re-cut
      launches a new slice task.
  - to: frontend-api-layer
    relation: uses
    description: 'Depends on sliceApi, previewApi, publishApi, publishMaterialApi.'
  - to: publishing-material-generation
    relation: uses
    description: Auto-generates titles/captions/tags from outputs via publishMaterialApi.
generator:
  version: 1
covers:
  - symbol: isRealSliceTask
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L31-L31'
  - symbol: RecutVideoPreview
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L34-L142'
  - symbol: OutputPreview
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L144-L950'
  - symbol: loadTask
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L219-L236'
  - symbol: downloadSelected
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L271-L305'
  - symbol: downloadOne
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L310-L330'
  - symbol: openPublishModal
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L333-L361'
  - symbol: submitPublish
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L363-L420'
  - symbol: onMaterialChange
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L423-L433'
  - symbol: onCaptionVersionChange
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L436-L445'
  - symbol: onGenerateMaterialFromOutput
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L448-L487'
  - symbol: openRecutModal
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L489-L508'
  - symbol: submitRecut
    kind: function
    at: 'frontend/src/pages/OutputPreview.tsx:L515-L542'
  - symbol: PublishManagement
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L19-L1425'
  - symbol: fetchTasks
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L85-L88'
  - symbol: fetchProfiles
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L90-L93'
  - symbol: fetchAccounts
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L95-L98'
  - symbol: fetchMiniPrograms
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L100-L103'
  - symbol: fetchTimeSlots
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L106-L108'
  - symbol: fetchMatrix
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L110-L117'
  - symbol: applyQr
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L120-L134'
  - symbol: poll
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L142-L166'
  - symbol: runHeartbeat
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L172-L179'
  - symbol: fetchAudit
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L181-L187'
  - symbol: fetchVerification
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L190-L196'
  - symbol: toggleFlag
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L199-L209'
  - symbol: fetchAll
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L211-L219'
  - symbol: confirmTask
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L225-L233'
  - symbol: viewScreenshot
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L235-L248'
  - symbol: requeueTask
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L251-L259'
  - symbol: cancelScheduled
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L262-L270'
  - symbol: publishNow
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L273-L281'
  - symbol: saveTimeSlot
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L284-L295'
  - symbol: deleteTimeSlot
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L298-L306'
  - symbol: createTask
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L308-L339'
  - symbol: saveProfile
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L341-L357'
  - symbol: saveAccount
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L359-L387'
  - symbol: saveBatchAssignProfile
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L390-L412'
  - symbol: saveMiniProgram
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L414-L438'
  - symbol: traceAction
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L704-L708'
  - symbol: buildVerifySteps
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L753-L820'
---
<!-- context:generated:start -->
## Summary

OutputPreview is the preview/publish hub for sliced outputs: lists slice tasks, previews/downloads (batch download uses a sequential loop with delays to avoid browser blocking; downloads route through axios to attach auth tokens since direct anchors 401), re-cuts via a draggable slider, and triggers one-click publish across WeChat Channels/Douyin/Kuaishou. Uses sequence refs as race-condition guards against stale responses and a single-expanded-preview policy to avoid multiple video players; supports deep-linking via ?task= query param. PublishManagement is the broader admin console for publish tasks, accounts, profiles, mini-program links, scheduled time slots, dead-letter requeueing, QR-code login heartbeat polling (8s interval, 90s cap), and a Redis-backed multi-operator feature flag.

## Related

- uses [[episode-production-pipeline-pages]] — Consumes slice tasks/outputs produced by the episode pipeline; re-cut launches a new slice task.
- uses [[frontend-api-layer]] — Depends on sliceApi, previewApi, publishApi, publishMaterialApi.
- uses [[publishing-material-generation]] — Auto-generates titles/captions/tags from outputs via publishMaterialApi.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
