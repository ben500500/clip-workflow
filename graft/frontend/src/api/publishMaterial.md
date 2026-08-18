# frontend/src/api/publishMaterial.ts · [[frontend-api-layer]]

API client module for generating, listing, fetching, and deleting short-drama publish materials (short titles, captions, tags, and pinned comments).

- PublishMaterial · interface · L4-L13 — Data shape for a generated publish material bundle: short title, three caption variants, hashtag sets, and pinned comment suggestions.
- PublishMaterialRecord · interface · L15-L27 — Persisted record of a publish material generation, tying it to its source story, generation parameters, and prompt record.
- PublishMaterialGenerateParams · interface · L29-L38 — Input parameters for generating publish material from a story, with optional theme/tone/platform overrides and a save flag.
- PublishMaterialGenerateFromOutputParams · interface · L40-L47 — Input parameters for generating publish material directly from an existing sliced output, reusing its content with optional overrides.
