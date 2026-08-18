---
name: Data Isolation & Access Control
slug: data-isolation-access-control
type: system
sources:
  - path: backend/app/api/autoclip.py
    hash: 1e998bdded81d944f1c4865f9a07b082e0a4a505a47057342c04e5c06473d98b
  - path: backend/app/api/batch_slice.py
    hash: 078afcff0bc659b47238493410f964aa353dc52bc4cbaba929f41d051c8d808d
  - path: backend/app/api/channel_accounts.py
    hash: 29351d38f2bca7bd80c922a9537cf559a2ade7f33461f8b87c5e3348338a18fa
  - path: backend/app/api/intervals.py
    hash: f5b361075c469e8fbac6e798025abc692c1ace58cdecf6f63d10b9b85b17cd8c
  - path: backend/app/api/preview.py
    hash: 9225738a98138a7b7a7e9cd99c7c25788f739998e5f3b98b5fbe00c39532f9af
  - path: backend/app/api/publications.py
    hash: de3e12a549e9f07bfb1ca1400818b310ea3f0934236bca93e4626e33d61f9de0
  - path: backend/app/api/publish_video_accounts.py
    hash: f2fea0b5088b7c9de7542ef783795e839308ca16872f81fe6b26e8999167500a
sources_digest: 5c0b518a9af110d9dbee60de72aee3112502badd2d925f36c03cfbcd41027c6e
links:
  - to: backend-app-factory-auth
    relation: depends_on
    description: Uses get_current_user and role checks from app.auth.
generator:
  version: 1
covers:
  - symbol: _merge_default_autoclip_config
    kind: function
    at: 'backend/app/api/autoclip.py:L32-L54'
  - symbol: AutoClipRunRequest
    kind: class
    at: 'backend/app/api/autoclip.py:L58-L60'
  - symbol: AutoClipRunResponse
    kind: class
    at: 'backend/app/api/autoclip.py:L63-L66'
  - symbol: AutoClipProgressResponse
    kind: class
    at: 'backend/app/api/autoclip.py:L69-L73'
  - symbol: AutoClipRunResponseItem
    kind: class
    at: 'backend/app/api/autoclip.py:L76-L90'
  - symbol: ClipUpdateRequest
    kind: class
    at: 'backend/app/api/autoclip.py:L93-L96'
  - symbol: ClipResponse
    kind: class
    at: 'backend/app/api/autoclip.py:L99-L116'
  - symbol: _serialize_clip
    kind: function
    at: 'backend/app/api/autoclip.py:L119-L136'
  - symbol: _serialize_autoclip_run
    kind: function
    at: 'backend/app/api/autoclip.py:L139-L153'
  - symbol: run_autoclip
    kind: function
    at: 'backend/app/api/autoclip.py:L157-L275'
  - symbol: get_autoclip_history
    kind: function
    at: 'backend/app/api/autoclip.py:L279-L305'
  - symbol: get_autoclip_progress
    kind: function
    at: 'backend/app/api/autoclip.py:L309-L367'
  - symbol: get_autoclip_clips
    kind: function
    at: 'backend/app/api/autoclip.py:L371-L398'
  - symbol: update_clip
    kind: function
    at: 'backend/app/api/autoclip.py:L402-L440'
  - symbol: regenerate_autoclip
    kind: function
    at: 'backend/app/api/autoclip.py:L444-L484'
  - symbol: BatchEpisodeItem
    kind: class
    at: 'backend/app/api/batch_slice.py:L42-L45'
  - symbol: BatchSliceRunRequest
    kind: class
    at: 'backend/app/api/batch_slice.py:L48-L59'
  - symbol: BatchSliceRunResponse
    kind: class
    at: 'backend/app/api/batch_slice.py:L62-L65'
  - symbol: BatchSliceItemResponse
    kind: class
    at: 'backend/app/api/batch_slice.py:L68-L86'
  - symbol: BatchSliceResponse
    kind: class
    at: 'backend/app/api/batch_slice.py:L89-L104'
  - symbol: BatchSliceOutputItem
    kind: class
    at: 'backend/app/api/batch_slice.py:L107-L114'
  - symbol: BatchSliceOutputResponse
    kind: class
    at: 'backend/app/api/batch_slice.py:L117-L119'
  - symbol: _serialize_batch
    kind: function
    at: 'backend/app/api/batch_slice.py:L127-L142'
  - symbol: _serialize_item
    kind: function
    at: 'backend/app/api/batch_slice.py:L145-L163'
  - symbol: _load_batch_owned
    kind: function
    at: 'backend/app/api/batch_slice.py:L166-L179'
  - symbol: run_batch_slice
    kind: function
    at: 'backend/app/api/batch_slice.py:L188-L240'
  - symbol: list_batch_slices
    kind: function
    at: 'backend/app/api/batch_slice.py:L244-L254'
  - symbol: get_batch_slice
    kind: function
    at: 'backend/app/api/batch_slice.py:L258-L265'
  - symbol: get_batch_items
    kind: function
    at: 'backend/app/api/batch_slice.py:L269-L282'
  - symbol: get_batch_outputs
    kind: function
    at: 'backend/app/api/batch_slice.py:L286-L361'
  - symbol: retry_batch_slice
    kind: function
    at: 'backend/app/api/batch_slice.py:L365-L395'
  - symbol: cancel_batch_slice
    kind: function
    at: 'backend/app/api/batch_slice.py:L399-L420'
  - symbol: OperatorCreate
    kind: class
    at: 'backend/app/api/channel_accounts.py:L38-L41'
  - symbol: OperatorUpdate
    kind: class
    at: 'backend/app/api/channel_accounts.py:L44-L47'
  - symbol: OperatorResponse
    kind: class
    at: 'backend/app/api/channel_accounts.py:L50-L58'
  - symbol: ChannelAccountCreate
    kind: class
    at: 'backend/app/api/channel_accounts.py:L61-L73'
  - symbol: ChannelAccountFromVideoAccount
    kind: class
    at: 'backend/app/api/channel_accounts.py:L76-L88'
  - symbol: ChannelAccountUpdate
    kind: class
    at: 'backend/app/api/channel_accounts.py:L91-L101'
  - symbol: ChannelAccountResponse
    kind: class
    at: 'backend/app/api/channel_accounts.py:L104-L125'
  - symbol: _serialize_operator
    kind: function
    at: 'backend/app/api/channel_accounts.py:L130-L138'
  - symbol: _load_report_metrics
    kind: function
    at: 'backend/app/api/channel_accounts.py:L141-L184'
  - symbol: _serialize_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L187-L210'
  - symbol: _reload_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L213-L221'
  - symbol: _parse_date
    kind: function
    at: 'backend/app/api/channel_accounts.py:L224-L232'
  - symbol: _parse_uuid
    kind: function
    at: 'backend/app/api/channel_accounts.py:L235-L241'
  - symbol: _validate_operator_identity
    kind: function
    at: 'backend/app/api/channel_accounts.py:L244-L250'
  - symbol: list_channel_accounts
    kind: function
    at: 'backend/app/api/channel_accounts.py:L256-L289'
  - symbol: get_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L293-L312'
  - symbol: create_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L316-L361'
  - symbol: create_channel_from_video_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L369-L403'
  - symbol: update_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L407-L445'
  - symbol: delete_channel_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L449-L465'
  - symbol: add_operator
    kind: function
    at: 'backend/app/api/channel_accounts.py:L471-L492'
  - symbol: update_operator
    kind: function
    at: 'backend/app/api/channel_accounts.py:L496-L533'
  - symbol: delete_operator
    kind: function
    at: 'backend/app/api/channel_accounts.py:L537-L560'
  - symbol: _load_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L565-L572'
  - symbol: _load_video_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L575-L583'
  - symbol: _find_or_create_video_account
    kind: function
    at: 'backend/app/api/channel_accounts.py:L586-L630'
  - symbol: _ensure_no_existing
    kind: function
    at: 'backend/app/api/channel_accounts.py:L633-L649'
  - symbol: _check_access
    kind: function
    at: 'backend/app/api/channel_accounts.py:L652-L656'
  - symbol: DetectRequest
    kind: class
    at: 'backend/app/api/intervals.py:L22-L25'
  - symbol: DetectResponse
    kind: class
    at: 'backend/app/api/intervals.py:L28-L30'
  - symbol: DetectProgressResponse
    kind: class
    at: 'backend/app/api/intervals.py:L33-L39'
  - symbol: IntervalCreate
    kind: class
    at: 'backend/app/api/intervals.py:L42-L50'
  - symbol: IntervalUpdate
    kind: class
    at: 'backend/app/api/intervals.py:L53-L60'
  - symbol: IntervalResponse
    kind: class
    at: 'backend/app/api/intervals.py:L63-L76'
  - symbol: IntervalHistoryItem
    kind: class
    at: 'backend/app/api/intervals.py:L79-L91'
  - symbol: _serialize_interval
    kind: function
    at: 'backend/app/api/intervals.py:L94-L107'
  - symbol: detect_intervals
    kind: function
    at: 'backend/app/api/intervals.py:L111-L186'
  - symbol: get_detect_progress
    kind: function
    at: 'backend/app/api/intervals.py:L190-L281'
  - symbol: list_intervals
    kind: function
    at: 'backend/app/api/intervals.py:L285-L310'
  - symbol: get_interval_history
    kind: function
    at: 'backend/app/api/intervals.py:L314-L376'
  - symbol: create_interval
    kind: function
    at: 'backend/app/api/intervals.py:L380-L413'
  - symbol: update_interval
    kind: function
    at: 'backend/app/api/intervals.py:L417-L460'
  - symbol: delete_interval
    kind: function
    at: 'backend/app/api/intervals.py:L464-L490'
  - symbol: toggle_interval
    kind: function
    at: 'backend/app/api/intervals.py:L494-L522'
  - symbol: BatchDownloadRequest
    kind: class
    at: 'backend/app/api/preview.py:L29-L30'
  - symbol: BatchDownloadItem
    kind: class
    at: 'backend/app/api/preview.py:L33-L36'
  - symbol: BatchDownloadResponse
    kind: class
    at: 'backend/app/api/preview.py:L39-L40'
  - symbol: _check_output_scope
    kind: function
    at: 'backend/app/api/preview.py:L43-L56'
  - symbol: preview_frames
    kind: function
    at: 'backend/app/api/preview.py:L60-L111'
  - symbol: preview_video
    kind: function
    at: 'backend/app/api/preview.py:L115-L148'
  - symbol: download_output
    kind: function
    at: 'backend/app/api/preview.py:L152-L201'
  - symbol: _cleanup_tmp
    kind: function
    at: 'backend/app/api/preview.py:L204-L209'
  - symbol: batch_download
    kind: function
    at: 'backend/app/api/preview.py:L213-L270'
  - symbol: PublicationCreate
    kind: class
    at: 'backend/app/api/publications.py:L19-L25'
  - symbol: PublicationUpdate
    kind: class
    at: 'backend/app/api/publications.py:L28-L34'
  - symbol: PublicationResponse
    kind: class
    at: 'backend/app/api/publications.py:L37-L48'
  - symbol: _serialize_publication
    kind: function
    at: 'backend/app/api/publications.py:L51-L62'
  - symbol: _check_output_scope
    kind: function
    at: 'backend/app/api/publications.py:L65-L78'
  - symbol: list_publications
    kind: function
    at: 'backend/app/api/publications.py:L82-L108'
  - symbol: create_publication
    kind: function
    at: 'backend/app/api/publications.py:L112-L153'
  - symbol: update_publication
    kind: function
    at: 'backend/app/api/publications.py:L157-L207'
  - symbol: VideoAccountCreate
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L22-L34'
  - symbol: VideoAccountUpdate
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L37-L48'
  - symbol: VideoAccountResponse
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L51-L68'
  - symbol: VideoAccountBatchImport
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L71-L74'
  - symbol: _serialize_video_account
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L77-L94'
  - symbol: list_video_accounts
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L98-L121'
  - symbol: create_video_account
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L125-L149'
  - symbol: batch_import_video_accounts
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L153-L196'
  - symbol: VideoAccountBatchAssignProfile
    kind: class
    at: 'backend/app/api/publish_video_accounts.py:L199-L202'
  - symbol: batch_assign_video_account_profile
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L206-L238'
  - symbol: update_video_account
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L242-L271'
  - symbol: delete_video_account
    kind: function
    at: 'backend/app/api/publish_video_accounts.py:L275-L297'
---
<!-- context:generated:start -->
## Summary

Cross-cutting data-scope enforcement traversing from outputs/tasks/episodes up to projects and verifying the current user's project-level permissions. check_project_access_by_episode and check_project_access_by_id are used across slice, preview, publications, autoclip, intervals, and batch_slice routers. user_can_access_all_materials gates material-level RBAC in channel_accounts and video_accounts.

## Related

- depends on [[backend-app-factory-auth]] — Uses get_current_user and role checks from app.auth.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
