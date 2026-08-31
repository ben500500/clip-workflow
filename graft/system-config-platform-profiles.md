---
name: System Config & Platform Profiles
slug: system-config-platform-profiles
type: system
sources:
  - path: backend/app/api/config.py
    hash: 2319c504c38c2ce6f9e24a49e0de7b99726795477cc47cce78e1696dccb0bc5f
sources_digest: f9e5ec19de7d06e05d6f82aa8ad33db9d6ccb682c8dd9e767b4d074d1ad28c73
links:
  - to: dashboard-analytics
    relation: uses
    description: dashboard.py reads SystemConfig for default dashboard config values.
  - to: variant-matrix-deduplication
    relation: configures
    description: Collision thresholds stored in SystemConfig override variant defaults.
generator:
  version: 1
covers:
  - symbol: ConfigUpdateRequest
    kind: class
    at: 'backend/app/api/config.py:L17-L19'
  - symbol: ConfigResponse
    kind: class
    at: 'backend/app/api/config.py:L22-L26'
  - symbol: ProfileCreate
    kind: class
    at: 'backend/app/api/config.py:L29-L36'
  - symbol: ProfileUpdate
    kind: class
    at: 'backend/app/api/config.py:L39-L46'
  - symbol: ProfileResponse
    kind: class
    at: 'backend/app/api/config.py:L49-L60'
  - symbol: _default_profile_for
    kind: function
    at: 'backend/app/api/config.py:L335-L343'
  - symbol: _serialize_config
    kind: function
    at: 'backend/app/api/config.py:L346-L352'
  - symbol: _serialize_profile
    kind: function
    at: 'backend/app/api/config.py:L355-L366'
  - symbol: get_all_config
    kind: function
    at: 'backend/app/api/config.py:L370-L399'
  - symbol: update_config
    kind: function
    at: 'backend/app/api/config.py:L403-L428'
  - symbol: reset_config_default
    kind: function
    at: 'backend/app/api/config.py:L432-L459'
  - symbol: list_platform_profiles
    kind: function
    at: 'backend/app/api/config.py:L463-L469'
  - symbol: create_platform_profile
    kind: function
    at: 'backend/app/api/config.py:L473-L500'
  - symbol: update_platform_profile
    kind: function
    at: 'backend/app/api/config.py:L504-L551'
  - symbol: reset_platform_profile_default
    kind: function
    at: 'backend/app/api/config.py:L555-L591'
  - symbol: get_platform_presets
    kind: function
    at: 'backend/app/api/config.py:L595-L607'
  - symbol: delete_platform_profile
    kind: function
    at: 'backend/app/api/config.py:L611-L630'
---
<!-- context:generated:start -->
## Summary

SystemConfig key-value pairs and PlatformProfile objects bundling dedup settings, target resolution, bitrate, and max duration per platform (WeChat Channels, Douyin, Kuaishou). Ships extensive seed data (DEFAULT_CONFIGS, DEFAULT_PLATFORM_PROFILES, PLATFORM_PRESETS) and merges DB-stored overrides with defaults so users never lose visibility of unmodified settings. Reset deletes DB overrides to fall back to built-in defaults, with platform-based fallback matching when no name match exists.

## Related

- uses [[dashboard-analytics]] — dashboard.py reads SystemConfig for default dashboard config values.
- configures [[variant-matrix-deduplication]] — Collision thresholds stored in SystemConfig override variant defaults.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
