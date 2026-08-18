# backend/app/api/publish_material.py

- PublishMaterialGenerateRequest · class · L42-L54 — Request model for generating publish material from a user-supplied story synopsis with optional title/theme/tone/platform overrides.
- PublishMaterialGenerateFromOutputRequest · class · L57-L66 — Request model for generating publish material from a slice output id, auto-assembling the story from upstream context.
- PublishMaterialGenerateResponse · class · L69-L73 — Response model wrapping generated material, model name, and optional saved record id.
- PublishMaterialRecordItem · class · L76-L86 — Response model for a single publish-material generation history record.
- _serialize_record · function · L94-L113 — Converts a PublishMaterial ORM record into an API dict, parsing material_json from string to dict when needed.
- generate_publish_material · function · L125-L205 — Generates a full set of publish material (short title, 3 captions, hashtags, 3 pinned comments) by calling AutoClip with the user's story synopsis, and optionally persists it to history.
- _build_story_from_output · function · L208-L291 — Assembles a story synopsis from a slice output's upstream chain (project/episode/clip candidate) and enforces data-isolation access control on the owning project.
- generate_publish_material_from_output · function · L298-L373 — Generates publish material from a slice output by auto-building the story from upstream context and calling AutoClip, then persisting the result.
- list_publish_materials · function · L377-L390 — Lists publish-material generation history ordered by creation time descending with a bounded limit.
- get_publish_material · function · L397-L403 — Fetches and serializes a single publish-material generation record by id.
- delete_publish_material · function · L407-L415 — Deletes a single publish-material generation record by id.
- _get_record_or_404 · function · L418-L429 — Looks up a PublishMaterial by UUID id, raising 400 for invalid ids and 404 when not found.
