---
name: WeChat Download Pipeline
slug: wechat-download-pipeline
type: system
sources:
  - path: backend/wechat_download/__init__.py
    hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - path: backend/wechat_download/api.py
    hash: a8d23790496dd11038e5696b476b61f36be55840694bb08323498b7f4a6d2a29
  - path: backend/wechat_download/base.py
    hash: ff66b408fed1bdad8a8d54e5ad09380adfe29de1bb1595d768c1cfee406b49f6
  - path: backend/wechat_download/downloader.py
    hash: 1edfea92c5f7158d97d20ba1ec3d0e13304307a6e94f2bc3e178413c42c8cfcd
  - path: backend/wechat_download/models.py
    hash: a1d2c9c3a9600871ba856874ecd4acead7da2463d48deceb7106cab5cad4f61d
  - path: backend/wechat_download/preview_client.py
    hash: 38110170ae63dcc71e07560e2a61b95105da264e2cce07649c6b271d85daf657
  - path: backend/wechat_download/provider_registry.py
    hash: 41db648b7f7dabc1a6e1a94fd43475ffc3a8776ce0a01a9af6233b9cd0497864
  - path: backend/wechat_download/service.py
    hash: db0e65aa4f5ef22fb25900e406144e383a78a06f86b76893576d8ded550bdb25
  - path: backend/wechat_download/tasks.py
    hash: 8d65b584fd3b57cb0aa6109d6e62a16eaa4ca6c53a69f160ad72110badb1cb39
  - path: backend/wechat_download/yuanbao_client.py
    hash: a6260bdeb69aa4d8a803d71739b89f4f513f04999bdcd4774bd00a03ac074c15
sources_digest: b19616321b6aafd70bb72f12d5573bccebb972a208250155fd29d7dba6cebbd4
links:
  - to: minio-storage-service
    relation: uses
    description: Uploads downloaded videos to MinIO via minio_service.upload_file_from_path
  - to: slice-engine-orchestration
    relation: produces
    description: >-
      The to-slice endpoint creates a SliceTask with mode=fast and dispatches
      via the existing slice_task Celery task
  - to: video-publishing-pipeline
    relation: uses
    description: >-
      PreviewClient routes through multi_operator service to get a CDP
      connection, same mechanism publish_service uses
generator:
  version: 1
covers:
  - symbol: ImportRequest
    kind: class
    at: 'backend/wechat_download/api.py:L48-L53'
  - symbol: ImportResponse
    kind: class
    at: 'backend/wechat_download/api.py:L56-L61'
  - symbol: wechat_dl_providers
    kind: function
    at: 'backend/wechat_download/api.py:L65-L85'
  - symbol: import_wechat_video
    kind: function
    at: 'backend/wechat_download/api.py:L89-L120'
  - symbol: list_tasks
    kind: function
    at: 'backend/wechat_download/api.py:L124-L157'
  - symbol: task_detail
    kind: function
    at: 'backend/wechat_download/api.py:L161-L166'
  - symbol: ImportToProjectRequest
    kind: class
    at: 'backend/wechat_download/api.py:L173-L181'
  - symbol: ImportToProjectResponse
    kind: class
    at: 'backend/wechat_download/api.py:L184-L187'
  - symbol: import_task_to_project
    kind: function
    at: 'backend/wechat_download/api.py:L191-L253'
  - symbol: BatchImportRequest
    kind: class
    at: 'backend/wechat_download/api.py:L260-L265'
  - symbol: BatchImportResponse
    kind: class
    at: 'backend/wechat_download/api.py:L268-L273'
  - symbol: import_wechat_video_batch
    kind: function
    at: 'backend/wechat_download/api.py:L277-L310'
  - symbol: ToSliceRequest
    kind: class
    at: 'backend/wechat_download/api.py:L318-L324'
  - symbol: ToSliceResponse
    kind: class
    at: 'backend/wechat_download/api.py:L327-L331'
  - symbol: to_slice
    kind: function
    at: 'backend/wechat_download/api.py:L335-L405'
  - symbol: WechatDownloadBase
    kind: class
    at: 'backend/wechat_download/base.py:L13-L16'
  - symbol: DownloadError
    kind: class
    at: 'backend/wechat_download/downloader.py:L26-L27'
  - symbol: WechatDownloader
    kind: class
    at: 'backend/wechat_download/downloader.py:L30-L119'
  - symbol: __init__
    kind: method
    at: 'backend/wechat_download/downloader.py:L33-L35'
  - symbol: download_to_file
    kind: method
    at: 'backend/wechat_download/downloader.py:L37-L47'
  - symbol: _download_direct
    kind: method
    at: 'backend/wechat_download/downloader.py:L49-L81'
  - symbol: _download_hls
    kind: method
    at: 'backend/wechat_download/downloader.py:L83-L119'
  - symbol: get_downloader
    kind: function
    at: 'backend/wechat_download/downloader.py:L125-L129'
  - symbol: WechatDownloadTask
    kind: class
    at: 'backend/wechat_download/models.py:L32-L70'
  - symbol: __repr__
    kind: method
    at: 'backend/wechat_download/models.py:L69-L70'
  - symbol: WechatSourceAuth
    kind: class
    at: 'backend/wechat_download/models.py:L73-L102'
  - symbol: __repr__
    kind: method
    at: 'backend/wechat_download/models.py:L101-L102'
  - symbol: WechatParseRecord
    kind: class
    at: 'backend/wechat_download/models.py:L105-L131'
  - symbol: __repr__
    kind: method
    at: 'backend/wechat_download/models.py:L130-L131'
  - symbol: PreviewClient
    kind: class
    at: 'backend/wechat_download/preview_client.py:L37-L164'
  - symbol: __init__
    kind: method
    at: 'backend/wechat_download/preview_client.py:L40-L43'
  - symbol: _connect
    kind: method
    at: 'backend/wechat_download/preview_client.py:L45-L54'
  - symbol: _pick_account_cdp
    kind: method
    at: 'backend/wechat_download/preview_client.py:L56-L79'
  - symbol: parse
    kind: method
    at: 'backend/wechat_download/preview_client.py:L81-L156'
  - symbol: close
    kind: method
    at: 'backend/wechat_download/preview_client.py:L158-L164'
  - symbol: PreviewUnavailableError
    kind: class
    at: 'backend/wechat_download/preview_client.py:L167-L168'
  - symbol: get_preview_client
    kind: function
    at: 'backend/wechat_download/preview_client.py:L174-L178'
  - symbol: ProviderParseError
    kind: class
    at: 'backend/wechat_download/provider_registry.py:L45-L46'
  - symbol: _root_home
    kind: function
    at: 'backend/wechat_download/provider_registry.py:L68-L75'
  - symbol: ProviderInfo
    kind: class
    at: 'backend/wechat_download/provider_registry.py:L78-L110'
  - symbol: __init__
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L86-L98'
  - symbol: to_dict
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L100-L110'
  - symbol: _fetch_http_balance
    kind: function
    at: 'backend/wechat_download/provider_registry.py:L113-L152'
  - symbol: BaseParseClient
    kind: class
    at: 'backend/wechat_download/provider_registry.py:L155-L168'
  - symbol: parse
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L160-L161'
  - symbol: check_balance
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L163-L165'
  - symbol: close
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L167-L168'
  - symbol: YuanbaoAdapter
    kind: class
    at: 'backend/wechat_download/provider_registry.py:L171-L189'
  - symbol: __init__
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L176-L177'
  - symbol: parse
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L179-L183'
  - symbol: close
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L185-L189'
  - symbol: PreviewAdapter
    kind: class
    at: 'backend/wechat_download/provider_registry.py:L192-L210'
  - symbol: __init__
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L197-L198'
  - symbol: parse
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L200-L204'
  - symbol: close
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L206-L210'
  - symbol: _dig
    kind: function
    at: 'backend/wechat_download/provider_registry.py:L213-L221'
  - symbol: _is_image_url
    kind: function
    at: 'backend/wechat_download/provider_registry.py:L224-L226'
  - symbol: HttpApiAdapter
    kind: class
    at: 'backend/wechat_download/provider_registry.py:L229-L357'
  - symbol: __init__
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L237-L253'
  - symbol: _build_url
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L255-L258'
  - symbol: parse
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L260-L306'
  - symbol: _normalize
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L308-L347'
  - symbol: close
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L349-L353'
  - symbol: check_balance
    kind: method
    at: 'backend/wechat_download/provider_registry.py:L355-L357'
  - symbol: build_providers
    kind: function
    at: 'backend/wechat_download/provider_registry.py:L360-L378'
  - symbol: dispatch_parse
    kind: function
    at: 'backend/wechat_download/provider_registry.py:L381-L399'
  - symbol: get_provider_infos
    kind: function
    at: 'backend/wechat_download/provider_registry.py:L402-L434'
  - symbol: fetch_provider_balances
    kind: function
    at: 'backend/wechat_download/provider_registry.py:L437-L451'
  - symbol: ImportError_
    kind: class
    at: 'backend/wechat_download/service.py:L48-L49'
  - symbol: RetryableImportError
    kind: class
    at: 'backend/wechat_download/service.py:L52-L57'
  - symbol: create_import_task
    kind: function
    at: 'backend/wechat_download/service.py:L64-L86'
  - symbol: get_task
    kind: function
    at: 'backend/wechat_download/service.py:L89-L91'
  - symbol: create_import_tasks_batch
    kind: function
    at: 'backend/wechat_download/service.py:L94-L140'
  - symbol: _serialize_task
    kind: function
    at: 'backend/wechat_download/service.py:L143-L161'
  - symbol: _read_default_download_resolution
    kind: function
    at: 'backend/wechat_download/service.py:L168-L180'
  - symbol: _apply_download_resolution
    kind: function
    at: 'backend/wechat_download/service.py:L183-L226'
  - symbol: run_download_pipeline
    kind: function
    at: 'backend/wechat_download/service.py:L233-L320'
  - symbol: _parse_with_fallback
    kind: function
    at: 'backend/wechat_download/service.py:L323-L377'
  - symbol: _hit_parse_cache
    kind: function
    at: 'backend/wechat_download/service.py:L380-L409'
  - symbol: _set_status
    kind: function
    at: 'backend/wechat_download/service.py:L412-L417'
  - symbol: _fail
    kind: function
    at: 'backend/wechat_download/service.py:L420-L424'
  - symbol: _progress_payload
    kind: function
    at: 'backend/wechat_download/service.py:L431-L438'
  - symbol: _publish_progress
    kind: function
    at: 'backend/wechat_download/service.py:L441-L449'
  - symbol: _temp_path
    kind: function
    at: 'backend/wechat_download/service.py:L452-L455'
  - symbol: _ensure_project
    kind: function
    at: 'backend/wechat_download/service.py:L458-L476'
  - symbol: _create_episode
    kind: function
    at: 'backend/wechat_download/service.py:L479-L494'
  - symbol: task_wechat_dl_download
    kind: function
    at: 'backend/wechat_download/tasks.py:L22-L52'
  - symbol: ParseResult
    kind: class
    at: 'backend/wechat_download/yuanbao_client.py:L27-L38'
  - symbol: YuanbaoParseError
    kind: class
    at: 'backend/wechat_download/yuanbao_client.py:L41-L42'
  - symbol: YuanbaoClient
    kind: class
    at: 'backend/wechat_download/yuanbao_client.py:L45-L124'
  - symbol: __init__
    kind: method
    at: 'backend/wechat_download/yuanbao_client.py:L52-L61'
  - symbol: close
    kind: method
    at: 'backend/wechat_download/yuanbao_client.py:L63-L64'
  - symbol: parse
    kind: method
    at: 'backend/wechat_download/yuanbao_client.py:L66-L95'
  - symbol: _normalize
    kind: method
    at: 'backend/wechat_download/yuanbao_client.py:L97-L124'
  - symbol: get_yuanbao_client
    kind: function
    at: 'backend/wechat_download/yuanbao_client.py:L131-L135'
---
<!-- context:generated:start -->
## Summary

The full WeChat video download subsystem: FastAPI router, ORM models on a standalone WechatDownloadBase (extractable as independent package), downloader with P1-level resumable HTTP Range support and HLS segment concatenation, provider registry with config-driven fallback chain (Yuanbao primary, Preview fallback, extensible HttpApiAdapter), and a Celery task on the wechat_dl queue. Distinguishes retryable failures (RetryableImportError) from permanent ones, preserves temp files on retryable failures for byte-range resume, and publishes progress to Redis for WebSocket delivery. The PreviewClient fallback connects to an already-logged-in WeChat account via Playwright CDP and extracts stream URLs from the finder-preview page DOM.

## Related

- uses [[minio-storage-service]] — Uploads downloaded videos to MinIO via minio_service.upload_file_from_path
- produces [[slice-engine-orchestration]] — The to-slice endpoint creates a SliceTask with mode=fast and dispatches via the existing slice_task Celery task
- uses [[video-publishing-pipeline]] — PreviewClient routes through multi_operator service to get a CDP connection, same mechanism publish_service uses
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
