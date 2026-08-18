---
name: Short-Drama Production Workflow
slug: short-drama-production-workflow
type: system
sources:
  - path: alembic/versions/0004_watermark.py
    hash: 79ce425f037f6a383f2cfde0df2aadac49e23eed4f9d3d537fb4eb2b3a440add
  - path: alembic/versions/0005_shortdrama_prompts.py
    hash: 5f16a1db84edf801637c4180f13fe8b5530f161577719ac759e3ec614447e389
  - path: alembic/versions/0006_shortdrama_prompt_video.py
    hash: 17748f7e5b48fb50b455f22b51675e37c175de99a53d246287e0a6c007fca5df
  - path: alembic/versions/0007_publish_materials.py
    hash: 8b0c4c883b371a4b217b4e285ff522b1fcb42371528e44d82544285b360cd9b9
  - path: alembic/versions/0009_prompt_versions.py
    hash: f0a5a83f8f0bbde56cc47f39fb440996cfbdd8dc1081e2d50bcbc9b7965afeee
  - path: alembic/versions/0010_watermark_prompt_link.py
    hash: ee7258f3d6106ead06f75aea3afca6c65c5304fcbd8dbf4ab285ebf75a35deff
  - path: alembic/versions/0011_doubao_generation.py
    hash: 1e94b89a8179ec82a699fd0c9b3f4c65e26cc25be115a1f64a27e42312efc7fd
  - path: alembic/versions/0012_prompt_default_duration.py
    hash: 82bfa3ff5260af1c84a0aebb0dd883c99ba6f5df01980f5f23ecb8fa49e21520
  - path: alembic/versions/0014_seedance_generate.py
    hash: fd04ed3d7a4d94f398ebeb7af7669b2e31290917b03cfe7381d4ac08d3a1f8b9
  - path: alembic/versions/0015_doubao_progress.py
    hash: 62fda8c827b06c0061247416c72b8d3bc67273b00618725694b053f6ec1a9c38
  - path: alembic/versions/0016_doubao_screenshot.py
    hash: 0d8249bd7e41c9e562675c03d6b9e343d2c3c59e4ee37257ba190b5f2b7f0bd9
  - path: alembic/versions/0017_doubao_account.py
    hash: 0c90f8eee10cc82ee2f982efc172f3213ff931c31e49261218c43bccc5e12eba
  - path: frontend/src/pages/ShortDrama.tsx
    hash: ab59d2e4d45aacc0bfb7ac7f4909f2f6683f1b376b1004e0abbd0898ac38ae78
sources_digest: cec1d6803a38c9b08ba897e5f92306bc8a8ae7a694684bf650bb073c6812acfd
links:
  - to: alembic-migration-chain
    relation: part_of
    description: These migrations build the short-drama schema across the chain.
  - to: publish-materials-generation
    relation: produces
    description: >-
      Passes pending prompt record IDs to PublishMaterialTab for material
      auto-fill.
  - to: watermark-removal-workflow
    relation: produces
    description: >-
      Hands off generated videos to the Watermark component for removal,
      preserving prompt_record_id links.
generator:
  version: 1
covers:
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0004_watermark.py:L24-L60'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0004_watermark.py:L63-L66'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0005_shortdrama_prompts.py:L24-L38'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0005_shortdrama_prompts.py:L41-L43'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0006_shortdrama_prompt_video.py:L23-L51'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0006_shortdrama_prompt_video.py:L54-L61'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0007_publish_materials.py:L25-L39'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0007_publish_materials.py:L42-L44'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0009_prompt_versions.py:L25-L33'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0009_prompt_versions.py:L36-L38'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0010_watermark_prompt_link.py:L26-L35'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0010_watermark_prompt_link.py:L38-L40'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0011_doubao_generation.py:L29-L74'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0011_doubao_generation.py:L77-L87'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0012_prompt_default_duration.py:L24-L28'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0012_prompt_default_duration.py:L31-L32'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0014_seedance_generate.py:L26-L50'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0014_seedance_generate.py:L53-L59'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0015_doubao_progress.py:L24-L28'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0015_doubao_progress.py:L31-L32'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0016_doubao_screenshot.py:L23-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0016_doubao_screenshot.py:L30-L31'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0017_doubao_account.py:L23-L27'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0017_doubao_account.py:L30-L31'
  - symbol: ShortDrama
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L110-L1881'
  - symbol: handleGenerate
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L346-L378'
  - symbol: handleOptimize
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L381-L401'
  - symbol: handleCopy
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L403-L429'
  - symbol: clearForm
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L431-L442'
  - symbol: openTemplateEditor
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L445-L451'
  - symbol: handleSaveTemplates
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L453-L472'
  - symbol: resetTemplates
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L474-L485'
  - symbol: deleteRecord
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L487-L495'
  - symbol: handleUploadVideo
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L498-L510'
  - symbol: handleDeleteVideo
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L512-L524'
  - symbol: handleImportToWatermark
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L526-L544'
  - symbol: handleDoubaoAccountTypeChange
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L549-L557'
  - symbol: handleSwitchDoubaoAccount
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L561-L572'
  - symbol: handleDoubaoGenerate
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L575-L600'
  - symbol: handleDoubaoCancel
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L603-L618'
  - symbol: handleRewriteDecision
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L621-L655'
  - symbol: isDoubaoActive
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L658-L661'
  - symbol: isSeedanceActive
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L666-L669'
  - symbol: handleSeedanceGenerate
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L672-L703'
  - symbol: handleSeedanceCancel
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L706-L719'
  - symbol: switchDurationMode
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L722-L735'
  - symbol: saveDefaultDuration
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L738-L748'
  - symbol: handleDurationSelect
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L750-L753'
  - symbol: PromptResultBlock
    kind: function
    at: 'frontend/src/pages/ShortDrama.tsx:L1884-L1916'
---
<!-- context:generated:start -->
## Summary

The short-drama generation flow: source copy → Seedance prompt (three-version system: fixed long/short templates with [视频文案] substitution plus AI-generated seven-segment prompt_text) → video generation via either Doubao RPA or Seedance official API (gen_channel for provenance) → video upload → watermark removal → publishing. Finished videos always write back to the existing video_* fields so downstream watermark/publish steps need zero changes. Doubao flow tracks progress (0-100), screenshots, and account via Celery callbacks.

## Related

- part of [[alembic-migration-chain]] — These migrations build the short-drama schema across the chain.
- produces [[publish-materials-generation]] — Passes pending prompt record IDs to PublishMaterialTab for material auto-fill.
- produces [[watermark-removal-workflow]] — Hands off generated videos to the Watermark component for removal, preserving prompt_record_id links.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
