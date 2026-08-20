---
name: Configuration & Database Bootstrap
slug: configuration-database-bootstrap
type: system
sources:
  - path: backend/app/config.py
    hash: 343fec5e28a2741d1083e7c06ba59eecae3aeb451d9084ee20ad7196fd5e6612
  - path: backend/app/database.py
    hash: 5ee4dd810b8b44b77aa72792c10d0eb7e6a3e88f3230b25b99cbc496a529fe41
sources_digest: df334f322685b10d5c27922d685847dbff7780f1992848fdd7e7c87724e85304
links:
  - to: auth-session-layer
    relation: configures
    description: 'Provides JWT_SECRET, COOKIE_ENCRYPT_KEY, and token TTLs'
  - to: data-isolation-rbac
    relation: implements
    description: >-
      _backfill_data_scope sets default data isolation scopes based on user
      roles at DB layer
generator:
  version: 1
covers:
  - symbol: _parse_origins
    kind: function
    at: 'backend/app/config.py:L15-L17'
  - symbol: Settings
    kind: class
    at: 'backend/app/config.py:L20-L223'
  - symbol: _no_default_secret
    kind: method
    at: 'backend/app/config.py:L209-L214'
  - symbol: _cookie_key_differs
    kind: method
    at: 'backend/app/config.py:L218-L223'
  - symbol: _ensure_cookie_key
    kind: function
    at: 'backend/app/config.py:L226-L241'
  - symbol: Base
    kind: class
    at: 'backend/app/database.py:L34-L35'
  - symbol: get_db
    kind: function
    at: 'backend/app/database.py:L38-L48'
  - symbol: init_db
    kind: function
    at: 'backend/app/database.py:L51-L62'
  - symbol: _enforce_idle_in_transaction_timeout
    kind: function
    at: 'backend/app/database.py:L65-L88'
  - symbol: _backfill_data_scope
    kind: function
    at: 'backend/app/database.py:L91-L112'
  - symbol: _ensure_autoclip_runs_table
    kind: function
    at: 'backend/app/database.py:L115-L156'
  - symbol: _apply_compat_migrations
    kind: function
    at: 'backend/app/database.py:L159-L257'
  - symbol: close_db
    kind: function
    at: 'backend/app/database.py:L260-L262'
  - symbol: _ensure_wechat_download_tables
    kind: function
    at: 'backend/app/database.py:L264-L276'
---
<!-- context:generated:start -->
## Summary

Pydantic BaseSettings loads env/.env for all infra connections; enforces JWT_SECRET strength and COOKIE_ENCRYPT_KEY distinctness, persists a generated cookie key to disk. Database layer uses async SQLAlchemy with pool_pre_ping, 30s statement timeout, and idempotent raw-SQL migrations (no Alembic) that add columns, backfill data_scope by role, and create legacy tables. extra='ignore' tolerates Docker Compose vars.

## Related

- configures [[auth-session-layer]] — Provides JWT_SECRET, COOKIE_ENCRYPT_KEY, and token TTLs
- implements [[data-isolation-rbac]] — _backfill_data_scope sets default data isolation scopes based on user roles at DB layer
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
