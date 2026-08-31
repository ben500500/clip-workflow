# backend/app/api/maintenance.py · [[maintenance-monitoring]]

- ArchiveRequest · class · L25-L26 — Request model carrying an optional archive age threshold in days.
- CleanupRequest · class · L29-L30 — Request model specifying max age in hours for temp file cleanup, defaulting to 24.
- MaintenanceStatusResponse · class · L33-L36 — Response model aggregating current archive, MinIO lifecycle, and temp cleanup configuration values.
- run_archive · function · L40-L48 — Admin endpoint that triggers archiving of dashboard metrics older than the requested days, translating failures into a 500 response.
- run_cleanup · function · L52-L60 — Admin endpoint that triggers deletion of stale local temp files older than the given hours, translating failures into a 500 response.
- run_minio_lifecycle · function · L64-L71 — Admin endpoint that applies the MinIO lifecycle policy to transition unaccessed objects to low-frequency storage, translating failures into a 500 response.
- maintenance_status · function · L75-L85 — Admin endpoint that reports current maintenance configuration values from settings.
