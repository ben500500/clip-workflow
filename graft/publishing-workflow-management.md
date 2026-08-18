---
name: Publishing Workflow Management
slug: publishing-workflow-management
type: system
sources:
  - path: frontend/src/pages/PublishManagement.tsx
    hash: d4eabac2dfd632e2558b7577222054ebe70599d583ee21f7648befe6c1be9b7a
sources_digest: 65a9d4708e5b8c568200b2334e356047a9c48a7712dc6842d238b184f964032b
links:
  - to: shared-frontend-types-formatting
    relation: uses
    description: >-
      Uses OperatorRouteRow, PublishAuditItem, RiskEventItem types and
      formatDateTime/getStatusColor/getStatusLabel.
generator:
  version: 1
covers:
  - symbol: PublishManagement
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L19-L1429'
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
    at: 'frontend/src/pages/PublishManagement.tsx:L705-L709'
  - symbol: buildVerifySteps
    kind: function
    at: 'frontend/src/pages/PublishManagement.tsx:L754-L821'
---
<!-- context:generated:start -->
## Summary

PublishManagement page handles the video publishing workflow: task creation with scheduled time slots, video account and mini-program management, batch profile assignment, QR-code WeChat login (polling loginHeartbeat every 8s until valid or 90s TTL), multi-operator route matrix with audit logs, and a Redis-backed feature flag toggle. Includes dead-letter task requeueing, screenshot viewing, and scheduled task cancellation/immediate publish.

## Related

- uses [[shared-frontend-types-formatting]] — Uses OperatorRouteRow, PublishAuditItem, RiskEventItem types and formatDateTime/getStatusColor/getStatusLabel.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
