---
name: Resumable Upload Service
slug: resumable-upload-service
type: system
sources:
  - path: backend/app/services/upload_service.py
    hash: 5b6276c62d071348518f752d19994e5715415aceae28e547d39fa9d596b1d8c4
sources_digest: 932b8379480663f335ad0dc6d607cb2bb44529d17ce5369fe1beb09d142ea577
links: []
generator:
  version: 1
covers:
  - symbol: _get_redis
    kind: function
    at: 'backend/app/services/upload_service.py:L20-L24'
  - symbol: _deserialize_session
    kind: function
    at: 'backend/app/services/upload_service.py:L27-L40'
  - symbol: create_upload_session
    kind: function
    at: 'backend/app/services/upload_service.py:L43-L70'
  - symbol: get_upload_session
    kind: function
    at: 'backend/app/services/upload_service.py:L73-L79'
  - symbol: _rebuild_hash
    kind: function
    at: 'backend/app/services/upload_service.py:L82-L94'
  - symbol: write_chunk
    kind: function
    at: 'backend/app/services/upload_service.py:L97-L152'
  - symbol: finalize_upload
    kind: function
    at: 'backend/app/services/upload_service.py:L155-L191'
  - symbol: get_upload_progress
    kind: function
    at: 'backend/app/services/upload_service.py:L194-L211'
  - symbol: delete_upload_session
    kind: function
    at: 'backend/app/services/upload_service.py:L214-L231'
  - symbol: get_temp_file_path
    kind: function
    at: 'backend/app/services/upload_service.py:L234-L236'
  - symbol: validate_file_name
    kind: function
    at: 'backend/app/services/upload_service.py:L239-L248'
---
<!-- context:generated:start -->
## Summary

tus-like resumable upload protocol storing session state (offset, completion flag, hash digest) in Redis hashes with 24-hour TTL and chunks on disk under settings.UPLOAD_TEMP_DIR. Enforces strict offset ordering, rejects writes to completed sessions, validates extensions. Notable compromise: MD5 hashing cannot restore internal state from a hex digest, so write_chunk recomputes the hash from all on-disk chunks on every write.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
