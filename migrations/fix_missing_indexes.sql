-- ============================================================================
-- 存量库补索引脚本
--
-- 背景：init.sql 第 273 行 `CREATE INDEX idx_users_email ON users(email)` 引用了
-- users 表中不存在的 email 字段，导致 postgres entrypoint 以 ON_ERROR_STOP=1
-- 执行时整文件中止，后续 27 条业务索引全部未创建，同时 alembic 的 || echo
-- 又静默吞掉了失败。结果：生产库业务索引 0/27，看板退化为全表扫描 + 30s 超时。
--
-- 本脚本用于对「已受影响的存量库」在线补建全部缺失索引。
-- 使用 CREATE INDEX CONCURRENTLY 不加锁；全部 IF NOT EXISTS 幂等，可重复执行。
--
-- 注意：CONCURRENTLY 不能在事务块内执行，请以 `psql -f` 直接运行，勿包在 BEGIN 里。
-- ============================================================================

-- ==================== users 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_is_active ON users(is_active);

-- ==================== user_sessions 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);

-- ==================== user_oauth_accounts 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_oauth_user_id ON user_oauth_accounts(user_id);

-- ==================== project_members 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_project_members_project_id ON project_members(project_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_project_members_user_id ON project_members(user_id);

-- ==================== media_assets 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_media_assets_user_id ON media_assets(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_media_assets_project_id ON media_assets(project_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_media_assets_media_type ON media_assets(media_type);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_media_assets_status ON media_assets(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_media_assets_created_at ON media_assets(created_at);

-- ==================== clip_tasks 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_clip_tasks_user_id ON clip_tasks(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_clip_tasks_project_id ON clip_tasks(project_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_clip_tasks_status ON clip_tasks(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_clip_tasks_created_at ON clip_tasks(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_clip_tasks_priority ON clip_tasks(priority);

-- ==================== autoclip 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_autoclip_configs_user_id ON autoclip_configs(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_autoclip_history_user_id ON autoclip_history(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_autoclip_history_status ON autoclip_history(status);

-- ==================== celery_tasks 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_celery_tasks_status ON celery_tasks(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_celery_tasks_created_at ON celery_tasks(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_celery_tasks_name ON celery_tasks(name);

-- ==================== notifications 索引 ====================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_notifications_created_at ON notifications(created_at);

-- ============ 补充：models.py 中新增显式 index=True 的外键索引 ============
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_episodes_project_id ON episodes(project_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_clip_candidates_episode_id ON clip_candidates(episode_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_detected_intervals_episode_id ON detected_intervals(episode_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_slice_tasks_episode_id ON slice_tasks(episode_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_slice_outputs_task_id ON slice_outputs(task_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_slice_outputs_clip_id ON slice_outputs(clip_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_publications_output_id ON publications(output_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_publish_tasks_output_id ON publish_tasks(output_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_video_metrics_publish_task_id ON video_metrics(publish_task_id);
