---
name: Drama Management & Import
slug: drama-management-import
type: system
sources:
  - path: backend/app/api/dramas.py
    hash: 376897f4f9eb3ae6cf47db97bdd042041c84f855764b241b8282b6792c2934b5
sources_digest: d836dcd25c047a9b8c05ae6eaabc6f106720be35bd04d1d0e4e2c4731ee1540f
links:
  - to: minio-storage-upload
    relation: uses
    description: Manages drama stills in MinIO with presigned URLs and image uploads.
generator:
  version: 1
covers:
  - symbol: DramaCreate
    kind: class
    at: 'backend/app/api/dramas.py:L45-L60'
  - symbol: DramaUpdate
    kind: class
    at: 'backend/app/api/dramas.py:L63-L76'
  - symbol: DramaStillPayload
    kind: class
    at: 'backend/app/api/dramas.py:L79-L82'
  - symbol: DramaLinkAccounts
    kind: class
    at: 'backend/app/api/dramas.py:L85-L86'
  - symbol: _resolve_image_url
    kind: function
    at: 'backend/app/api/dramas.py:L91-L98'
  - symbol: _serialize_drama
    kind: function
    at: 'backend/app/api/dramas.py:L101-L123'
  - symbol: _serialize_drama_detail
    kind: function
    at: 'backend/app/api/dramas.py:L126-L138'
  - symbol: _resolve_drama
    kind: function
    at: 'backend/app/api/dramas.py:L143-L152'
  - symbol: _can_manage
    kind: function
    at: 'backend/app/api/dramas.py:L155-L160'
  - symbol: _apply_rbac_filter
    kind: function
    at: 'backend/app/api/dramas.py:L163-L166'
  - symbol: _associate_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L169-L182'
  - symbol: list_dramas
    kind: function
    at: 'backend/app/api/dramas.py:L188-L226'
  - symbol: create_drama
    kind: function
    at: 'backend/app/api/dramas.py:L230-L274'
  - symbol: get_drama
    kind: function
    at: 'backend/app/api/dramas.py:L278-L287'
  - symbol: update_drama
    kind: function
    at: 'backend/app/api/dramas.py:L291-L326'
  - symbol: delete_drama
    kind: function
    at: 'backend/app/api/dramas.py:L330-L341'
  - symbol: add_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L347-L363'
  - symbol: delete_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L367-L386'
  - symbol: upload_drama_image
    kind: function
    at: 'backend/app/api/dramas.py:L390-L445'
  - symbol: link_drama_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L451-L464'
  - symbol: DramaImportRow
    kind: class
    at: 'backend/app/api/dramas.py:L469-L484'
  - symbol: DramaImportRequest
    kind: class
    at: 'backend/app/api/dramas.py:L487-L489'
  - symbol: DramaImportConfirmItem
    kind: class
    at: 'backend/app/api/dramas.py:L492-L510'
  - symbol: DramaImportConfirm
    kind: class
    at: 'backend/app/api/dramas.py:L513-L516'
  - symbol: _row_key
    kind: function
    at: 'backend/app/api/dramas.py:L519-L521'
  - symbol: _diff_fields
    kind: function
    at: 'backend/app/api/dramas.py:L524-L542'
  - symbol: drama_import_preview
    kind: function
    at: 'backend/app/api/dramas.py:L546-L609'
  - symbol: drama_import_parse
    kind: function
    at: 'backend/app/api/dramas.py:L613-L695'
  - symbol: _norm
    kind: function
    at: 'backend/app/api/dramas.py:L649-L650'
  - symbol: _find
    kind: function
    at: 'backend/app/api/dramas.py:L654-L659'
  - symbol: drama_import_confirm
    kind: function
    at: 'backend/app/api/dramas.py:L699-L821'
  - symbol: get_drama_publish_context
    kind: function
    at: 'backend/app/api/dramas.py:L827-L841'
  - symbol: DramaMaterialLink
    kind: class
    at: 'backend/app/api/dramas.py:L844-L847'
  - symbol: link_drama_material
    kind: function
    at: 'backend/app/api/dramas.py:L851-L875'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/api/dramas.py:L880-L885'
  - symbol: _parse_dt
    kind: function
    at: 'backend/app/api/dramas.py:L888-L893'
---
<!-- context:generated:start -->
## Summary

Drama CRUD with RBAC data-scope filtering (operators see only their own dramas; admins/publishers full access). Three-stage preview/confirm import workflow using drama name as dedup key, returning new/update/unchanged groups with field-level diffs, writing only user-selected items. Generates unique drama codes DR-<8-digit HEX> with collision retry, masks material link passwords in responses, and uses pandas with fuzzy Chinese-header column matching for Excel/CSV import.

## Related

- uses [[minio-storage-upload]] — Manages drama stills in MinIO with presigned URLs and image uploads.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
