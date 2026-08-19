-- =============================================================================
-- Clip Workflow - 数据库初始化脚本
-- 在 PostgreSQL 首次启动时自动执行
--
-- 注意：projects / episodes / slice_tasks / publish_tasks / video_metrics 等
-- 业务表由后端 SQLAlchemy（Base.metadata.create_all）负责创建，本脚本只负责
-- 预置未来认证/协作/素材等扩展表，避免两套 schema 互相冲突。
-- =============================================================================

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==================== 用户与认证 ====================

-- 用户表（结构与 backend ORM User 模型保持一致）
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    role VARCHAR(20) NOT NULL DEFAULT 'operator' CHECK (role IN ('admin', 'operator', 'publisher', 'material')),
    -- 数据可见范围：all=全部素材，own=仅自己创建（数据隔离，二期方案）
    data_scope VARCHAR(20) NOT NULL DEFAULT 'own' CHECK (data_scope IN ('all', 'own')),
    -- 提示词生成默认时长（秒）：用户选择时长后即作为当前登录用户的默认值（10/15/20/25/30 或自定义）
    prompt_default_duration INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 用户会话表
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token VARCHAR(512) NOT NULL UNIQUE,
    access_token VARCHAR(512),
    user_agent VARCHAR(512),
    ip_address VARCHAR(45),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMP WITH TIME ZONE
);

-- 用户 OAuth 关联表
CREATE TABLE IF NOT EXISTS user_oauth_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL,
    provider_username VARCHAR(255),
    provider_email VARCHAR(255),
    access_token TEXT,
    refresh_token TEXT,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(provider, provider_user_id)
);

-- ==================== 项目与工作流 ====================

-- 项目协作成员表（projects 表由 ORM 创建，此处不建外键）
CREATE TABLE IF NOT EXISTS project_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL DEFAULT 'editor' CHECK (role IN ('owner', 'editor', 'viewer')),
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, user_id)
);

-- 工作流模板表
CREATE TABLE IF NOT EXISTS workflow_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(64),
    config JSONB NOT NULL DEFAULT '{}',
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    usage_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== 素材管理 ====================

-- 素材表（视频、音频、图片等；project_id 由 ORM 的 projects 管理，此处不建外键）
CREATE TABLE IF NOT EXISTS media_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID,
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(128) NOT NULL,
    media_type VARCHAR(32) NOT NULL CHECK (media_type IN ('video', 'audio', 'image', 'subtitle', 'other')),
    storage_type VARCHAR(16) NOT NULL DEFAULT 'minio' CHECK (storage_type IN ('local', 'minio')),
    storage_path VARCHAR(512) NOT NULL,
    thumbnail_url VARCHAR(512),
    duration DOUBLE PRECISION,
    width INTEGER,
    height INTEGER,
    fps DOUBLE PRECISION,
    bitrate BIGINT,
    codec VARCHAR(64),
    file_hash VARCHAR(64),
    metadata JSONB DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded' CHECK (status IN ('uploading', 'uploaded', 'processing', 'processed', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 素材标签表
CREATE TABLE IF NOT EXISTS media_tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(64) NOT NULL UNIQUE,
    color VARCHAR(7),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 素材-标签关联表
CREATE TABLE IF NOT EXISTS media_asset_tags (
    asset_id UUID NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES media_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (asset_id, tag_id)
);

-- ==================== 剪辑任务 ====================

-- 剪辑任务表（project_id 由 ORM 管理，此处不建外键）
CREATE TABLE IF NOT EXISTS clip_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    source_media_id UUID REFERENCES media_assets(id) ON DELETE SET NULL,
    config JSONB NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'queued', 'processing', 'completed', 'failed', 'cancelled')),
    progress DOUBLE PRECISION DEFAULT 0,
    error_message TEXT,
    output_media_id UUID REFERENCES media_assets(id) ON DELETE SET NULL,
    result JSONB DEFAULT '{}',
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== AutoClip 配置 ====================

-- AutoClip 剪辑配置表
CREATE TABLE IF NOT EXISTS autoclip_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    prompt_template TEXT,
    ai_model VARCHAR(128) DEFAULT 'qwen-vl-max',
    parameters JSONB DEFAULT '{}',
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- AutoClip 剪辑历史记录表
CREATE TABLE IF NOT EXISTS autoclip_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    config_id UUID REFERENCES autoclip_configs(id) ON DELETE SET NULL,
    task_id UUID REFERENCES clip_tasks(id) ON DELETE SET NULL,
    source_media_id UUID REFERENCES media_assets(id) ON DELETE SET NULL,
    output_media_id UUID REFERENCES media_assets(id) ON DELETE SET NULL,
    prompt TEXT,
    ai_model VARCHAR(128),
    parameters JSONB DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    result JSONB DEFAULT '{}',
    error_message TEXT,
    processing_time DOUBLE PRECISION,
    token_usage JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== Celery 任务管理 ====================

-- Celery 任务记录表
CREATE TABLE IF NOT EXISTS celery_tasks (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255),
    task_type VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'received', 'started', 'retrying', 'success', 'failure', 'revoked')),
    args JSONB,
    kwargs JSONB,
    result JSONB,
    traceback TEXT,
    worker VARCHAR(255),
    queue VARCHAR(128),
    retries INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    eta TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    received_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    succeeded_at TIMESTAMP WITH TIME ZONE,
    failed_at TIMESTAMP WITH TIME ZONE,
    runtime DOUBLE PRECISION,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Celery 定时任务调度表
CREATE TABLE IF NOT EXISTS celery_periodic_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    task VARCHAR(255) NOT NULL,
    args JSONB DEFAULT '[]',
    kwargs JSONB DEFAULT '{}',
    queue VARCHAR(128),
    exchange VARCHAR(128),
    routing_key VARCHAR(128),
    expires_at TIMESTAMP WITH TIME ZONE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMP WITH TIME ZONE,
    total_run_count INTEGER NOT NULL DEFAULT 0,
    date_changed TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    description TEXT,
    crontab_minute VARCHAR(64) DEFAULT '*',
    crontab_hour VARCHAR(64) DEFAULT '*',
    crontab_day_of_month VARCHAR(64) DEFAULT '*',
    crontab_month_of_year VARCHAR(64) DEFAULT '*',
    crontab_day_of_week VARCHAR(64) DEFAULT '*',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== 系统通知 ====================

-- 通知表
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT,
    data JSONB DEFAULT '{}',
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    read_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== 系统配置（扩展表，ORM 使用 system_config 单数表） ====================

-- 系统配置表
CREATE TABLE IF NOT EXISTS system_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT NOT NULL,
    description TEXT,
    category VARCHAR(64) DEFAULT 'general',
    is_encrypted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== 索引 ====================

-- users 索引（注意：users 表无 email 字段，已删除原本会导致全文件索引创建中止的错误语句）
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- user_sessions 索引
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);

-- user_oauth_accounts 索引
CREATE INDEX IF NOT EXISTS idx_user_oauth_user_id ON user_oauth_accounts(user_id);

-- project_members 索引
CREATE INDEX IF NOT EXISTS idx_project_members_project_id ON project_members(project_id);
CREATE INDEX IF NOT EXISTS idx_project_members_user_id ON project_members(user_id);

-- media_assets 索引
CREATE INDEX IF NOT EXISTS idx_media_assets_user_id ON media_assets(user_id);
CREATE INDEX IF NOT EXISTS idx_media_assets_project_id ON media_assets(project_id);
CREATE INDEX IF NOT EXISTS idx_media_assets_media_type ON media_assets(media_type);
CREATE INDEX IF NOT EXISTS idx_media_assets_status ON media_assets(status);
CREATE INDEX IF NOT EXISTS idx_media_assets_created_at ON media_assets(created_at);

-- clip_tasks 索引
CREATE INDEX IF NOT EXISTS idx_clip_tasks_user_id ON clip_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_clip_tasks_project_id ON clip_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_clip_tasks_status ON clip_tasks(status);
CREATE INDEX IF NOT EXISTS idx_clip_tasks_created_at ON clip_tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_clip_tasks_priority ON clip_tasks(priority);

-- autoclip 索引
CREATE INDEX IF NOT EXISTS idx_autoclip_configs_user_id ON autoclip_configs(user_id);
CREATE INDEX IF NOT EXISTS idx_autoclip_history_user_id ON autoclip_history(user_id);
CREATE INDEX IF NOT EXISTS idx_autoclip_history_status ON autoclip_history(status);

-- celery_tasks 索引
CREATE INDEX IF NOT EXISTS idx_celery_tasks_status ON celery_tasks(status);
CREATE INDEX IF NOT EXISTS idx_celery_tasks_created_at ON celery_tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_celery_tasks_name ON celery_tasks(name);

-- notifications 索引
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at);

-- =============================================================================
-- P1 防御：空闲事务超时自动回滚（Issue #219）
-- 根因：autoclip 某接口在事务内 SELECT 后未 commit/rollback 就把连接归还连接池，
--       连接以 idle in transaction 悬挂并持有 autoclip_runs 表级 RowExclusiveLock，
--       挡死 worker-selection 的 UPDATE，导致选点卡「排队中」。
-- 该设置把悬挂事务最迟 60s 交由 PG 自动回滚，作为代码修复的防御层。
-- 目录级 ALTER ROLE 基于 pg_authid（角色级设置，覆盖该角色所有连接/所有库），
-- 不写 postgresql.auto.conf，不受 163 生产库缺 include 缺陷影响，容器重建后保留；
-- 新连接即时生效，无需 pg_reload_conf()。
-- =============================================================================
ALTER ROLE clipworkflow SET idle_in_transaction_session_timeout = '60s';
