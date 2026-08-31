# alembic/versions/0035_publish_profile_location.py · [[alembic-migration-chain]] [[publishing-video-account-matrix]]

Alembic migration adding an optional 'location' column to publish_profiles so each account can inject a location control (e.g. '广东·深圳') into the video channel publish page, defaulting to NULL for backward compatibility without locking the table.

- upgrade · function · L25-L33 — Adds the nullable 'location' VARCHAR(200) column to publish_profiles only if the table exists and the column is not already present, avoiding table locks.
- downgrade · function · L36-L40 — Removes the 'location' column from publish_profiles if the table exists, reverting the schema change.
