---
name: frontend auth & session
slug: frontend-auth-session
type: system
sources:
  - path: frontend/src/components/AppLayout.tsx
    hash: c06942f43e0e884f165854cae769a87d6831dec03266de4898f8c87c833fdce0
  - path: frontend/src/components/AuthGuard.tsx
    hash: dbcca0e8d08445bf73521abdc152fd341ae51ea75d05e279953a5f4de083b697
  - path: frontend/src/contexts/AuthContext.tsx
    hash: df27092e40f207edb8262938c23e06641f3ba23c3b6fe9b55177b4719ec28714
sources_digest: 4535d45be1935bd79c78fcf45538e425dfb8d3a98057306309046de3ae0ce4df
links:
  - to: frontend-api-layer
    relation: uses
    description: >-
      Calls authApi.login/refresh/logout/getMe and
      sliceApi.listWorkers/enableWorker/disableWorker.
  - to: frontend-app-shell-routing
    relation: part_of
    description: >-
      AppLayout filters the static menu through hasPermission; AuthGuard wraps
      all protected routes.
generator:
  version: 1
covers:
  - symbol: WorkerStatusIcon
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L138-L297'
  - symbol: toggleWorker
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L164-L180'
  - symbol: onOpenChange
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L183-L185'
  - symbol: AppLayout
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L299-L495'
  - symbol: getSelectedKey
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L327-L332'
  - symbol: handleMenuClick
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L354-L356'
  - symbol: handleUserMenuClick
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L358-L374'
  - symbol: onOk
    kind: method
    at: 'frontend/src/components/AppLayout.tsx:L368-L371'
  - symbol: getMenuKeyFromPath
    kind: function
    at: 'frontend/src/components/AuthGuard.tsx:L28-L38'
  - symbol: ForbiddenPage
    kind: function
    at: 'frontend/src/components/AuthGuard.tsx:L40-L54'
  - symbol: AuthGuardProps
    kind: interface
    at: 'frontend/src/components/AuthGuard.tsx:L56-L58'
  - symbol: AuthGuard
    kind: function
    at: 'frontend/src/components/AuthGuard.tsx:L60-L89'
  - symbol: AuthContextType
    kind: interface
    at: 'frontend/src/contexts/AuthContext.tsx:L52-L60'
  - symbol: AuthProvider
    kind: function
    at: 'frontend/src/contexts/AuthContext.tsx:L64-L164'
  - symbol: refresh
    kind: function
    at: 'frontend/src/contexts/AuthContext.tsx:L103-L113'
  - symbol: useAuth
    kind: function
    at: 'frontend/src/contexts/AuthContext.tsx:L166-L172'
---
<!-- context:generated:start -->
## Summary

Authentication state management: AuthContext reads token from localStorage, validates via authApi.getMe(), and silently refreshes the access token every 20 minutes to prevent idle session expiry. ROLE_PERMISSIONS maps roles (admin/operator/publisher/material) to allowed menu paths with admin wildcard. AuthGuard protects routes by mapping URL paths to menu permission keys (exact + prefix matching for /projects/ and /episodes/), returning null during loading to avoid flicker, and rendering ForbiddenPage for unauthorized mapped routes. Unmapped routes are treated as accessible.

## Related

- uses [[frontend-api-layer]] — Calls authApi.login/refresh/logout/getMe and sliceApi.listWorkers/enableWorker/disableWorker.
- part of [[frontend-app-shell-routing]] — AppLayout filters the static menu through hasPermission; AuthGuard wraps all protected routes.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
