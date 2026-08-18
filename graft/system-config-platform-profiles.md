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
    at: 'backend/app/api/config.py:L275-L283'
  - symbol: _serialize_config
    kind: function
    at: 'backend/app/api/config.py:L286-L292'
  - symbol: _serialize_profile
    kind: function
    at: 'backend/app/api/config.py:L295-L306'
  - symbol: get_all_config
    kind: function
    at: 'backend/app/api/config.py:L310-L339'
  - symbol: update_config
    kind: function
    at: 'backend/app/api/config.py:L343-L368'
  - symbol: reset_config_default
    kind: function
    at: 'backend/app/api/config.py:L372-L399'
  - symbol: list_platform_profiles
    kind: function
    at: 'backend/app/api/config.py:L403-L409'
  - symbol: create_platform_profile
    kind: function
    at: 'backend/app/api/config.py:L413-L440'
  - symbol: update_platform_profile
    kind: function
    at: 'backend/app/api/config.py:L444-L491'
  - symbol: reset_platform_profile_default
    kind: function
    at: 'backend/app/api/config.py:L495-L531'
  - symbol: get_platform_presets
    kind: function
    at: 'backend/app/api/config.py:L535-L547'
  - symbol: delete_platform_profile
    kind: function
    at: 'backend/app/api/config.py:L551-L570'
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
