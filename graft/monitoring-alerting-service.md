---
name: Monitoring & Alerting Service
slug: monitoring-alerting-service
type: system
sources:
  - path: backend/app/services/monitor_service.py
    hash: 5b93bf9ee7d0f68bd4f57bade88c9993c1dfc1d7feb29daa2eb7c3b9a4762194
sources_digest: d1cd03268e20ed0a684eb964bcc920b1ac6e1c0679d3bfc3c8396d0c2c99f01c
links:
  - to: object-storage-service-minio
    relation: uses
    description: Integrates with MinIO for storage health checks
  - to: redis-stream-service
    relation: uses
    description: Reuses the Redis connection pool from app.services.redis_stream
generator:
  version: 1
covers:
  - symbol: ensure_default_alert_rules
    kind: function
    at: 'backend/app/services/monitor_service.py:L66-L76'
  - symbol: _get_redis
    kind: function
    at: 'backend/app/services/monitor_service.py:L84-L87'
  - symbol: collect_metrics
    kind: function
    at: 'backend/app/services/monitor_service.py:L90-L157'
  - symbol: send_dingtalk_alert
    kind: function
    at: 'backend/app/services/monitor_service.py:L165-L188'
  - symbol: _evaluate
    kind: function
    at: 'backend/app/services/monitor_service.py:L196-L210'
  - symbol: _format_metric_value
    kind: function
    at: 'backend/app/services/monitor_service.py:L213-L221'
  - symbol: run_alert_checks
    kind: function
    at: 'backend/app/services/monitor_service.py:L224-L284'
  - symbol: check_health
    kind: function
    at: 'backend/app/services/monitor_service.py:L292-L343'
---
<!-- context:generated:start -->
## Summary

Health checks, metric collection, and DingTalk webhook alerting. Defines seven alert metrics with default rules seeded idempotently, persists triggered events, and evaluates rules against DB/Redis/disk metrics. Skips cookie_expiring alerts when no data exists and uses rule-level webhook URLs with a global settings fallback.

## Related

- uses [[object-storage-service-minio]] — Integrates with MinIO for storage health checks
- uses [[redis-stream-service]] — Reuses the Redis connection pool from app.services.redis_stream
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
