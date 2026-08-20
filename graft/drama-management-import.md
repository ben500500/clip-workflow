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
    at: 'backend/app/api/dramas.py:L85-L102'
  - symbol: DramaUpdate
    kind: class
    at: 'backend/app/api/dramas.py:L105-L119'
  - symbol: DramaStillPayload
    kind: class
    at: 'backend/app/api/dramas.py:L122-L125'
  - symbol: DramaLinkAccounts
    kind: class
    at: 'backend/app/api/dramas.py:L128-L129'
  - symbol: _resolve_image_url
    kind: function
    at: 'backend/app/api/dramas.py:L134-L141'
  - symbol: _serialize_drama
    kind: function
    at: 'backend/app/api/dramas.py:L144-L167'
  - symbol: _serialize_drama_detail
    kind: function
    at: 'backend/app/api/dramas.py:L170-L185'
  - symbol: _resolve_drama
    kind: function
    at: 'backend/app/api/dramas.py:L190-L207'
  - symbol: _can_manage
    kind: function
    at: 'backend/app/api/dramas.py:L210-L215'
  - symbol: _apply_rbac_filter
    kind: function
    at: 'backend/app/api/dramas.py:L218-L221'
  - symbol: _associate_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L224-L237'
  - symbol: list_topic_presets
    kind: function
    at: 'backend/app/api/dramas.py:L243-L257'
  - symbol: list_dramas
    kind: function
    at: 'backend/app/api/dramas.py:L261-L299'
  - symbol: create_drama
    kind: function
    at: 'backend/app/api/dramas.py:L303-L358'
  - symbol: get_drama
    kind: function
    at: 'backend/app/api/dramas.py:L362-L371'
  - symbol: update_drama
    kind: function
    at: 'backend/app/api/dramas.py:L375-L410'
  - symbol: delete_drama
    kind: function
    at: 'backend/app/api/dramas.py:L414-L425'
  - symbol: add_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L431-L447'
  - symbol: delete_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L451-L470'
  - symbol: upload_drama_image
    kind: function
    at: 'backend/app/api/dramas.py:L474-L529'
  - symbol: link_drama_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L535-L548'
  - symbol: DramaImportRow
    kind: class
    at: 'backend/app/api/dramas.py:L553-L568'
  - symbol: DramaImportRequest
    kind: class
    at: 'backend/app/api/dramas.py:L571-L573'
  - symbol: DramaImportConfirmItem
    kind: class
    at: 'backend/app/api/dramas.py:L576-L594'
  - symbol: DramaImportConfirm
    kind: class
    at: 'backend/app/api/dramas.py:L597-L600'
  - symbol: _row_key
    kind: function
    at: 'backend/app/api/dramas.py:L603-L605'
  - symbol: _diff_fields
    kind: function
    at: 'backend/app/api/dramas.py:L608-L626'
  - symbol: drama_import_preview
    kind: function
    at: 'backend/app/api/dramas.py:L630-L693'
  - symbol: drama_import_parse
    kind: function
    at: 'backend/app/api/dramas.py:L697-L779'
  - symbol: _norm
    kind: function
    at: 'backend/app/api/dramas.py:L733-L734'
  - symbol: _find
    kind: function
    at: 'backend/app/api/dramas.py:L738-L743'
  - symbol: drama_import_confirm
    kind: function
    at: 'backend/app/api/dramas.py:L783-L905'
  - symbol: get_drama_publish_context
    kind: function
    at: 'backend/app/api/dramas.py:L911-L927'
  - symbol: DramaMaterialLink
    kind: class
    at: 'backend/app/api/dramas.py:L930-L933'
  - symbol: link_drama_material
    kind: function
    at: 'backend/app/api/dramas.py:L937-L961'
  - symbol: DramaLinkEpisodes
    kind: class
    at: 'backend/app/api/dramas.py:L966-L968'
  - symbol: link_drama_episodes
    kind: function
    at: 'backend/app/api/dramas.py:L972-L1035'
  - symbol: get_drama_slice_status
    kind: function
    at: 'backend/app/api/dramas.py:L1039-L1154'
  - symbol: _stage_status
    kind: function
    at: 'backend/app/api/dramas.py:L1091-L1101'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/api/dramas.py:L1159-L1164'
  - symbol: _parse_dt
    kind: function
    at: 'backend/app/api/dramas.py:L1167-L1172'
---
<!-- context:generated:start -->
## Summary

Drama CRUD with RBAC data-scope filtering (operators see only their own dramas; admins/publishers full access). Three-stage preview/confirm import workflow using drama name as dedup key, returning new/update/unchanged groups with field-level diffs, writing only user-selected items. Generates unique drama codes DR-<8-digit HEX> with collision retry, masks material link passwords in responses, and uses pandas with fuzzy Chinese-header column matching for Excel/CSV import.

## Related

- uses [[minio-storage-upload]] — Manages drama stills in MinIO with presigned URLs and image uploads.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
