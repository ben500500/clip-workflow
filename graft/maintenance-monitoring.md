---
name: Maintenance & Monitoring
slug: maintenance-monitoring
type: system
sources:
  - path: backend/app/api/maintenance.py
    hash: a8a4503cdc6272c01c6a0c1daffaed16d3488fee039b414730f3b30f1978ef1f
  - path: backend/app/api/monitor.py
    hash: cdacff9500e7c719e91d9b1b44a22a368178b9a38acc2e838c4c1f1000b8d7e3
sources_digest: d6d5d0ce34f77108efe78cc695714872d19386a527d9a8fab47cef046e05b159
links:
  - to: backend-app-factory-auth
    relation: uses
    description: All endpoints require admin role via require_roles from app.auth.
generator:
  version: 1
covers:
  - symbol: ArchiveRequest
    kind: class
    at: 'backend/app/api/maintenance.py:L25-L26'
  - symbol: CleanupRequest
    kind: class
    at: 'backend/app/api/maintenance.py:L29-L30'
  - symbol: MaintenanceStatusResponse
    kind: class
    at: 'backend/app/api/maintenance.py:L33-L36'
  - symbol: run_archive
    kind: function
    at: 'backend/app/api/maintenance.py:L40-L48'
  - symbol: run_cleanup
    kind: function
    at: 'backend/app/api/maintenance.py:L52-L60'
  - symbol: run_minio_lifecycle
    kind: function
    at: 'backend/app/api/maintenance.py:L64-L71'
  - symbol: maintenance_status
    kind: function
    at: 'backend/app/api/maintenance.py:L75-L85'
  - symbol: AlertRuleCreate
    kind: class
    at: 'backend/app/api/monitor.py:L38-L46'
  - symbol: AlertRuleUpdate
    kind: class
    at: 'backend/app/api/monitor.py:L49-L57'
  - symbol: AlertRuleResponse
    kind: class
    at: 'backend/app/api/monitor.py:L60-L73'
  - symbol: AlertEventResponse
    kind: class
    at: 'backend/app/api/monitor.py:L76-L89'
  - symbol: AlertCheckResponse
    kind: class
    at: 'backend/app/api/monitor.py:L92-L96'
  - symbol: _serialize_rule
    kind: function
    at: 'backend/app/api/monitor.py:L99-L112'
  - symbol: _serialize_event
    kind: function
    at: 'backend/app/api/monitor.py:L115-L128'
  - symbol: health_check
    kind: function
    at: 'backend/app/api/monitor.py:L137-L139'
  - symbol: get_monitor_metrics
    kind: function
    at: 'backend/app/api/monitor.py:L143-L145'
  - symbol: trigger_alert_check
    kind: function
    at: 'backend/app/api/monitor.py:L149-L153'
  - symbol: list_alert_rules
    kind: function
    at: 'backend/app/api/monitor.py:L157-L164'
  - symbol: get_alert_rule_meta
    kind: function
    at: 'backend/app/api/monitor.py:L168-L170'
  - symbol: create_alert_rule
    kind: function
    at: 'backend/app/api/monitor.py:L174-L184'
  - symbol: update_alert_rule
    kind: function
    at: 'backend/app/api/monitor.py:L188-L210'
  - symbol: delete_alert_rule
    kind: function
    at: 'backend/app/api/monitor.py:L214-L232'
  - symbol: list_alert_events
    kind: function
    at: 'backend/app/api/monitor.py:L236-L249'
---
<!-- context:generated:start -->
## Summary

Third-phase operational features: maintenance endpoints for archiving dashboard metrics older than 90 days, cleaning stale temp files (24h threshold), configuring MinIO lifecycle policies, and status reporting. Monitoring endpoints for health checks, metric collection, alert rule CRUD, alert event listing, and manual alert triggering, with a 200-event query limit and admin-only alert management. Health check is publicly accessible.

## Related

- uses [[backend-app-factory-auth]] — All endpoints require admin role via require_roles from app.auth.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
