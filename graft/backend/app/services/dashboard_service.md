# backend/app/services/dashboard_service.py

- _cache_key · function · L41-L48 — Builds a namespaced Redis cache key that isolates cached aggregates by parameter dimensions, skipping None values.
- _get_cached_agg · function · L51-L62 — Reads a cached aggregate from Redis, returning None on cache miss or Redis failure so the main query path is never blocked.
- _set_cached_agg · function · L65-L78 — Writes an aggregate to Redis with a short TTL plus a long-lived snapshot key so stale data can serve as a fallback during DB failures.
- _get_cached_agg · function · L81-L92 — Duplicate of the cache reader that returns None on cache miss or Redis exception, keeping the main query unaffected by cache failures.
- _get_snapshot_agg · function · L95-L106 — Reads the long-TTL last-success snapshot from Redis to serve as a degraded fallback when DB computation fails.
- _with_cache · function · L109-L131 — Generic cache wrapper that returns cached data on hit, computes and writes on miss, and degrades to short cache then snapshot before raising on DB failure.
- get_overview · function · L134-L145 — Public entry point for overview stats that delegates to the cached compute path with account/date parameters.
- _compute_overview · function · L148-L241 — Aggregates today's and last-7-days ad revenue, total play count, total UV, eCPM, and revenue-per-UV across metric tables, filtered by account and date.
- get_video_ranking · function · L244-L296 — Returns top videos ordered by a validated sort metric (defaulting to play_count), with account filtering and a row limit.
- get_funnel · function · L299-L312 — Public entry point for funnel conversion data that delegates to the cached compute path with account/date parameters.
- _compute_funnel · function · L315-L415 — Builds the play→jump→mini_uv→ad_impression→revenue funnel, preferring the latest stored snapshot and otherwise computing conversion rates from raw metrics.
- get_trend · function · L418-L434 — Public entry point for daily trend series that delegates to the cached compute path with account and date-range parameters.
- _compute_trend · function · L437-L542 — Merges daily video and ad metric aggregates into a unified zero-filled time series covering every date in the requested range.
