---
name: Provider Fallback Chain
slug: provider-fallback-chain
type: concept
sources:
  - path: backend/wechat_download/preview_client.py
    hash: 38110170ae63dcc71e07560e2a61b95105da264e2cce07649c6b271d85daf657
  - path: backend/wechat_download/provider_registry.py
    hash: 41db648b7f7dabc1a6e1a94fd43475ffc3a8776ce0a01a9af6233b9cd0497864
  - path: backend/wechat_download/yuanbao_client.py
    hash: a6260bdeb69aa4d8a803d71739b89f4f513f04999bdcd4774bd00a03ac074c15
sources_digest: a2f814047bb1363c07ea91430872c3aa05abe68dfc6d0d1b40e96eb327f71961
links:
  - to: wechat-download-pipeline
    relation: part_of
    description: The fallback chain is the parsing layer of the download pipeline
  - to: wechat-download-pipeline
    relation: uses
    description: service.py invokes build_providers and dispatch_parse
generator:
  version: 1
covers:
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

Config-driven, ordered fallback chain for WeChat URL parsing. WECHAT_DL_PROVIDERS env var builds an ordered provider list (default 'yuanbao,preview'), each conforming to BaseParseClient; dispatch_parse returns the first successful ParseResult or aggregates errors. HttpApiAdapter is the extensibility point supporting configurable HTTP methods, auth schemes (query/bearer/header), and response field mappings via WECHAT_DL_<NAME>_* env vars. dispatch_parse is kept pure (no DB writes) for testability.

## Related

- part of [[wechat-download-pipeline]] — The fallback chain is the parsing layer of the download pipeline
- uses [[wechat-download-pipeline]] — service.py invokes build_providers and dispatch_parse
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
