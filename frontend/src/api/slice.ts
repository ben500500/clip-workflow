import client from './client';
import type { ApiResponse, SliceTask, SliceOutput, DedupeConfig } from '../types';

export interface SliceRequest {
  episode_id: number;
  candidate_ids?: number[];
  interval_ids?: number[];
  dedupe_config?: DedupeConfig;
  output_dir?: string;
}

export const sliceApi = {
  /** 启动切片任务 */
  start(data: SliceRequest) {
    return client.post<ApiResponse<{ task_id: number }>>('/slice/start', data);
  },

  /** 获取切片任务列表 */
  getTasks(episodeId: number) {
    return client.get<ApiResponse<SliceTask[]>>('/slice/tasks', {
      params: { episode_id: episodeId },
    });
  },

  /** 获取切片任务详情 */
  getTaskDetail(taskId: number) {
    return client.get<ApiResponse<SliceTask>>(`/slice/tasks/${taskId}`);
  },

  /** 获取切片输出列表 */
  getOutputs(taskId: number) {
    return client.get<ApiResponse<SliceOutput[]>>(`/slice/outputs`, {
      params: { task_id: taskId },
    });
  },

  /** 取消切片任务 */
  cancelTask(taskId: number) {
    return client.post<ApiResponse<null>>(`/slice/tasks/${taskId}/cancel`);
  },

  /** 重试失败的切片 */
  retryFailed(taskId: number) {
    return client.post<ApiResponse<null>>(`/slice/tasks/${taskId}/retry`);
  },
};