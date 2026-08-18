---
name: Backend App Factory & Auth
slug: backend-app-factory-auth
type: system
sources:
  - path: backend/app/__init__.py
    hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - path: backend/app/api/auth.py
    hash: 8e744588002a7699918cb083129aeaabef990ddf49a0db695e12b9362aea4e55
sources_digest: 69e1d1ab2e65cea7bff9a4a66ded49d2c5038cbeec65151a68425e7370721fe2
links:
  - to: data-isolation-access-control
    relation: implements
    description: >-
      auth.py provides the RBAC and data_scope primitives that data_scope
      services build on.
  - to: publish-api-facade
    relation: uses
    description: >-
      All publish subdomain routers depend on get_current_user and require_roles
      from app.auth.
generator:
  version: 1
covers:
  - symbol: LoginRequest
    kind: class
    at: 'backend/app/api/auth.py:L51-L53'
  - symbol: LoginResponse
    kind: class
    at: 'backend/app/api/auth.py:L56-L60'
  - symbol: RefreshResponse
    kind: class
    at: 'backend/app/api/auth.py:L63-L65'
  - symbol: LogoutResponse
    kind: class
    at: 'backend/app/api/auth.py:L68-L70'
  - symbol: UserResponse
    kind: class
    at: 'backend/app/api/auth.py:L73-L86'
  - symbol: RegisterRequest
    kind: class
    at: 'backend/app/api/auth.py:L89-L93'
  - symbol: UpdateRoleRequest
    kind: class
    at: 'backend/app/api/auth.py:L96-L97'
  - symbol: UpdateDataScopeRequest
    kind: class
    at: 'backend/app/api/auth.py:L100-L101'
  - symbol: UpdateProfileRequest
    kind: class
    at: 'backend/app/api/auth.py:L104-L107'
  - symbol: _user_to_response
    kind: function
    at: 'backend/app/api/auth.py:L115-L128'
  - symbol: _set_refresh_cookie
    kind: function
    at: 'backend/app/api/auth.py:L131-L144'
  - symbol: _write_audit
    kind: function
    at: 'backend/app/api/auth.py:L147-L173'
  - symbol: _revoke_session_by_refresh_token
    kind: function
    at: 'backend/app/api/auth.py:L176-L189'
  - symbol: login
    kind: function
    at: 'backend/app/api/auth.py:L198-L235'
  - symbol: refresh_token
    kind: function
    at: 'backend/app/api/auth.py:L239-L321'
  - symbol: logout
    kind: function
    at: 'backend/app/api/auth.py:L325-L337'
  - symbol: get_me
    kind: function
    at: 'backend/app/api/auth.py:L341-L345'
  - symbol: register
    kind: function
    at: 'backend/app/api/auth.py:L349-L390'
  - symbol: list_users
    kind: function
    at: 'backend/app/api/auth.py:L394-L401'
  - symbol: update_user_role
    kind: function
    at: 'backend/app/api/auth.py:L405-L442'
  - symbol: update_user_data_scope
    kind: function
    at: 'backend/app/api/auth.py:L446-L486'
  - symbol: toggle_user_active
    kind: function
    at: 'backend/app/api/auth.py:L490-L518'
  - symbol: update_profile
    kind: function
    at: 'backend/app/api/auth.py:L522-L541'
---
<!-- context:generated:start -->
## Summary

Flask/FastAPI application bootstrap and the authentication/RBAC layer. create_app configures extensions lazily to avoid circular imports; auth.py issues dual tokens (short-lived access + refresh via HttpOnly cookie), reuses the same session/access JTI on refresh (avoiding multi-tab logout and concurrent refresh races), enforces RBAC via require_roles, and writes audit logs for security-critical actions. Data isolation is enforced per-user via data_scope (all vs own) defaulting by role.

## Related

- implements [[data-isolation-access-control]] — auth.py provides the RBAC and data_scope primitives that data_scope services build on.
- uses [[publish-api-facade]] — All publish subdomain routers depend on get_current_user and require_roles from app.auth.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
