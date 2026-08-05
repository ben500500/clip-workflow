import client from './client';
import type {
  AdMetric,
  ApiList,
  DashboardOverview,
  DramaMetric,
  FunnelData,
  MiniProgramMetric,
  TrendPoint,
  VideoMetric,
} from '../types';

export const dashboardApi = {
  getOverview: (params?: { date?: string; account_id?: string }) =>
    client.get('/dashboard/overview', { params }) as Promise<DashboardOverview>,

  getTrend: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/overview/trend', { params }) as Promise<TrendPoint[]>,

  getFunnel: (params?: { date?: string; account_id?: string }) =>
    client.get('/dashboard/overview/funnel', { params }) as Promise<FunnelData>,

  getTopVideos: (params?: { limit?: number; account_id?: string }) =>
    client.get('/dashboard/overview/top-videos', { params }) as Promise<VideoMetric[]>,

  getVideos: (params?: {
    page?: number;
    page_size?: number;
    sort_by?: string;
    content_type?: string;
    play_level?: string;
    account_id?: string;
  }) => client.get('/dashboard/videos', { params }) as Promise<ApiList<VideoMetric>>,

  getVideoRanking: (params?: { sort_by?: string; limit?: number; account_id?: string }) =>
    client.get('/dashboard/videos/ranking', { params }) as Promise<VideoMetric[]>,

  getMiniProgramMetrics: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/mini-program', { params }) as Promise<MiniProgramMetric[]>,

  getAdMetrics: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/ads', { params }) as Promise<AdMetric[]>,

  getDramaMetrics: (params?: { account_id?: string }) =>
    client.get('/dashboard/dramas', { params }) as Promise<DramaMetric[]>,

  getFunnelTrend: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/funnel/trend', { params }) as Promise<FunnelData[]>,

  importVideoMetrics: (file: File, accountId?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (accountId) formData.append('account_id', accountId);
    return client.post('/dashboard/metrics/video', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as Promise<{ success: boolean; imported_count: number; errors: string[] }>;
  },

  importMiniProgramMetrics: (file: File, accountId?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (accountId) formData.append('account_id', accountId);
    return client.post('/dashboard/metrics/mini-program', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as Promise<{ success: boolean; imported_count: number; errors: string[] }>;
  },

  importAdMetrics: (file: File, accountId?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (accountId) formData.append('account_id', accountId);
    return client.post('/dashboard/metrics/ads', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as Promise<{ success: boolean; imported_count: number; errors: string[] }>;
  },

  downloadTemplate: (type: string) =>
    client.get('/dashboard/metrics/template', { params: { type }, responseType: 'blob' }) as Promise<Blob>,

  getConfig: () =>
    client.get('/dashboard/config') as Promise<{ config: Record<string, unknown> }>,

  updateConfig: (data: Record<string, unknown>) =>
    client.put('/dashboard/config', data) as Promise<{ config: Record<string, unknown> }>,
};
