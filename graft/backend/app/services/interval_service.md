# backend/app/services/interval_service.py

Service module that runs an external detection engine subprocess to identify intervals (credits, static, watermark, custom) in a video file and returns them as structured data.

- detect_intervals · function · L13-L99 — Runs the detection engine as a subprocess with a timeout, validates its output, and parses the resulting intervals from JSON into a list.
