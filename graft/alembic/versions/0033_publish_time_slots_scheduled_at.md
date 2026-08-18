# alembic/versions/0033_publish_time_slots_scheduled_at.py · [[alembic-migration-chain]]

- upgrade · function · L28-L50 — def upgrade() -> None: # publish_tasks：定时预约字段（可空，保持立即发布兼容）
- _insert_slot · function · L53-L70 — def _insert_slot(name: str, start: str, end: str, preset: bool) -> None
- downgrade · function · L73-L78 — def downgrade() -> None
