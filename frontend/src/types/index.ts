// ========== 通用 ==========

export interface ApiList<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiError {
  detail?: string;
}

// ========== 项目与剧集 ==========

export type ProjectStatus = 'draft' | 'processing' | 'completed' | 'archived';

export interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  config: Record<string, unknown> | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
  episode_count: number;
}

export interface ProjectFormValues {
  name: string;
  description?: string;
  status?: string;
  config?: Record<string, unknown>;
}

export interface ProjectStats {
  total_projects: number;
  active_projects: number;
  total_episodes: number;
  processed_episodes: number;
  total_slices: number;
  recent_projects: Project[];
}

export interface Episode {
  id: string;
  project_id: string;
  title: string | null;
  episode_no: number | null;
  source_file_key: string | null;
  duration: number | null;
  resolution: string | null;
  file_size: number | null;
  status: string;
  created_at: string;
  updated_at: string;
}

// ========== AutoClip 选点 ==========

export interface ClipCandidate {
  id: string;
  episode_id: string;
  clip_index: number | null;
  start_time: number | null;
  end_time: number | null;
  duration: number | null;
  title: string | null;
  content: string | null;
  outline: string | null;
  score: number | null;
  recommend_reason: string | null;
  status: string;
  adjusted_start: number | null;
  adjusted_end: number | null;
  created_at: string;
}

export interface AutoClipRunRecord {
  id: string;
  episode_id: string;
  autoclip_project_id: string | null;
  celery_task_id: string | null;
  status: string;
  progress: number;
  message: string | null;
  error_message: string | null;
  config: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface IntervalHistoryItem {
  id: string;
  episode_id: string;
  mode: string | null;
  status: string | null;
  progress: number;
  error_message: string | null;
  interval_count: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AutoClipConfig {
  [key: string]: unknown;
}

// ========== 区间检测 ==========

export interface DetectedInterval {
  id: string;
  episode_id: string;
  interval_type: string | null;
  start_time: number | null;
  end_time: number | null;
  confidence: number | null;
  label: string | null;
  enabled: boolean;
  source: string | null;
  detection_config: Record<string, unknown> | null;
  created_at: string;
}

// ========== 切片 ==========

export interface SliceTask {
  id: string;
  episode_id: string;
  mode: string | null;
  status: string | null;
  progress: number;
  output_count: number;
  error_message: string | null;
  // 实际执行该任务的 Worker 节点 ID
  node_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface WorkerNode {
  id: string;
  node_id: string;
  hostname: string | null;
  ip: string | null;
  os: string | null;
  arch: string | null;
  ffmpeg_version: string | null;
  tags: string[];
  max_concurrent: number;
  // 节点是否启用（管理员可启停）
  enabled: boolean;
  status: string;
  current_tasks: number;
  total_tasks_completed: number;
  total_tasks_failed: number;
  last_heartbeat: string | null;
  started_at: string | null;
  created_at: string;
  // 该节点正在运行的任务平均进度（工作时进度显示）
  running_progress?: number;
  // 该节点 CPU 资源分配比例（%，默认 50）
  cpu_percent?: number;
  // 该节点正在运行的任务列表（含 task_id/阶段/模式/进度）
  running_tasks?: WorkerRunningTask[];
}

export interface WorkerRunningTask {
  task_id: string;
  status: string;
  progress: number;
  // 任务阶段：download / ffmpeg / upload 等
  phase?: string;
  // 切片模式：fast / dedupe / scrub
  mode?: string;
}

export interface SliceOutput {
  id: string;
  task_id: string;
  clip_id: string | null;
  file_key: string | null;
  file_name: string | null;
  duration: number | null;
  file_size: number | null;
  resolution: string | null;
  prompt_record_id: string | null;
  created_at: string;
  presigned_url: string | null;
}

export interface DedupeConfig {
  [key: string]: unknown;
}

// ========== 发布 ==========

export interface PublishTask {
  id: string;
  output_id: string;
  platform: string | null;
  account_name: string | null;
  status: string | null;
  celery_task_id: string | null;
  title: string | null;
  description: string | null;
  tags: string[] | null;
  cover_file_key: string | null;
  mini_program_link: string | null;
  link_attached: boolean;
  published_url: string | null;
  published_id: string | null;
  published_at: string | null;
  error_message: string | null;
  require_manual_confirm: boolean;
  screenshot_key: string | null;
  video_account_id: string | null;
  mini_program_id: string | null;
  prompt_record_id: string | null;
  material_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PublishProfile {
  id: string;
  platform: string | null;
  account_name: string | null;
  chrome_debug_port: number;
  cookie_file: string | null;
  title_template: string | null;
  description_template: string | null;
  default_tags: string[] | null;
  mini_program_link: string | null;
  publish_mode: string;
  require_manual_confirm: boolean;
  min_interval_seconds: number;
  max_daily_publish: number;
  created_at: string;
}

export interface Publication {
  id: string;
  output_id: string;
  platform: string | null;
  publish_url: string | null;
  publish_time: string | null;
  status: string | null;
  reject_reason: string | null;
  operator: string | null;
  created_at: string;
}

// ========== 账号矩阵 / 小程序库（一期） ==========

export interface VideoAccount {
  id: string;
  account_name: string;
  platform: string;
  group_name: string | null;
  wxid: string | null;
  account_uid: string | null;
  profile_id: string | null;
  mini_program_enabled: boolean;
  remark: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface MiniProgram {
  id: string;
  name: string;
  appid: string | null;
  path: string | null;
  full_link: string;
  remark: string | null;
  enabled: boolean;
  created_at: string;
}

// ========== 短片分析（P3） ==========

export interface ShortDramaGeneration {
  prompt_record_id: string | null;
  material_id: string | null;
  source_text: string | null;
  duration: number | null;
  theme: string | null;
  tone: string | null;
  short_title: string | null;
  material_tags: string[];
}

export interface ShortDramaAnalysisRow {
  video_metric_id: string;
  publish_task_id: string | null;
  platform: string | null;
  account_name: string | null;
  video_id: string | null;
  title: string | null;
  publish_date: string | null;
  play_count: number;
  finish_rate: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  favorite_count: number;
  jump_click_count: number;
  jump_click_rate: number;
  attributed_uv: number;
  attributed_revenue: number;
  tags: string[];
  generation: ShortDramaGeneration | null;
}

export interface ShortDramaSummary {
  platform: string | null;
  published_count: number;
  total_play: number;
  avg_finish_rate: number;
  total_jump_click: number;
  attributed_revenue: number;
}

export interface ShortDramaTopic {
  tag: string;
  count: number;
}

// ========== 系统配置 ==========

export interface PlatformProfile {
  id: string;
  name: string;
  platform: string | null;
  description?: string | null;
  dedupe_config: Record<string, unknown> | null;
  target_resolution: string | null;
  target_bitrate: string | null;
  max_duration: number | null;
  created_at: string;
}

export interface SystemConfig {
  key: string;
  value: unknown;
  description?: string | null;
  updated_at: string;
}

// ========== 数据看板 ==========

export interface DashboardOverview {
  today_revenue: number;
  week_revenue: number;
  total_play: number;
  total_uv: number;
  today_uv: number;
  ecpm: number;
  revenue_per_uv: number;
  date: string;
}

export interface TrendPoint {
  date: string;
  play_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  jump_click_count: number;
  attributed_revenue: number;
  revenue: number;
  impression_count: number;
  ecpm: number;
}

export interface FunnelData {
  date: string;
  total_play: number;
  jump_click: number;
  jump_rate: number;
  mini_program_uv: number;
  drama_play_uv: number;
  play_rate: number;
  ad_exposure_uv: number;
  exposure_rate: number;
  revenue: number;
  revenue_per_1000_play: number;
}

export interface VideoMetric {
  id: string;
  publish_task_id: string | null;
  video_id: string | null;
  title: string | null;
  publish_date: string | null;
  account_id: string | null;
  play_count: number;
  finish_rate: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  favorite_count: number;
  social_recommend_ratio: number;
  social_recommend_play: number;
  friend_recommend_play: number;
  jump_click_count: number;
  jump_click_rate: number;
  attributed_uv: number;
  attributed_revenue: number;
  content_type: string | null;
  tags?: string[];
  drama_id: string | null;
  traffic_method: string | null;
  publish_time_slot: string | null;
  play_level: string | null;
  production_cost: number;
  recorded_at: string;
  updated_at: string;
}

export interface MiniProgramMetric {
  id: string;
  date: string | null;
  account_id: string | null;
  uv: number;
  new_user_count: number;
  drama_play_count: number;
  avg_play_duration: number;
  drama_finish_rate: number;
  recorded_at: string | null;
}

export interface AdMetric {
  id: string;
  date: string | null;
  account_id: string | null;
  impression_count: number;
  click_count: number;
  ctr: number;
  ecpm: number;
  revenue: number;
  reward_video_impression: number;
  reward_video_revenue: number;
  interstitial_impression: number;
  interstitial_revenue: number;
  recorded_at: string | null;
}

export interface DramaMetric {
  id: string;
  date: string | null;
  drama_id: string | null;
  account_id: string | null;
  uv: number;
  play_count: number;
  finish_rate: number;
  ad_impression: number;
  ad_revenue: number;
  recorded_at: string | null;
}

export interface EcosystemMetric {
  id: string;
  date: string | null;
  account_id: string | null;
  article_count: number;
  article_read_count: number;
  mini_program_uv_from_article: number;
  wecom_new_friends: number;
  wecom_total_friends: number;
  wecom_source: string | null;
  recorded_at: string | null;
}

export interface ImportTemplate {
  id: string;
  name: string;
  platform: string;
  mapping: Record<string, string>;
  unit_conversions: Record<string, unknown> | null;
  created_at: string | null;
}

export interface ImportHistoryRecord {
  id: string;
  file_name: string;
  platform: string;
  import_mode: string;
  target_table: string;
  imported_count: number;
  updated_count: number;
  error_count: number;
  errors: string[];
  created_at: string | null;
}

export interface PlatformDetectResult {
  detected: boolean;
  headers: string[];
  platform: {
    platform_id: string;
    name: string;
    required_headers: string[];
    optional_headers: string[];
    transforms: Record<string, string | [string, string]>;
    target_table: string;
  } | null;
  preview: Record<string, unknown>[];
  suggested_mapping: Record<string, string>;
  target_table: string | null;
}

export interface FilePreviewResult {
  headers: string[];
  preview: Record<string, unknown>[];
  total_rows: number;
}

export interface CrossAnalysisData {
  by_content_type: Array<{
    content_type: string;
    video_count: number;
    avg_play: number;
    avg_finish_rate: number;
    avg_jump_rate: number;
    total_revenue: number;
  }>;
}

export interface FunnelCompareData {
  this_week: {
    avg_jump_rate: number;
    avg_play_rate: number;
    avg_exposure_rate: number;
    total_revenue: number;
  };
  last_week: {
    avg_jump_rate: number;
    avg_play_rate: number;
    avg_exposure_rate: number;
    total_revenue: number;
  };
  changes: {
    jump_rate_change: number;
    play_rate_change: number;
    exposure_rate_change: number;
    revenue_change: number;
  };
}

export interface DramaDetail {
  summary: {
    drama_id: string;
    total_uv: number;
    total_play: number;
    avg_finish_rate: number;
    total_ad_impression: number;
    total_ad_revenue: number;
  };
  trend: Array<{
    date: string;
    uv: number;
    play_count: number;
    finish_rate: number;
    ad_impression: number;
    ad_revenue: number;
  }>;
}

// ========== 认证与权限 ==========

export type Role = 'admin' | 'operator' | 'publisher' | 'material';

export interface User {
  id: string;
  username: string;
  display_name?: string | null;
  role: Role;
  role_display?: string;
  data_scope?: string;
  menus?: string[];
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface RoleOption {
  value: Role;
  label: string;
}

export const ROLE_OPTIONS: RoleOption[] = [
  { value: 'admin', label: '管理员' },
  { value: 'operator', label: '运营专员' },
  { value: 'publisher', label: '发布专员' },
  { value: 'material', label: '素材专员' },
];

export const DATA_SCOPE_OPTIONS = [
  { value: 'all', label: '全部素材' },
  { value: 'own', label: '仅自己创建' },
];

// ========== 监控告警（三期） ==========

export interface AlertRule {
  id: string;
  name: string;
  metric: string;
  operator: string;
  threshold: number;
  level: string;
  enabled: boolean;
  description: string | null;
  webhook_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertEvent {
  id: string;
  rule_id: string | null;
  rule_name: string | null;
  metric: string | null;
  level: string;
  message: string | null;
  current_value: number | null;
  threshold: number | null;
  notified: boolean;
  notify_error: string | null;
  created_at: string;
}
