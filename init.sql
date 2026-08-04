-- =============================================================================
-- Clip Workflow - 数据库初始化脚本
-- 在 PostgreSQL 首次启动时自动执行
-- =============================================================================

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==================== 用户与认证 ====================

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    display_name VARCHAR(128),
    avatar_url VARCHAR(512),
    bio TEXT,
    role VARCHAR(32) NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin', 'superadmin')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at TIMESTAMP WITH TIME ZONE,
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

-- 项目表
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    cover_url VARCHAR(512),
    status VARCHAR(32) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'processing', 'completed', 'archived')),
    visibility VARCHAR(16) NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'public', 'shared')),
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 项目协作成员表
CREATE TABLE IF NOT EXISTS project_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
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

-- 素材表（视频、音频、图片等）
CREATE TABLE IF NOT EXISTS media_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
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

-- 剪辑任务表
CREATE TABLE IF NOT EXISTS clip_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
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

-- ==================== 系统配置 ====================

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

-- users 索引
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- user_sessions 索引
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);

-- user_oauth_accounts 索引
CREATE INDEX IF NOT EXISTS idx_user_oauth_user_id ON user_oauth_accounts(user_id);

-- projects 索引
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at);

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

-- ==================== V2 版本新增表 ====================

-- 项目版本历史表
CREATE TABLE IF NOT EXISTS project_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    snapshot JSONB NOT NULL,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- AI 生成记录表
CREATE TABLE IF NOT EXISTS ai_generations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_type VARCHAR(64) NOT NULL,
    prompt TEXT,
    result JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== V2: 发布管理 ====================

-- 发布任务表
CREATE TABLE IF NOT EXISTS publish_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    output_id UUID,
    platform VARCHAR(50) NOT NULL CHECK (platform IN ('wechat_channels', 'douyin', 'kuaishou')),
    account_name VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'uploading', 'processing', 'pending_confirm', 'published', 'failed')),
    celery_task_id VARCHAR(100),
    title VARCHAR(500),
    description TEXT,
    tags JSONB DEFAULT '[]',
    cover_file_key VARCHAR(500),
    mini_program_link VARCHAR(500),
    link_attached BOOLEAN NOT NULL DEFAULT FALSE,
    published_url VARCHAR(500),
    published_id VARCHAR(200),
    published_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    require_manual_confirm BOOLEAN NOT NULL DEFAULT TRUE,
    screenshot_key VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 发布配置表
CREATE TABLE IF NOT EXISTS publish_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform VARCHAR(50) NOT NULL CHECK (platform IN ('wechat_channels', 'douyin', 'kuaishou')),
    account_name VARCHAR(100) NOT NULL,
    chrome_debug_port INTEGER NOT NULL DEFAULT 9222,
    cookie_file VARCHAR(500),
    title_template VARCHAR(500) DEFAULT '{clip_title}',
    description_template TEXT DEFAULT '',
    default_tags JSONB DEFAULT '[]',
    mini_program_link VARCHAR(500),
    publish_mode VARCHAR(50) NOT NULL DEFAULT 'immediate' CHECK (publish_mode IN ('immediate', 'scheduled')),
    require_manual_confirm BOOLEAN NOT NULL DEFAULT TRUE,
    min_interval_seconds INTEGER NOT NULL DEFAULT 300,
    max_daily_publish INTEGER NOT NULL DEFAULT 20,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== V2: IAA 数据看板 ====================

-- 视频数据指标表
CREATE TABLE IF NOT EXISTS video_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    publish_task_id UUID REFERENCES publish_tasks(id) ON DELETE SET NULL,
    video_id VARCHAR(200),
    title VARCHAR(500),
    publish_date DATE,
    account_id UUID,
    play_count INTEGER NOT NULL DEFAULT 0,
    finish_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    like_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    share_count INTEGER NOT NULL DEFAULT 0,
    favorite_count INTEGER NOT NULL DEFAULT 0,
    social_recommend_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
    social_recommend_play INTEGER NOT NULL DEFAULT 0,
    friend_recommend_play INTEGER NOT NULL DEFAULT 0,
    jump_click_count INTEGER NOT NULL DEFAULT 0,
    jump_click_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    attributed_uv INTEGER NOT NULL DEFAULT 0,
    attributed_revenue DOUBLE PRECISION NOT NULL DEFAULT 0,
    content_type VARCHAR(50),
    drama_id UUID,
    traffic_method VARCHAR(50),
    publish_time_slot VARCHAR(10),
    play_level VARCHAR(10),
    production_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 小程序数据指标表
CREATE TABLE IF NOT EXISTS mini_program_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL,
    account_id UUID,
    uv INTEGER NOT NULL DEFAULT 0,
    new_user_count INTEGER NOT NULL DEFAULT 0,
    drama_play_count INTEGER NOT NULL DEFAULT 0,
    avg_play_duration DOUBLE PRECISION NOT NULL DEFAULT 0,
    drama_finish_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 广告数据指标表
CREATE TABLE IF NOT EXISTS ad_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL,
    account_id UUID,
    impression_count INTEGER NOT NULL DEFAULT 0,
    click_count INTEGER NOT NULL DEFAULT 0,
    ctr DOUBLE PRECISION NOT NULL DEFAULT 0,
    ecpm DOUBLE PRECISION NOT NULL DEFAULT 0,
    revenue DOUBLE PRECISION NOT NULL DEFAULT 0,
    reward_video_impression INTEGER NOT NULL DEFAULT 0,
    reward_video_revenue DOUBLE PRECISION NOT NULL DEFAULT 0,
    interstitial_impression INTEGER NOT NULL DEFAULT 0,
    interstitial_revenue DOUBLE PRECISION NOT NULL DEFAULT 0,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 短剧维度数据表
CREATE TABLE IF NOT EXISTS drama_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL,
    drama_id UUID,
    account_id UUID,
    uv INTEGER NOT NULL DEFAULT 0,
    play_count INTEGER NOT NULL DEFAULT 0,
    finish_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    ad_impression INTEGER NOT NULL DEFAULT 0,
    ad_revenue DOUBLE PRECISION NOT NULL DEFAULT 0,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 漏斗快照表
CREATE TABLE IF NOT EXISTS funnel_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL,
    account_id UUID,
    total_play INTEGER NOT NULL DEFAULT 0,
    jump_click INTEGER NOT NULL DEFAULT 0,
    jump_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    mini_program_uv INTEGER NOT NULL DEFAULT 0,
    drama_play_uv INTEGER NOT NULL DEFAULT 0,
    play_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    ad_exposure_uv INTEGER NOT NULL DEFAULT 0,
    exposure_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    revenue DOUBLE PRECISION NOT NULL DEFAULT 0,
    revenue_per_1000_play DOUBLE PRECISION NOT NULL DEFAULT 0,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 生态数据表
CREATE TABLE IF NOT EXISTS ecosystem_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL,
    account_id UUID,
    article_count INTEGER NOT NULL DEFAULT 0,
    article_read_count INTEGER NOT NULL DEFAULT 0,
    mini_program_uv_from_article INTEGER NOT NULL DEFAULT 0,
    wecom_new_friends INTEGER NOT NULL DEFAULT 0,
    wecom_total_friends INTEGER NOT NULL DEFAULT 0,
    wecom_source VARCHAR(50),
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ==================== V2: 索引 ====================

CREATE INDEX IF NOT EXISTS idx_publish_tasks_platform ON publish_tasks(platform);
CREATE INDEX IF NOT EXISTS idx_publish_tasks_status ON publish_tasks(status);
CREATE INDEX IF NOT EXISTS idx_publish_tasks_output_id ON publish_tasks(output_id);
CREATE INDEX IF NOT EXISTS idx_video_metrics_date ON video_metrics(publish_date);
CREATE INDEX IF NOT EXISTS idx_video_metrics_account ON video_metrics(account_id);
CREATE INDEX IF NOT EXISTS idx_video_metrics_drama ON video_metrics(drama_id);
CREATE INDEX IF NOT EXISTS idx_mini_metrics_date ON mini_program_metrics(date);
CREATE INDEX IF NOT EXISTS idx_mini_metrics_account ON mini_program_metrics(account_id);
CREATE INDEX IF NOT EXISTS idx_ad_metrics_date ON ad_metrics(date);
CREATE INDEX IF NOT EXISTS idx_ad_metrics_account ON ad_metrics(account_id);
CREATE INDEX IF NOT EXISTS idx_drama_metrics_date ON drama_metrics(date);
CREATE INDEX IF NOT EXISTS idx_funnel_date ON funnel_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_ecosystem_date ON ecosystem_metrics(date);

-- ==================== 初始数据 ====================

-- 插入默认系统配置
INSERT INTO system_configs (key, value, description, category) VALUES
    ('site_name', 'Clip Workflow', '站点名称', 'general'),
    ('site_description', 'AI 驱动的智能视频剪辑平台', '站点描述', 'general'),
    ('max_upload_size', '524288000', '最大上传文件大小（字节）', 'upload'),
    ('allowed_video_extensions', '.mp4,.avi,.mov,.mkv,.webm', '允许的视频文件扩展名', 'upload'),
    ('allowed_audio_extensions', '.mp3,.wav,.aac,.flac,.ogg', '允许的音频文件扩展名', 'upload'),
    ('default_ai_model', 'qwen-vl-max', '默认 AI 剪辑模型', 'autoclip'),
    ('max_concurrent_tasks', '10', '最大并发剪辑任务数', 'autoclip'),
    ('task_timeout_seconds', '3600', '任务超时时间（秒）', 'autoclip'),
    ('jwt_access_token_expire_minutes', '30', 'JWT 访问令牌过期时间（分钟）', 'auth'),
    ('jwt_refresh_token_expire_days', '7', 'JWT 刷新令牌过期时间（天）', 'auth')
ON CONFLICT (key) DO NOTHING;

-- 插入默认工作流模板
INSERT INTO workflow_templates (name, description, category, config, is_system, is_public) VALUES
    ('智能高光剪辑', '自动识别视频中的高光时刻并生成精彩片段', 'auto_clip', '{"type": "highlight", "ai_model": "qwen-vl-max", "max_duration": 60, "min_clip_duration": 5, "scene_threshold": 0.7}', TRUE, TRUE),
    ('字幕生成', '自动为视频生成字幕并支持导出 SRT 格式', 'subtitle', '{"type": "subtitle", "language": "zh", "model": "whisper-large", "output_formats": ["srt", "vtt"]}', TRUE, TRUE),
    ('视频摘要', '将长视频自动压缩为短视频摘要', 'summary', '{"type": "summary", "ai_model": "qwen-vl-max", "target_duration_ratio": 0.3, "keep_audio": true}', TRUE, TRUE),
    ('多平台适配', '将视频自动裁剪适配为不同平台的尺寸规格', 'adaptation', '{"type": "adaptation", "target_aspect_ratios": ["16:9", "9:16", "1:1", "4:3"], "keep_important_content": true}', TRUE, TRUE)
ON CONFLICT DO NOTHING;