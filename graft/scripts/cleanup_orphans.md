# scripts/cleanup_orphans.py · [[storage-cleanup-orphan-reclamation]]

Scans and optionally deletes orphaned resources (MinIO raw/sliced objects and media volume files) whose referenced DB records no longer exist, defaulting to a dry-run report.

- human_size · function · L49-L55 — Formats a byte count into a human-readable size string with appropriate units.
- media_path_size · function · L58-L75 — Computes total disk size of a media path, summing file sizes recursively for directories and handling OSError gracefully.
- _collect_valid · function · L78-L102 — Loads all currently-valid DB references (raw/slice source keys, episode ids, media project ids) into sets used to identify orphans.
- _scan_raw · function · L105-L113 — Lists raw-footage bucket objects and flags those whose key is not referenced by any episode or slice_task source_file_key.
- _scan_sliced · function · L116-L128 — Lists sliced bucket objects and flags those under slices/{episode_id}/ where the episode_id no longer exists in the episodes table, leaving non-slices prefixes untouched.
- _scan_media · function · L131-L158 — Scans the media volume for mp4 files, metadata dirs, and asr_cache entries whose uuid prefix is not in the valid autoclip project id set.
- _remove_media · function · L161-L173 — Deletes a media file or directory tree, returning success and logging a specific hint when permission errors indicate the autoclip image needs rebuilding.
- main · function · L176-L246 — Orchestrates the full orphan scan, prints a report of orphans and reclaimable space, then optionally deletes them after interactive or --yes confirmation.
