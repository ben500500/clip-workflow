# alembic/versions/0014_seedance_generate.py · [[alembic-migration-chain]]

Alembic migration adding Seedance official API direct-generate task fields and a gen_channel source-tracking column to shortdrama_prompts, enabling a parallel video-generation channel that still writes results back to existing video_* fields.

- upgrade · function · L26-L50 — Adds six nullable columns (seedance_status/task_id/message/error_message/resolution and gen_channel) to shortdrama_prompts to support the Seedance direct-generate channel.
- downgrade · function · L53-L59 — Rolls back the migration by dropping the six added columns in reverse order.
