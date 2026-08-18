---
name: Frontend Routing & Shell
slug: frontend-routing-shell
type: system
sources:
  - path: frontend/src/App.tsx
    hash: 20419ea6411db7c4ac06c5b2b18450987c34726e6a14516b243c507886f9f31e
  - path: frontend/src/components/AppLayout.tsx
    hash: e66e7fab76393d6f601cc979f6c220ae7ac69ebd7014ddbc8fbcdf0ee7cb3c6a
  - path: frontend/src/main.tsx
    hash: 91206c72a91e3c9f11d21768cd1ecaff845eb4ed163d9fc65cd497f411dff60f
sources_digest: 55ead5be5f710147b6a3b9cc206f32db97193ca8f7453912206c69e3133c90a8
links:
  - to: auth-session-management
    relation: uses
    description: >-
      AppLayout filters menu via hasPermission and renders logout; AuthGuard
      gates routes.
  - to: frontend-api-client-layer
    relation: uses
    description: >-
      AppLayout polls and toggles workers via sliceApi; pages consume the api
      objects.
generator:
  version: 1
covers:
  - symbol: App
    kind: function
    at: 'frontend/src/App.tsx:L38-L87'
  - symbol: WorkerStatusIcon
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L132-L291'
  - symbol: toggleWorker
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L158-L174'
  - symbol: onOpenChange
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L177-L179'
  - symbol: AppLayout
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L293-L489'
  - symbol: getSelectedKey
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L321-L326'
  - symbol: handleMenuClick
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L348-L350'
  - symbol: handleUserMenuClick
    kind: function
    at: 'frontend/src/components/AppLayout.tsx:L352-L368'
  - symbol: onOk
    kind: method
    at: 'frontend/src/components/AppLayout.tsx:L362-L365'
---
<!-- context:generated:start -->
## Summary

The React app composition root and shell: main.tsx mounts with StrictMode, BrowserRouter, and Ant Design ConfigProvider (zhCN locale, primary #1677ff). App.tsx defines the full route tree with /login public and all business routes under AuthGuard+AppLayout. AppLayout provides the sidebar (filtered by role permissions), sticky header with a WorkerStatusIcon polling sliceApi.listWorkers every 15s, and route-selection mapping from nested paths back to parent menu keys.

## Related

- uses [[auth-session-management]] — AppLayout filters menu via hasPermission and renders logout; AuthGuard gates routes.
- uses [[frontend-api-client-layer]] — AppLayout polls and toggles workers via sliceApi; pages consume the api objects.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
