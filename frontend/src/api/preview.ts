import client from './client';
import type { ApiResponse, SliceOutput, Publication } from '../types';

export const previewApi = {
  /** 获取成品列表 */
  getOutputs(episodeId: number) {
    return client.get<ApiResponse<SliceOutput[]>>('/preview/outputs', {
      params: { episode_id: episodeId },
    });
  },

  /** 获取成品详情 */
  getOutputDetail(outputId: number) {
    return client.get<ApiResponse<SliceOutput>>(`/preview/outputs/${outputId}`);
  },

  /** 获取下载链接 */
  getDownloadUrl(outputId: number) {
    return client.get<ApiResponse<{ url: string; filename: string }>>(`/preview/download/${outputId}`);
  },

  /** 获取发布状态列表 */
  getPublications(outputId: number) {
    return client.get<ApiResponse<Publication[]>>('/preview/publications', {
      params: { output_id: outputId },
    });
  },

  /** 发布到平台 */
  publish(outputId: number, platform: string) {
    return client.post<ApiResponse<{ publication_id: number }>>('/preview/publish', {
      output_id: outputId,
      platform,
    });
  },

  /** 获取预览流地址 */
  getStreamUrl(outputId: number) {
    return client.get<ApiResponse<{ url: string }>>(`/preview/stream/${outputId}`);
  },
};