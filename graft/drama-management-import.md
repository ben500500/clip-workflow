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
    at: 'backend/app/api/dramas.py:L89-L110'
  - symbol: DramaUpdate
    kind: class
    at: 'backend/app/api/dramas.py:L113-L131'
  - symbol: DramaStillPayload
    kind: class
    at: 'backend/app/api/dramas.py:L134-L137'
  - symbol: DramaLinkAccounts
    kind: class
    at: 'backend/app/api/dramas.py:L140-L141'
  - symbol: _resolve_image_url
    kind: function
    at: 'backend/app/api/dramas.py:L146-L153'
  - symbol: _load_drama_theaters
    kind: function
    at: 'backend/app/api/dramas.py:L157-L159'
  - symbol: _serialize_drama
    kind: function
    at: 'backend/app/api/dramas.py:L162-L204'
  - symbol: _serialize_drama_detail
    kind: function
    at: 'backend/app/api/dramas.py:L207-L222'
  - symbol: _resolve_drama
    kind: function
    at: 'backend/app/api/dramas.py:L227-L245'
  - symbol: _can_manage
    kind: function
    at: 'backend/app/api/dramas.py:L248-L253'
  - symbol: _apply_rbac_filter
    kind: function
    at: 'backend/app/api/dramas.py:L256-L259'
  - symbol: _sync_drama_theaters
    kind: function
    at: 'backend/app/api/dramas.py:L262-L294'
  - symbol: _associate_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L297-L310'
  - symbol: list_topic_presets
    kind: function
    at: 'backend/app/api/dramas.py:L316-L330'
  - symbol: list_dramas
    kind: function
    at: 'backend/app/api/dramas.py:L334-L383'
  - symbol: create_drama
    kind: function
    at: 'backend/app/api/dramas.py:L387-L450'
  - symbol: get_drama
    kind: function
    at: 'backend/app/api/dramas.py:L454-L463'
  - symbol: update_drama
    kind: function
    at: 'backend/app/api/dramas.py:L467-L512'
  - symbol: delete_drama
    kind: function
    at: 'backend/app/api/dramas.py:L516-L527'
  - symbol: add_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L533-L549'
  - symbol: delete_drama_still
    kind: function
    at: 'backend/app/api/dramas.py:L553-L572'
  - symbol: upload_drama_image
    kind: function
    at: 'backend/app/api/dramas.py:L576-L631'
  - symbol: link_drama_accounts
    kind: function
    at: 'backend/app/api/dramas.py:L637-L650'
  - symbol: DramaImportRow
    kind: class
    at: 'backend/app/api/dramas.py:L655-L672'
  - symbol: DramaImportRequest
    kind: class
    at: 'backend/app/api/dramas.py:L675-L677'
  - symbol: DramaImportConfirmItem
    kind: class
    at: 'backend/app/api/dramas.py:L680-L699'
  - symbol: DramaImportConfirm
    kind: class
    at: 'backend/app/api/dramas.py:L702-L705'
  - symbol: _row_key
    kind: function
    at: 'backend/app/api/dramas.py:L708-L710'
  - symbol: _diff_fields
    kind: function
    at: 'backend/app/api/dramas.py:L713-L743'
  - symbol: _split_theater_names
    kind: function
    at: 'backend/app/api/dramas.py:L746-L756'
  - symbol: _resolve_theater_ids
    kind: function
    at: 'backend/app/api/dramas.py:L759-L781'
  - symbol: _resolve_theater_id
    kind: function
    at: 'backend/app/api/dramas.py:L784-L790'
  - symbol: drama_import_preview
    kind: function
    at: 'backend/app/api/dramas.py:L794-L861'
  - symbol: drama_import_parse
    kind: function
    at: 'backend/app/api/dramas.py:L865-L955'
  - symbol: _norm
    kind: function
    at: 'backend/app/api/dramas.py:L901-L902'
  - symbol: _find
    kind: function
    at: 'backend/app/api/dramas.py:L906-L911'
  - symbol: drama_import_confirm
    kind: function
    at: 'backend/app/api/dramas.py:L959-L1115'
  - symbol: FeishuImportRequest
    kind: class
    at: 'backend/app/api/dramas.py:L1120-L1121'
  - symbol: drama_import_feishu
    kind: function
    at: 'backend/app/api/dramas.py:L1125-L1138'
  - symbol: get_drama_publish_context
    kind: function
    at: 'backend/app/api/dramas.py:L1144-L1160'
  - symbol: DramaMaterialLink
    kind: class
    at: 'backend/app/api/dramas.py:L1163-L1166'
  - symbol: link_drama_material
    kind: function
    at: 'backend/app/api/dramas.py:L1170-L1194'
  - symbol: DramaLinkEpisodes
    kind: class
    at: 'backend/app/api/dramas.py:L1199-L1201'
  - symbol: link_drama_episodes
    kind: function
    at: 'backend/app/api/dramas.py:L1205-L1269'
  - symbol: get_drama_slice_status
    kind: function
    at: 'backend/app/api/dramas.py:L1273-L1388'
  - symbol: _stage_status
    kind: function
    at: 'backend/app/api/dramas.py:L1325-L1335'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/api/dramas.py:L1393-L1398'
  - symbol: _parse_dt
    kind: function
    at: 'backend/app/api/dramas.py:L1401-L1406'
---
<!-- context:generated:start -->
## Summary

Drama CRUD with RBAC data-scope filtering (operators see only their own dramas; admins/publishers full access). Three-stage preview/confirm import workflow using drama name as dedup key, returning new/update/unchanged groups with field-level diffs, writing only user-selected items. Generates unique drama codes DR-<8-digit HEX> with collision retry, masks material link passwords in responses, and uses pandas with fuzzy Chinese-header column matching for Excel/CSV import.

## Related

- uses [[minio-storage-upload]] — Manages drama stills in MinIO with presigned URLs and image uploads.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
