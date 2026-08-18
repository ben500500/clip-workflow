---
name: Authentication & Profile
slug: authentication-profile
type: system
sources:
  - path: frontend/src/pages/Login.tsx
    hash: 4027b1d1d317a4a6bff87c1f8d072eedda72d55becb8de4dc6df3414db0550ba
  - path: frontend/src/pages/Profile.tsx
    hash: 626ff9b2fcbcd835f9c0698c44459cb0288d46bf77ccb2e02a75bb298ce33828
sources_digest: 0d2f9933a809f48090150883f6794767a7708576eda55f2a1f9db07d3be2f99a
links:
  - to: shared-frontend-types-formatting
    relation: uses
    description: Uses ROLE_OPTIONS and formatDateTime.
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
---
<!-- context:generated:start -->
## Summary

Login and Profile pages handle authentication entry and user profile display. Login guards against already-authenticated users via Navigate redirect, uses useAuth.login, and surfaces backend errors via message API. Profile maps role values to labels via ROLE_OPTIONS with conditional admin styling and handles the null-user case by rendering nothing.

## Related

- uses [[shared-frontend-types-formatting]] — Uses ROLE_OPTIONS and formatDateTime.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
