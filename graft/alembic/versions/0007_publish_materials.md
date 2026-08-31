# alembic/versions/0007_publish_materials.py · [[alembic-migration-chain]] [[short-drama-production-workflow]]

Alembic migration adding the publish_materials table that records each 'story outline → publish materials' generation history (short title, three video captions, hashtag set, three pinned comments) for short-drama publishing.

- upgrade · function · L25-L39 — Creates the publish_materials table with columns for the story input, generated title/theme/tone/platform/requirements, model used, the JSON material payload, and a created_at timestamp, plus an index on created_at.
- downgrade · function · L42-L44 — Reverses the migration by dropping the created_at index and the publish_materials table.
