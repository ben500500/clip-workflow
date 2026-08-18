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
    at: 'backend/app/api/dramas.py:L46-L61'
  - symbol: DramaUpdate
    kind: class
    at: 'backend/app/api/dramas.py:L64-L77'
  - symbol: DramaStillPayload
    kind: class
    at: 'backend/app/api/dramas.py:L80-L83'
  - symbol: DramaLinkAccounts
    kind: class
    at: 'backend/app/api/dramas.py:L86-L87'
  - symbol: _resolve_image_url
    kind: function
    at: 'backend/app/api/dramas.py:L92-L99'
  - symbol: _serialize_drama
    kind: function
    at: 'backend/app/api/dramas.py:L102-L124'
  - symbol: _serialize_drama_detail
    kind: function
    at: 'backend/app/api/dramas.py:L127-L142'
  - symbol: _resolve_drama
    kind: function
    at: 'backend/app/api/dramas.py:L147-L164'
  - symbol: _can_manage
    kind: function
    at: 'backend/app/api/dramas.py:L167-L172'
  - symbol: _apply_rbac_filter
    kind: function
    at: 'backend/app/api/dramas.py:L175-L178'
  - symbol: _associate_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L181-L194'
  - symbol: list_dramas
    kind: function
    at: 'backend/app/api/dramas.py:L200-L238'
  - symbol: create_drama
    kind: function
    at: 'backend/app/api/dramas.py:L242-L296'
  - symbol: get_drama
    kind: function
    at: 'backend/app/api/dramas.py:L300-L309'
  - symbol: update_drama
    kind: function
    at: 'backend/app/api/dramas.py:L313-L348'
  - symbol: delete_drama
    kind: function
    at: 'backend/app/api/dramas.py:L352-L363'
  - symbol: add_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L369-L385'
  - symbol: delete_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L389-L408'
  - symbol: upload_drama_image
    kind: function
    at: 'backend/app/api/dramas.py:L412-L467'
  - symbol: link_drama_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L473-L486'
  - symbol: DramaImportRow
    kind: class
    at: 'backend/app/api/dramas.py:L491-L506'
  - symbol: DramaImportRequest
    kind: class
    at: 'backend/app/api/dramas.py:L509-L511'
  - symbol: DramaImportConfirmItem
    kind: class
    at: 'backend/app/api/dramas.py:L514-L532'
  - symbol: DramaImportConfirm
    kind: class
    at: 'backend/app/api/dramas.py:L535-L538'
  - symbol: _row_key
    kind: function
    at: 'backend/app/api/dramas.py:L541-L543'
  - symbol: _diff_fields
    kind: function
    at: 'backend/app/api/dramas.py:L546-L564'
  - symbol: drama_import_preview
    kind: function
    at: 'backend/app/api/dramas.py:L568-L631'
  - symbol: drama_import_parse
    kind: function
    at: 'backend/app/api/dramas.py:L635-L717'
  - symbol: _norm
    kind: function
    at: 'backend/app/api/dramas.py:L671-L672'
  - symbol: _find
    kind: function
    at: 'backend/app/api/dramas.py:L676-L681'
  - symbol: drama_import_confirm
    kind: function
    at: 'backend/app/api/dramas.py:L721-L843'
  - symbol: get_drama_publish_context
    kind: function
    at: 'backend/app/api/dramas.py:L849-L863'
  - symbol: DramaMaterialLink
    kind: class
    at: 'backend/app/api/dramas.py:L866-L869'
  - symbol: link_drama_material
    kind: function
    at: 'backend/app/api/dramas.py:L873-L897'
  - symbol: DramaLinkEpisodes
    kind: class
    at: 'backend/app/api/dramas.py:L902-L904'
  - symbol: link_drama_episodes
    kind: function
    at: 'backend/app/api/dramas.py:L908-L971'
  - symbol: get_drama_slice_status
    kind: function
    at: 'backend/app/api/dramas.py:L975-L1090'
  - symbol: _stage_status
    kind: function
    at: 'backend/app/api/dramas.py:L1027-L1037'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/api/dramas.py:L1095-L1100'
  - symbol: _parse_dt
    kind: function
    at: 'backend/app/api/dramas.py:L1103-L1108'
---
<!-- context:generated:start -->
## Summary

Drama CRUD with RBAC data-scope filtering (operators see only their own dramas; admins/publishers full access). Three-stage preview/confirm import workflow using drama name as dedup key, returning new/update/unchanged groups with field-level diffs, writing only user-selected items. Generates unique drama codes DR-<8-digit HEX> with collision retry, masks material link passwords in responses, and uses pandas with fuzzy Chinese-header column matching for Excel/CSV import.

## Related

- uses [[minio-storage-upload]] — Manages drama stills in MinIO with presigned URLs and image uploads.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
