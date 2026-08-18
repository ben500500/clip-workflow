---
name: Auth & Session Layer
slug: auth-session-layer
type: system
sources:
  - path: backend/app/auth.py
    hash: d86b3e272a03fe944f3549a3b4a984700c3984a0671a647cea9a01370c052bc6
  - path: backend/app/models/user.py
    hash: 6e3a1b90d901e75a6d3a2e96d5cb46aa614b1fcc81d88b9b0e411cb5b517ecc4
sources_digest: 55a2c088ec2393bbf3c17fd423d7bccdec5ca57e51cc7084d2c9e8465427c9ad
links:
  - to: data-isolation-rbac
    relation: implements
    description: >-
      Role-based data_scope defaults and user_can_access_all_materials gate
      project visibility
  - to: login-qr-self-service
    relation: uses
    description: login_qr_service derives its Fernet key from the same COOKIE_ENCRYPT_KEY
generator:
  version: 1
covers:
  - symbol: verify_password
    kind: function
    at: 'backend/app/auth.py:L36-L38'
  - symbol: get_password_hash
    kind: function
    at: 'backend/app/auth.py:L41-L43'
  - symbol: _create_jwt
    kind: function
    at: 'backend/app/auth.py:L51-L56'
  - symbol: create_access_token
    kind: function
    at: 'backend/app/auth.py:L59-L68'
  - symbol: create_refresh_token
    kind: function
    at: 'backend/app/auth.py:L71-L88'
  - symbol: _hash_token
    kind: function
    at: 'backend/app/auth.py:L91-L93'
  - symbol: decode_token
    kind: function
    at: 'backend/app/auth.py:L96-L115'
  - symbol: get_current_user
    kind: function
    at: 'backend/app/auth.py:L123-L177'
  - symbol: require_roles
    kind: function
    at: 'backend/app/auth.py:L180-L208'
  - symbol: role_checker
    kind: function
    at: 'backend/app/auth.py:L198-L206'
  - symbol: create_user_session
    kind: function
    at: 'backend/app/auth.py:L211-L232'
  - symbol: get_role_menus
    kind: function
    at: 'backend/app/auth.py:L284-L290'
  - symbol: _fernet_key_from_secret
    kind: function
    at: 'backend/app/auth.py:L298-L301'
  - symbol: encrypt_cookie
    kind: function
    at: 'backend/app/auth.py:L304-L313'
  - symbol: decrypt_cookie
    kind: function
    at: 'backend/app/auth.py:L316-L322'
  - symbol: UserRole
    kind: class
    at: 'backend/app/models/user.py:L25-L30'
  - symbol: default_data_scope_for_role
    kind: function
    at: 'backend/app/models/user.py:L52-L57'
  - symbol: user_can_access_all_materials
    kind: function
    at: 'backend/app/models/user.py:L60-L65'
  - symbol: User
    kind: class
    at: 'backend/app/models/user.py:L68-L92'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/user.py:L91-L92'
  - symbol: UserSession
    kind: class
    at: 'backend/app/models/user.py:L95-L117'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/user.py:L116-L117'
  - symbol: UserPreference
    kind: class
    at: 'backend/app/models/user.py:L120-L136'
  - symbol: __repr__
    kind: method
    at: 'backend/app/models/user.py:L135-L136'
---
<!-- context:generated:start -->
## Summary

Dual-token JWT auth (30-min access, 7-day refresh) with bcrypt hashing, four roles (admin/operator/publisher/material), and session-level revocation via UserSession. Refresh tokens carry a mandatory random jti to prevent collision during concurrent logins; get_current_user checks access_token_jti against revoked sessions. Also provides AES-256 Fernet cookie encryption with a key derived from settings.COOKIE_ENCRYPT_KEY.

## Related

- implements [[data-isolation-rbac]] — Role-based data_scope defaults and user_can_access_all_materials gate project visibility
- uses [[login-qr-self-service]] — login_qr_service derives its Fernet key from the same COOKIE_ENCRYPT_KEY
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
