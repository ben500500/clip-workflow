---
name: WeChat Download & Drama Management
slug: wechat-download-drama-management
type: system
sources:
  - path: alembic/versions/0029_wechat_download.py
    hash: 92910560c9faeec28d8974f535a4ada3516bbd8c929bc79872d3b03d05bfe045
  - path: alembic/versions/0036_drama_management.py
    hash: 87e0349c1793c8ac26ee643ae6d520cfafbbeb57c7de121412e71c8ea4925bb0
sources_digest: 382123fc8173abcc48867b5fcbce82afebc47c365552b3f678b0f2fc10b08c00
links:
  - to: alembic-migration-chain
    relation: part_of
    description: Both feature areas are implemented as additive migrations in the chain.
generator:
  version: 1
covers:
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0029_wechat_download.py:L31-L92'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0029_wechat_download.py:L95-L104'
  - symbol: upgrade
    kind: function
    at: 'alembic/versions/0036_drama_management.py:L32-L104'
  - symbol: downgrade
    kind: function
    at: 'alembic/versions/0036_drama_management.py:L107-L111'
---
<!-- context:generated:start -->
## Summary

Two feature areas: (1) WeChat video download (Issue #150) with wechat_download_tasks, wechat_source_auths (enforcing the hard requirement that unauthorized sources are blocked), wechat_parse_records, and a minimal source_url column on episodes kept as lightweight coupling. (2) Drama management (Issue #130) with dramas (unique DR-8HEX code), drama_stills, drama_accounts many-to-many, and drama_materials linking to publish_materials with SET NULL.

## Related

- part of [[alembic-migration-chain]] — Both feature areas are implemented as additive migrations in the chain.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
