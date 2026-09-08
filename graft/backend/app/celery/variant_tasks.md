# backend/app/celery/variant_tasks.py · [[celery-task-layer]]

- generate_variants_task · function · L21-L67 — def generate_variants_task( self, output_id: str, count: int = 1, base_dedupe: dict = None, created_by: str = None, thresholds: dict = None, lock_token: str = None, )
- verify_variant_fingerprint_task · function · L71-L73 — def verify_variant_fingerprint_task(self, variant_id: str, thresholds: dict = None)
