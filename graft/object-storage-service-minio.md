---
name: Object Storage Service (MinIO)
slug: object-storage-service-minio
type: system
sources:
  - path: backend/app/services/minio_service.py
    hash: 7a6f0ad14ec96f190e49c71a8305719726688bb9dc03816555bc05cc41c382b1
sources_digest: 3180034db6bd2b274c24a5441f4c6ad5273cf4fa39a91e89c9f893e85c20e30e
links:
  - to: variant-generation-pipeline
    relation: uses
    description: variant_service downloads base videos from MinIO and persists variants
  - to: wechat-download-pipeline
    relation: uses
    description: >-
      service.py uploads downloaded videos via
      minio_service.upload_file_from_path
generator:
  version: 1
covers:
  - symbol: _parse_endpoint
    kind: function
    at: 'backend/app/services/minio_service.py:L22-L30'
  - symbol: get_minio_client
    kind: function
    at: 'backend/app/services/minio_service.py:L33-L46'
  - symbol: get_external_minio_client
    kind: function
    at: 'backend/app/services/minio_service.py:L49-L72'
  - symbol: _generate_presigned_url
    kind: function
    at: 'backend/app/services/minio_service.py:L75-L107'
  - symbol: upload_file
    kind: function
    at: 'backend/app/services/minio_service.py:L110-L141'
  - symbol: upload_file_from_path
    kind: function
    at: 'backend/app/services/minio_service.py:L144-L173'
  - symbol: _download_sync
    kind: function
    at: 'backend/app/services/minio_service.py:L176-L185'
  - symbol: download_file
    kind: function
    at: 'backend/app/services/minio_service.py:L188-L199'
  - symbol: get_presigned_url
    kind: function
    at: 'backend/app/services/minio_service.py:L202-L242'
  - symbol: get_presigned_upload_url
    kind: function
    at: 'backend/app/services/minio_service.py:L245-L265'
  - symbol: delete_file
    kind: function
    at: 'backend/app/services/minio_service.py:L268-L278'
  - symbol: _list_objects_sync
    kind: function
    at: 'backend/app/services/minio_service.py:L281-L293'
  - symbol: list_files
    kind: function
    at: 'backend/app/services/minio_service.py:L296-L304'
  - symbol: get_file_info
    kind: function
    at: 'backend/app/services/minio_service.py:L307-L321'
  - symbol: ensure_bucket
    kind: function
    at: 'backend/app/services/minio_service.py:L324-L336'
  - symbol: download_to_file
    kind: function
    at: 'backend/app/services/minio_service.py:L339-L362'
---
<!-- context:generated:start -->
## Summary

Centralized async wrapper around the MinIO/S3 SDK. Provides cached client factories (internal vs external endpoint split), CRUD operations offloaded to the event loop, and presigned URL generation. The internal/external endpoint split is deliberate: upload URLs always use the internal endpoint (for Worker containers) while GET URLs prefer the external endpoint (for browsers), working around container-internal hostnames like minio:9000 that break SigV4 signatures.

## Related

- uses [[variant-generation-pipeline]] — variant_service downloads base videos from MinIO and persists variants
- uses [[wechat-download-pipeline]] — service.py uploads downloaded videos via minio_service.upload_file_from_path
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
