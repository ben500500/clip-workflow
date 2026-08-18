---
name: Admin & User Management
slug: admin-user-management
type: system
sources:
  - path: frontend/src/pages/Settings.tsx
    hash: 4c3ded0e3397b0b5c499a95fa07f150239e42cae1349cf5d1c266238a5c38a0f
  - path: frontend/src/pages/UserManagement.tsx
    hash: 0223afdd13b50636a9e2ede6acf62bbd956731b75964cdea9b935128065e0679
sources_digest: b450c956d83f252bcf751ab3535c72c51d2de6bb2d46d22655af9d9faaec71a2
links:
  - to: shared-frontend-types-formatting
    relation: uses
    description: 'Uses ROLE_OPTIONS, DATA_SCOPE_OPTIONS constants and formatDateTime.'
generator:
  version: 1
covers:
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

UserManagement and Settings pages cover admin functions: user/role/data-scope management (operators default to 'own' scope, others to 'all', with explicit override) and system configuration (ASR engine selector, global key-value configs, per-platform dedupe profiles with JSON dedupe_config combining preset tiers and manual overrides). Settings supports JSON syntax validation and reset-to-default.

## Related

- uses [[shared-frontend-types-formatting]] — Uses ROLE_OPTIONS, DATA_SCOPE_OPTIONS constants and formatDateTime.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
