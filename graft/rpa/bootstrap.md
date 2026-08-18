# rpa/bootstrap.py · [[rpa-multi-operator-infrastructure]]

Bootstrap script that reads multi-operator profiles from Redis and writes them to /app/profiles.json for supervisord startup, falling back to single-instance mode when disabled or empty.

- main · function · L20-L53 — Reads pub:profiles from Redis, validates it as a JSON list, and writes a payload with multi_operator flag plus chrom_profiles and cdp_profiles views to /app/profiles.json.
