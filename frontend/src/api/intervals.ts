import client from './client';
import type { DetectedInterval, IntervalHistoryItem } from '../types';

export const intervalApi = {
  detect: (episodeId: string, mode: string, config?: Record<string, unknown>) =>
    client.post(`/episodes/${episodeId}/intervals/detect`, { mode, config }) as Promise<{
      celery_task_id: string;
      message: string;
    }>,

  history: (episodeId: string) =>
    client.get(`/episodes/${episodeId}/intervals/history`) as Promise<IntervalHistoryItem[]>,

  progress: (episodeId: string) =>
    client.get(`/episodes/${episodeId}/intervals/progress`) as Promise<{
      status: string;
      progress: number;
      message: string;
      error_message?: string | null;
      interval_count?: number | null;
      interval_type?: string | null;
    }>,

  list: (episodeId: string) =>
    client.get(`/episodes/${episodeId}/intervals`) as Promise<DetectedInterval[]>,

  create: (data: {
    episode_id: string;
    interval_type: string;
    start_time: number;
    end_time: number;
    confidence?: number;
    label?: string;
    enabled?: boolean;
    source?: string;
  }) => client.post('/intervals', data) as Promise<DetectedInterval>,

  update: (id: string, data: Partial<DetectedInterval>) =>
    client.put(`/intervals/${id}`, data) as Promise<DetectedInterval>,

  remove: (id: string) => client.delete(`/intervals/${id}`) as Promise<void>,

  toggle: (id: string) => client.put(`/intervals/${id}/toggle`) as Promise<DetectedInterval>,
};
