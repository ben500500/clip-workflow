// ========== 项目相关 ==========

export interface Project {
  id: number;
  name: string;
  description: string;
  platform: string;
  platform_profile_id?: number;
  status: 'active' | 'archived' | 'completed';
  total_episodes: number;
  processed_episodes: number;
  created_at: string;
  updated_at: string;
}

export interface Episode {
  id: number;
  project_id: number;
  title: string;
  file_path: string;
  file_size: number;
  duration: number;
  status: 'uploaded' | 'clips_detected' | 'intervals_detected' | 'slicing' | 'completed' | 'failed';
  clip_count: number;
  interval_count: number;
  slice_count: number;
  created_at: string;
  updated_at: string;
}

// ========== AutoClip 选点相关 ==========

export interface AutoClipConfig {
  min_clip_duration: number;
  max_clip_duration: number;
  min_confidence: number;
  max_clips: number;
  overlap_ratio: number;
  detect_types: string[];
  custom_prompt?: string;
}

export interface ClipCandidate {
  id: number;
  episode_id: number;
  start_time: number;
  end_time: number;
  confidence: number;
  clip_type: string;
  label: string;
  description: string;
  status: 'pending' | 'approved' | 'rejected' | 'adjusted';
  adjusted_start?: number;
  adjusted_end?: number;
  created_at: string;
  updated_at: string;
}

// ========== 区间检测相关 ==========

export interface IntervalDetectionConfig {
  min_interval_duration: number;
  max_interval_duration: number;
  merge_threshold: number;
  min_silence_duration: number;
  voice_activity_threshold: number;
  detect_modes: string[];
}

export interface DetectedInterval {
  id: number;
  episode_id: number;
  start_time: number;
  end_time: number;
  duration: number;
  interval_type: string;
  confidence: number;
  label: string;
  status: 'pending' | 'approved' | 'rejected' | 'adjusted';
  adjusted_start?: number;
  adjusted_end?: number;
  created_at: string;
  updated_at: string;
}

// ========== 去重与切片相关 ==========

export interface DedupeConfig {
  enabled: boolean;
  similarity_threshold: number;
  method: 'hash' | 'perceptual' | 'content';
  max_duplicate_ratio: number;
}

export interface SliceTask {
  id: number;
  episode_id: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  total_clips: number;
  completed_clips: number;
  failed_clips: number;
  config: Record<string, unknown>;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface SliceOutput {
  id: number;
  slice_task_id: number;
  clip_candidate_id?: number;
  detected_interval_id?: number;
  file_path: string;
  file_size: number;
  duration: number;
  start_time: number;
  end_time: number;
  label: string;
  status: 'completed' | 'failed';
  error_message?: string;
  created_at: string;
}

// ========== 发布相关 ==========

export interface Publication {
  id: number;
  slice_output_id: number;
  platform: string;
  status: 'pending' | 'published' | 'failed';
  published_url?: string;
  published_at?: string;
  error_message?: string;
  created_at: string;
}

// ========== 系统配置相关 ==========

export interface SystemConfig {
  auto_clip: AutoClipConfig;
  interval_detection: IntervalDetectionConfig;
  dedupe: DedupeConfig;
  output_dir: string;
  concurrency: number;
  retention_days: number;
}

export interface PlatformProfile {
  id: number;
  platform: string;
  name: string;
  config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ========== API 通用响应 ==========

export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface TaskProgressEvent {
  task_id: number;
  episode_id: number;
  status: string;
  progress: number;
  current_step: string;
  message: string;
  timestamp: string;
}

// ========== 表单类型 ==========

export interface ProjectFormValues {
  name: string;
  description: string;
  platform: string;
  platform_profile_id?: number;
}

export interface AutoClipFormValues {
  min_clip_duration: number;
  max_clip_duration: number;
  min_confidence: number;
  max_clips: number;
  overlap_ratio: number;
  detect_types: string[];
  custom_prompt?: string;
}

export interface IntervalDetectionFormValues {
  min_interval_duration: number;
  max_interval_duration: number;
  merge_threshold: number;
  min_silence_duration: number;
  voice_activity_threshold: number;
  detect_modes: string[];
}

export interface DedupeFormValues {
  enabled: boolean;
  similarity_threshold: number;
  method: 'hash' | 'perceptual' | 'content';
  max_duplicate_ratio: number;
}

// ========== 发布管理 v2 ==========

export type PublishPlatform = 'wechat_channels' | 'douyin' | 'kuaishou';
export type PublishStatus = 'pending' | 'uploading' | 'processing' | 'pending_confirm' | 'published' | 'failed';

export interface PublishTask {
  id: string;
  output_id: string;
  platform: PublishPlatform;
  account_name: string;
  status: PublishStatus;
  celery_task_id?: string;
  title: string;
  description: string;
  tags: string[];
  cover_file_key?: string;
  mini_program_link?: string;
  link_attached: boolean;
  published_url?: string;
  published_id?: string;
  published_at?: string;
  error_message?: string;
  require_manual_confirm: boolean;
  screenshot_key?: string;
  created_at: string;
  updated_at: string;
}

export interface PublishProfile {
  id: string;
  platform: PublishPlatform;
  account_name: string;
  chrome_debug_port: number;
  cookie_file?: string;
  title_template: string;
  description_template: string;
  default_tags: string[];
  mini_program_link?: string;
  publish_mode: 'immediate' | 'scheduled';
  require_manual_confirm: boolean;
  min_interval_seconds: number;
  max_daily_publish: number;
  created_at: string;
}

export interface PublishTaskFormValues {
  output_id: string;
  platform: PublishPlatform;
  profile_id: string;
  title: string;
  description: string;
  tags: string[];
  cover_mode: 'auto' | 'manual';
  publish_mode: 'immediate' | 'scheduled';
  scheduled_time?: string;
}

// ========== IAA 数据看板 v2 ==========

export interface DashboardOverview {
  today_revenue: number;
  week_revenue: number;
  total_play: number;
  total_uv: number;
  ecpm: number;
  revenue_per_uv: number;
  today_revenue_change?: number;
  week_revenue_change?: number;
  total_play_change?: number;
}

export interface DashboardTrend {
  dates: string[];
  revenue: number[];
  play_count: number[];
  uv: number[];
  ecpm: number[];
}

export interface FunnelData {
  play: number;
  jump: number;
  jump_rate: number;
  mini_uv: number;
  play_rate: number;
  ad_impression: number;
  exposure_rate: number;
  revenue: number;
  revenue_per_1000_play: number;
}

export interface VideoMetric {
  id: string;
  publish_task_id?: string;
  video_id?: string;
  title: string;
  publish_date: string;
  account_id: string;
  play_count: number;
  finish_rate: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  favorite_count: number;
  social_recommend_ratio: number;
  jump_click_count: number;
  jump_click_rate: number;
  attributed_uv: number;
  attributed_revenue: number;
  content_type?: string;
  drama_id?: string;
  traffic_method?: string;
  publish_time_slot?: string;
  play_level?: string;
  production_cost: number;
}

export interface MiniProgramMetric {
  id: string;
  date: string;
  account_id: string;
  uv: number;
  new_user_count: number;
  drama_play_count: number;
  avg_play_duration: number;
  drama_finish_rate: number;
}

export interface AdMetric {
  id: string;
  date: string;
  account_id: string;
  impression_count: number;
  click_count: number;
  ctr: number;
  ecpm: number;
  revenue: number;
  reward_video_impression: number;
  reward_video_revenue: number;
  interstitial_impression: number;
  interstitial_revenue: number;
}

export interface DramaMetric {
  id: string;
  date: string;
  drama_id: string;
  account_id: string;
  uv: number;
  play_count: number;
  finish_rate: number;
  ad_impression: number;
  ad_revenue: number;
}

export interface DashboardConfig {
  accounts: Array<{
    id: string;
    name: string;
    platform: string;
    mini_program_id: string;
  }>;
  dramas: Array<{
    id: string;
    name: string;
    episode_count: number;
    mini_program_drama_id: string;
  }>;
  attribution: {
    method: 'channel_param' | 'indirect';
    time_window_days: number;
    default_uv_revenue: number;
  };
  alerts: {
    revenue_drop_percent: number;
    ecpm_min_value: number;
    jump_rate_min_percent: number;
  };
}