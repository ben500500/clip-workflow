---
name: frontend app shell & routing
slug: frontend-app-shell-routing
type: system
sources:
  - path: frontend/src/App.tsx
    hash: 3c4dc25d1ea5c207b711dc4afed199c36298e0532ecb365a04aa46da8b1a736b
  - path: frontend/src/components/AppLayout.tsx
    hash: c06942f43e0e884f165854cae769a87d6831dec03266de4898f8c87c833fdce0
  - path: frontend/src/main.tsx
    hash: 91206c72a91e3c9f11d21768cd1ecaff845eb4ed163d9fc65cd497f411dff60f
sources_digest: 23fa8f19eb5ad88cbb50ca62d891e003770e1a371a500cb38821f36f5e6ea9ba
links:
  - to: frontend-api-layer
    relation: uses
    description: >-
      WorkerStatusIcon polls sliceApi.listWorkers and toggles nodes via
      enableWorker/disableWorker.
  - to: frontend-auth-session
    relation: uses
    description: AppLayout filters menu via hasPermission; AuthGuard gates routes.
generator:
  version: 1
covers:
  - symbol: App
    kind: function
    at: 'frontend/src/App.tsx:L39-L89'
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
---
<!-- context:generated:start -->
## Summary

The React application root: main.tsx mounts App with StrictMode, BrowserRouter, and Ant Design ConfigProvider (zhCN locale, primary #1677ff, radius 6). App.tsx declares the flat route structure (root redirects to /dashboard, catch-all NotFound) wrapping all non-login routes in AuthGuard + AppLayout. AppLayout renders the fixed sidebar with role-filtered menu, sticky header with a WorkerStatusIcon that polls sliceApi.listWorkers every 15s, and the content outlet.

## Related

- uses [[frontend-api-layer]] — WorkerStatusIcon polls sliceApi.listWorkers and toggles nodes via enableWorker/disableWorker.
- uses [[frontend-auth-session]] — AppLayout filters menu via hasPermission; AuthGuard gates routes.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
