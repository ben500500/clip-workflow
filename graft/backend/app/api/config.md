# backend/app/api/config.py

- ConfigUpdateRequest · class · L17-L19 — Request body for updating or resetting a single config key-value pair.
- ConfigResponse · class · L22-L26 — Response schema for a config entry including key, value, optional description, and updated timestamp.
- ProfileCreate · class · L29-L36 — Request body for creating a new platform profile with dedupe and encoding settings.
- ProfileUpdate · class · L39-L46 — Request body for partially updating an existing platform profile; all fields optional.
- ProfileResponse · class · L49-L60 — Response schema for a platform profile including id, dedupe config, and encoding targets.
- _default_profile_for · function · L274-L282 — Finds the built-in default dedupe recipe for a profile by matching name first, then platform, to support restoring defaults.
- _serialize_config · function · L285-L291 — Converts a SystemConfig ORM row into a plain dict, falling back to built-in descriptions when none stored.
- _serialize_profile · function · L294-L305 — Converts a PlatformProfile ORM row into a plain dict for API responses.
- get_all_config · function · L309-L338 — Returns all config entries by merging saved DB values over built-in defaults, so unmodified defaults still appear and user-added custom keys are included.
- update_config · function · L342-L367 — Upserts a config value, updating an existing row or creating a new one, and stamps the current timestamp.
- reset_config_default · function · L371-L398 — Restores a config key to its built-in default by deleting any DB override record, returning the default value.
- list_platform_profiles · function · L402-L408 — Lists all platform profiles ordered by name.
- create_platform_profile · function · L412-L439 — Creates a new platform profile, rejecting duplicate names with a 409 conflict.
- update_platform_profile · function · L443-L490 — Partially updates a platform profile, validating UUID format and rejecting duplicate names while applying only provided fields.
- reset_platform_profile_default · function · L494-L530 — Restores a platform profile's dedupe/encoding settings to the built-in default recipe for its name or platform.
- get_platform_presets · function · L534-L546 — Returns the curated per-platform resolution/bitrate quick-select options for the frontend dropdown.
- delete_platform_profile · function · L550-L569 — Deletes a platform profile by id, validating UUID format and returning 404 if not found.
