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
    at: 'backend/app/api/dramas.py:L90-L111'
  - symbol: DramaUpdate
    kind: class
    at: 'backend/app/api/dramas.py:L114-L132'
  - symbol: DramaStillPayload
    kind: class
    at: 'backend/app/api/dramas.py:L135-L138'
  - symbol: DramaLinkAccounts
    kind: class
    at: 'backend/app/api/dramas.py:L141-L142'
  - symbol: _resolve_image_url
    kind: function
    at: 'backend/app/api/dramas.py:L147-L154'
  - symbol: _load_drama_theaters
    kind: function
    at: 'backend/app/api/dramas.py:L158-L160'
  - symbol: _serialize_drama
    kind: function
    at: 'backend/app/api/dramas.py:L163-L207'
  - symbol: _serialize_drama_detail
    kind: function
    at: 'backend/app/api/dramas.py:L210-L225'
  - symbol: _resolve_drama
    kind: function
    at: 'backend/app/api/dramas.py:L230-L248'
  - symbol: _can_manage
    kind: function
    at: 'backend/app/api/dramas.py:L251-L256'
  - symbol: _apply_rbac_filter
    kind: function
    at: 'backend/app/api/dramas.py:L259-L262'
  - symbol: _sync_drama_theaters
    kind: function
    at: 'backend/app/api/dramas.py:L265-L297'
  - symbol: _associate_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L300-L313'
  - symbol: list_topic_presets
    kind: function
    at: 'backend/app/api/dramas.py:L319-L333'
  - symbol: list_dramas
    kind: function
    at: 'backend/app/api/dramas.py:L337-L404'
  - symbol: create_drama
    kind: function
    at: 'backend/app/api/dramas.py:L408-L471'
  - symbol: get_drama
    kind: function
    at: 'backend/app/api/dramas.py:L475-L484'
  - symbol: update_drama
    kind: function
    at: 'backend/app/api/dramas.py:L488-L533'
  - symbol: delete_drama
    kind: function
    at: 'backend/app/api/dramas.py:L537-L548'
  - symbol: add_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L554-L570'
  - symbol: delete_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L574-L593'
  - symbol: upload_drama_image
    kind: function
    at: 'backend/app/api/dramas.py:L597-L652'
  - symbol: link_drama_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L658-L671'
  - symbol: DramaImportRow
    kind: class
    at: 'backend/app/api/dramas.py:L676-L693'
  - symbol: DramaImportRequest
    kind: class
    at: 'backend/app/api/dramas.py:L696-L698'
  - symbol: DramaImportConfirmItem
    kind: class
    at: 'backend/app/api/dramas.py:L701-L720'
  - symbol: DramaImportConfirm
    kind: class
    at: 'backend/app/api/dramas.py:L723-L726'
  - symbol: _row_key
    kind: function
    at: 'backend/app/api/dramas.py:L729-L731'
  - symbol: _validate_import_rating
    kind: function
    at: 'backend/app/api/dramas.py:L734-L748'
  - symbol: _diff_fields
    kind: function
    at: 'backend/app/api/dramas.py:L751-L782'
  - symbol: _split_theater_names
    kind: function
    at: 'backend/app/api/dramas.py:L785-L795'
  - symbol: _resolve_theater_ids
    kind: function
    at: 'backend/app/api/dramas.py:L798-L820'
  - symbol: _resolve_theater_id
    kind: function
    at: 'backend/app/api/dramas.py:L823-L829'
  - symbol: drama_import_preview
    kind: function
    at: 'backend/app/api/dramas.py:L833-L906'
  - symbol: drama_import_parse
    kind: function
    at: 'backend/app/api/dramas.py:L910-L1005'
  - symbol: _norm
    kind: function
    at: 'backend/app/api/dramas.py:L946-L947'
  - symbol: _find
    kind: function
    at: 'backend/app/api/dramas.py:L951-L956'
  - symbol: drama_import_confirm
    kind: function
    at: 'backend/app/api/dramas.py:L1009-L1183'
  - symbol: FeishuImportRequest
    kind: class
    at: 'backend/app/api/dramas.py:L1188-L1189'
  - symbol: drama_import_feishu
    kind: function
    at: 'backend/app/api/dramas.py:L1193-L1206'
  - symbol: drama_import_feishu_roster
    kind: function
    at: 'backend/app/api/dramas.py:L1210-L1235'
  - symbol: drama_feishu_roster_status
    kind: function
    at: 'backend/app/api/dramas.py:L1239-L1250'
  - symbol: get_drama_publish_context
    kind: function
    at: 'backend/app/api/dramas.py:L1256-L1272'
  - symbol: DramaMaterialLink
    kind: class
    at: 'backend/app/api/dramas.py:L1275-L1278'
  - symbol: link_drama_material
    kind: function
    at: 'backend/app/api/dramas.py:L1282-L1306'
  - symbol: DramaLinkEpisodes
    kind: class
    at: 'backend/app/api/dramas.py:L1311-L1313'
  - symbol: link_drama_episodes
    kind: function
    at: 'backend/app/api/dramas.py:L1317-L1381'
  - symbol: get_drama_slice_status
    kind: function
    at: 'backend/app/api/dramas.py:L1385-L1500'
  - symbol: _stage_status
    kind: function
    at: 'backend/app/api/dramas.py:L1437-L1447'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/api/dramas.py:L1505-L1519'
  - symbol: _parse_dt
    kind: function
    at: 'backend/app/api/dramas.py:L1522-L1545'
---
<!-- context:generated:start -->
## Summary

Drama CRUD with RBAC data-scope filtering (operators see only their own dramas; admins/publishers full access). Three-stage preview/confirm import workflow using drama name as dedup key, returning new/update/unchanged groups with field-level diffs, writing only user-selected items. Generates unique drama codes DR-<8-digit HEX> with collision retry, masks material link passwords in responses, and uses pandas with fuzzy Chinese-header column matching for Excel/CSV import.

## Related

- uses [[minio-storage-upload]] — Manages drama stills in MinIO with presigned URLs and image uploads.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
