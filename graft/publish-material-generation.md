---
name: Publish Material Generation
slug: publish-material-generation
type: system
sources:
  - path: backend/app/api/publish_material.py
    hash: 2b34681ec436089ea831736bde98277d4ed83e17e4ac5b13ec4242ecaaf9bfa9
sources_digest: 3dcf62aa3c4e81fdbab545e32d8738b41d418c9a4916b029177682ea9839d1f1
links:
  - to: data-isolation-access-control
    relation: uses
    description: from-output path verifies project ownership or admin access.
  - to: seedance-prompt-generation
    relation: uses
    description: Both call the external AutoClip service reusing the same LLM config.
generator:
  version: 1
covers:
  - symbol: PublishMaterialGenerateRequest
    kind: class
    at: 'backend/app/api/publish_material.py:L42-L54'
  - symbol: PublishMaterialGenerateFromOutputRequest
    kind: class
    at: 'backend/app/api/publish_material.py:L57-L66'
  - symbol: PublishMaterialGenerateResponse
    kind: class
    at: 'backend/app/api/publish_material.py:L69-L73'
  - symbol: PublishMaterialRecordItem
    kind: class
    at: 'backend/app/api/publish_material.py:L76-L86'
  - symbol: _serialize_record
    kind: function
    at: 'backend/app/api/publish_material.py:L94-L113'
  - symbol: generate_publish_material
    kind: function
    at: 'backend/app/api/publish_material.py:L125-L205'
  - symbol: _build_story_from_output
    kind: function
    at: 'backend/app/api/publish_material.py:L208-L291'
  - symbol: generate_publish_material_from_output
    kind: function
    at: 'backend/app/api/publish_material.py:L298-L373'
  - symbol: list_publish_materials
    kind: function
    at: 'backend/app/api/publish_material.py:L377-L390'
  - symbol: get_publish_material
    kind: function
    at: 'backend/app/api/publish_material.py:L397-L403'
  - symbol: delete_publish_material
    kind: function
    at: 'backend/app/api/publish_material.py:L407-L415'
  - symbol: _get_record_or_404
    kind: function
    at: 'backend/app/api/publish_material.py:L418-L429'
---
<!-- context:generated:start -->
## Summary

v7 short-drama publish material API: generates short titles, three video captions, hashtag sets, and three pinned interactive comments from raw story text or an existing SliceOutput (assembling context from linked Project/Episode/ClipCandidate). Delegates to the external AutoClip service via HTTP, reusing the same DASHSCOPE config. Enforces strict output ordering, optional persistence via a save flag, and falls back to slice filename for story construction when no contextual metadata exists.

## Related

- uses [[data-isolation-access-control]] — from-output path verifies project ownership or admin access.
- uses [[seedance-prompt-generation]] — Both call the external AutoClip service reusing the same LLM config.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
