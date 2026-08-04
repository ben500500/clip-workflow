import client from './client';
import type { ApiResponse, IntervalDetectionConfig, DetectedInterval } from '../types';

export const intervalApi = {
  /** 触发区间检测 */
  detect(episodeId: number, config?: Partial<IntervalDetectionConfig>) {
    return client.post<ApiResponse<{ task_id: number }>>(`/intervals/detect`, {
      episode_id: episodeId,
      config,
    });
  },

  /** 获取检测到的区间列表 */
  getIntervals(episodeId: number) {
    return client.get<ApiResponse<DetectedInterval[]>>(`/intervals`, {
      params: { episode_id: episodeId },
    });
  },

  /** 更新区间状态 */
  updateInterval(id: number, data: Partial<DetectedInterval>) {
    return client.put<ApiResponse<DetectedInterval>>(`/intervals/${id}`, data);
  },

  /** 批量更新区间状态 */
  batchUpdateIntervals(data: { ids: number[]; status: string; adjusted_start?: number; adjusted_end?: number }) {
    return client.post<ApiResponse<null>>(`/intervals/batch`, data);
  },

  /** 获取区间检测任务状态 */
  getTaskStatus(taskId: number) {
    return client.get<ApiResponse<{
      task_id: number;
      status: string;
      progress: number;
      intervals_count: number;
    }>>(`/intervals/tasks/${taskId}`);
  },
};