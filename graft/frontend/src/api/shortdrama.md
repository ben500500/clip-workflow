# frontend/src/api/shortdrama.ts · [[frontend-api-client-layer]]

API client module for all short-drama prompt generation, video upload, Doubao RPA, and Seedance API workflows.

- ShortdramaPromptRecord · interface · L3-L45 — Data shape for a persisted short-drama prompt record including generated video attachments and both Doubao RPA and Seedance API generation task states.
- DoubaoRewriteItem · interface · L47-L54 — Data shape for a single Doubao prompt rewrite attempt with original, rewritten text, and reason.
- DoubaoGenerateParams · interface · L56-L59 — Parameters for triggering a Doubao RPA generation, selecting free or pro account type and optional duration.
- DoubaoGenerateResult · interface · L61-L65 — Result shape returned when starting a Doubao RPA generation task.
- SeedanceGenerateResult · interface · L67-L71 — Result shape returned when starting a Seedance API generation task.
- PromptGenerateParams · interface · L73-L83 — Input parameters for generating a short-drama prompt, including optional save and save-duration-as-default flags.
- PromptGenerateResult · interface · L85-L96 — Result shape of prompt generation with the generated prompt, optional long/short/AI versions, and record id.
- PromptTemplates · interface · L98-L102 — Data shape for editable long and short prompt templates that can be persisted.
- ScriptOptimizeParams · interface · L104-L109 — Input parameters for optimizing a short-drama script with optional theme, tone, and extra requirements.
- ScriptOptimizeResult · interface · L111-L115 — Result shape of script optimization containing the optimized text.
