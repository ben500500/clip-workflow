---
name: Data Isolation & RBAC
slug: data-isolation-rbac
type: concept
sources:
  - path: backend/app/database.py
    hash: 5ee4dd810b8b44b77aa72792c10d0eb7e6a3e88f3230b25b99cbc496a529fe41
  - path: backend/app/models/user.py
    hash: 6e3a1b90d901e75a6d3a2e96d5cb46aa614b1fcc81d88b9b0e411cb5b517ecc4
  - path: backend/app/services/data_scope.py
    hash: 7e65efad5a2fd51f598c2157b97558c015c8247c1004329b7293d14c9fc5e1cd
sources_digest: 07a08d6786ccc2bc22191de31dfaaf61b64e91c8e00a2fc2e6c5d7c5fc9552a1
links:
  - to: auth-session-layer
    relation: depends_on
    description: Role comes from the authenticated user's JWT claims
  - to: orm-model-registry
    relation: uses
    description: Consults user_can_access_all_materials and Project.created_by
generator:
  version: 1
covers:
  - symbol: Base
    kind: class
    at: 'backend/app/database.py:L34-L35'
  - symbol: get_db
    kind: function
    at: 'backend/app/database.py:L38-L48'
  - symbol: init_db
    kind: function
    at: 'backend/app/database.py:L51-L60'
  - symbol: _backfill_data_scope
    kind: function
    at: 'backend/app/database.py:L63-L84'
  - symbol: _ensure_autoclip_runs_table
    kind: function
    at: 'backend/app/database.py:L87-L128'
  - symbol: _apply_compat_migrations
    kind: function
    at: 'backend/app/database.py:L131-L219'
  - symbol: close_db
    kind: function
    at: 'backend/app/database.py:L222-L224'
  - symbol: _ensure_wechat_download_tables
    kind: function
    at: 'backend/app/database.py:L226-L238'
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
  - symbol: check_project_access_by_episode
    kind: function
    at: 'backend/app/services/data_scope.py:L21-L35'
  - symbol: check_project_access_by_id
    kind: function
    at: 'backend/app/services/data_scope.py:L38-L56'
---
<!-- context:generated:start -->
## Summary

Role-based data visibility: admins and material/publishing specialists see all materials; operators see only their own unless granted broader scope. Access checks deliberately return HTTP 404 instead of 403 to hide project/episode existence and prevent enumeration. data_scope is backfilled at DB layer by role, and check_project_access_* validates UUID before querying.

## Related

- depends on [[auth-session-layer]] — Role comes from the authenticated user's JWT claims
- uses [[orm-model-registry]] — Consults user_can_access_all_materials and Project.created_by
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
