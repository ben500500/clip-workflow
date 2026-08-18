---
name: 'Auth, Users & Settings'
slug: auth-users-settings
type: system
sources:
  - path: frontend/src/pages/Login.tsx
    hash: 4027b1d1d317a4a6bff87c1f8d072eedda72d55becb8de4dc6df3414db0550ba
  - path: frontend/src/pages/Profile.tsx
    hash: 626ff9b2fcbcd835f9c0698c44459cb0288d46bf77ccb2e02a75bb298ce33828
  - path: frontend/src/pages/ResourceDownload.tsx
    hash: 2ed21b7206ae05a055bddb66a2c4f5dda28b3fdfb7a3eae8acfbe3ac7f0886e1
  - path: frontend/src/pages/Settings.tsx
    hash: 4c3ded0e3397b0b5c499a95fa07f150239e42cae1349cf5d1c266238a5c38a0f
  - path: frontend/src/pages/UserManagement.tsx
    hash: 0223afdd13b50636a9e2ede6acf62bbd956731b75964cdea9b935128065e0679
sources_digest: 365dd686614de8e0a8467298d992527cc8a513824cf2c0f9829ab2c8d3fb4cc5
links:
  - to: frontend-api-layer
    relation: uses
    description: 'Uses authApi, configApi, wechatDlApi, projectApi.'
  - to: slice-configuration-presets
    relation: configures
    description: >-
      Settings' per-platform dedupe profiles feed the dedupe_config used by
      slice tasks.
generator:
  version: 1
covers:
  - symbol: Login
    kind: function
    at: 'frontend/src/pages/Login.tsx:L9-L113'
  - symbol: handleSubmit
    kind: function
    at: 'frontend/src/pages/Login.tsx:L19-L31'
  - symbol: Profile
    kind: function
    at: 'frontend/src/pages/Profile.tsx:L12-L61'
  - symbol: ImportPanel
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L32-L179'
  - symbol: handleResolutionChange
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L50-L57'
  - symbol: handleImport
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L59-L97'
  - symbol: TaskListPanel
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L182-L514'
  - symbol: handleToSlice
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L211-L222'
  - symbol: canImport
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L252-L252'
  - symbol: openPreview
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L254-L266'
  - symbol: openImport
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L268-L281'
  - symbol: handleImportConfirm
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L283-L308'
  - symbol: metaDuration
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L310-L317'
  - symbol: ProvidersPanel
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L517-L625'
  - symbol: renderBalance
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L531-L553'
  - symbol: ResourceDownload
    kind: function
    at: 'frontend/src/pages/ResourceDownload.tsx:L628-L654'
  - symbol: Settings
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L12-L393'
  - symbol: fetchAll
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L26-L34'
  - symbol: saveConfig
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L40-L50'
  - symbol: handleConfigEdit
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L52-L59'
  - symbol: handleConfigSave
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L61-L79'
  - symbol: saveProfile
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L81-L105'
  - symbol: handleConfigReset
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L108-L116'
  - symbol: handleProfileReset
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L119-L127'
  - symbol: applyPreset
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L130-L135'
  - symbol: handleAsrChange
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L138-L149'
  - symbol: renderConfigValue
    kind: function
    at: 'frontend/src/pages/Settings.tsx:L151-L181'
  - symbol: UserManagement
    kind: function
    at: 'frontend/src/pages/UserManagement.tsx:L13-L214'
  - symbol: fetchUsers
    kind: function
    at: 'frontend/src/pages/UserManagement.tsx:L22-L32'
  - symbol: handleAdd
    kind: function
    at: 'frontend/src/pages/UserManagement.tsx:L38-L43'
  - symbol: handleEdit
    kind: function
    at: 'frontend/src/pages/UserManagement.tsx:L45-L49'
  - symbol: handleSubmit
    kind: function
    at: 'frontend/src/pages/UserManagement.tsx:L51-L74'
  - symbol: handleScopeEdit
    kind: function
    at: 'frontend/src/pages/UserManagement.tsx:L76-L80'
  - symbol: handleScopeSubmit
    kind: function
    at: 'frontend/src/pages/UserManagement.tsx:L82-L94'
---
<!-- context:generated:start -->
## Summary

Login is the auth entry point guarding against already-authenticated users via Navigate redirect. UserManagement manages users/roles/data scopes with a default-scope rule (operators default to 'own', others to 'all') and defensive errorFields checks. Profile renders the current user with role/status styling. Settings is the admin config page: ASR engine selector (Aliyun/Whisper/FunASR), global key-value and JSON configs with validation, and per-platform dedupe profiles combining preset tiers (light/standard/heavy) with manual overrides. ResourceDownload manages WeChat Channels downloads with WebSocket progress, a global default resolution persisted via configApi, and two completion paths (import to project or direct to slice).

## Related

- uses [[frontend-api-layer]] — Uses authApi, configApi, wechatDlApi, projectApi.
- configures [[slice-configuration-presets]] — Settings' per-platform dedupe profiles feed the dedupe_config used by slice tasks.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
