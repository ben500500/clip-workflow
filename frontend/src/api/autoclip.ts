import client from './client';
import type { ApiResponse, AutoClipConfig, ClipCandidate } from '../types';

export const autoclipApi = {
  /** 触发 AutoClip 检测 */
  detect(episodeId: number, config?: Partial<AutoClipConfig>) {
    return client.post<ApiResponse<{ task_id: number }>>(`/autoclip/detect`, {
      episode_id: episodeId,
      config,
    });
  },

  /** 获取选点候选项列表 */
  getCandidates(episodeId: number) {
    return client.get<ApiResponse<ClipCandidate[]>>(`/autoclip/candidates`, {
      params: { episode_id: episodeId },
    });
  },

  /** 更新选点状态 */
  updateCandidate(id: number, data: Partial<ClipCandidate>) {
    return client.put<ApiResponse<ClipCandidate>>(`/autoclip/candidates/${id}`, data);
  },

  /** 批量更新选点状态 */
  batchUpdateCandidates(data: { ids: number[]; status: string; adjusted_start?: number; adjusted_end?: number }) {
    return client.post<ApiResponse<null>>(`/autoclip/candidates/batch`, data);
  },

  /** 获取 AutoClip 检测任务状态 */
  getTaskStatus(taskId: number) {
    return client.get<ApiResponse<{
      task_id: number;
      status: string;
      progress: number;
      candidates_count: number;
    }>>(`/autoclip/tasks/${taskId}`);
  },
};