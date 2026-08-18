---
name: Auth & Session Management
slug: auth-session-management
type: system
sources:
  - path: frontend/src/api/auth.ts
    hash: ca0de968f895916fb29ddf57cb08544d07363771a2740266bc61c939dd71996e
  - path: frontend/src/components/AuthGuard.tsx
    hash: dbcca0e8d08445bf73521abdc152fd341ae51ea75d05e279953a5f4de083b697
  - path: frontend/src/contexts/AuthContext.tsx
    hash: ef3d7e17a1c5feae93d78e7de3ccef5fa58291e25140859049def799ffbb4af6
sources_digest: bedd219eebc337844cce638d990bd7ed075892a001b595e2f0715ca3ea7aab1b
links:
  - to: frontend-api-client-layer
    relation: uses
    description: >-
      AuthContext calls authApi.getMe/refresh/logout; the client's
      silent-refresh interceptor is the transport for token renewal.
  - to: frontend-routing-shell
    relation: part_of
    description: >-
      AuthGuard wraps all business routes under AppLayout; AppLayout filters
      menu items through hasPermission.
generator:
  version: 1
covers:
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
    at: 'frontend/src/contexts/AuthContext.tsx:L50-L58'
  - symbol: AuthProvider
    kind: function
    at: 'frontend/src/contexts/AuthContext.tsx:L62-L162'
  - symbol: refresh
    kind: function
    at: 'frontend/src/contexts/AuthContext.tsx:L101-L111'
  - symbol: useAuth
    kind: function
    at: 'frontend/src/contexts/AuthContext.tsx:L164-L170'
---
<!-- context:generated:start -->
## Summary

Frontend authentication: AuthContext provides user/token/roles and hasPermission against a hardcoded ROLE_PERMISSIONS map (admin wildcard; operator/publisher/material get explicit route lists). Validates saved token via getMe on mount and silently refreshes every 20 minutes before the 30-minute access token expires. Logout revokes the refresh-token session server-side before clearing local state. AuthGuard maps URL paths to menu permission keys and redirects unauthenticated users to /login while preserving the intended destination.

## Related

- uses [[frontend-api-client-layer]] — AuthContext calls authApi.getMe/refresh/logout; the client's silent-refresh interceptor is the transport for token renewal.
- part of [[frontend-routing-shell]] — AuthGuard wraps all business routes under AppLayout; AppLayout filters menu items through hasPermission.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
