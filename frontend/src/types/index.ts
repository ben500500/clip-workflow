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