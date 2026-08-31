# backend/app/api/config.py · [[system-config-platform-profiles]]

- ConfigUpdateRequest · class · L17-L19 — Request body for updating or resetting a single config key-value pair.
- ConfigResponse · class · L22-L26 — Response schema for a config entry including key, value, optional description, and updated timestamp.
- ProfileCreate · class · L29-L36 — Request body for creating a new platform profile with dedupe and encoding settings.
- ProfileUpdate · class · L39-L46 — Request body for partially updating an existing platform profile; all fields optional.
- ProfileResponse · class · L49-L60 — Response schema for a platform profile including id, dedupe config, and encoding targets.
- _default_profile_for · function · L335-L343 — Finds the built-in default dedupe recipe for a profile by matching name first, then platform, to support restoring defaults.
- _serialize_config · function · L346-L352 — Converts a SystemConfig ORM row into a plain dict, falling back to built-in descriptions when none stored.
- _serialize_profile · function · L355-L366 — Converts a PlatformProfile ORM row into a plain dict for API responses.
- get_all_config · function · L370-L399 — Returns all config entries by merging saved DB values over built-in defaults, so unmodified defaults still appear and user-added custom keys are included.
- update_config · function · L403-L428 — Upserts a config value, updating an existing row or creating a new one, and stamps the current timestamp.
- reset_config_default · function · L432-L459 — Restores a config key to its built-in default by deleting any DB override record, returning the default value.
- list_platform_profiles · function · L463-L469 — Lists all platform profiles ordered by name.
- create_platform_profile · function · L473-L500 — Creates a new platform profile, rejecting duplicate names with a 409 conflict.
- update_platform_profile · function · L504-L551 — Partially updates a platform profile, validating UUID format and rejecting duplicate names while applying only provided fields.
- reset_platform_profile_default · function · L555-L591 — Restores a platform profile's dedupe/encoding settings to the built-in default recipe for its name or platform.
- get_platform_presets · function · L595-L607 — Returns the curated per-platform resolution/bitrate quick-select options for the frontend dropdown.
- delete_platform_profile · function · L611-L630 — Deletes a platform profile by id, validating UUID format and returning 404 if not found.
