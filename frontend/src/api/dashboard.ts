import client from './client';
import type {
  AdMetric,
  ApiList,
  CrossAnalysisData,
  DashboardOverview,
  DramaDetail,
  DramaMetric,
  EcosystemMetric,
  FilePreviewResult,
  FunnelCompareData,
  FunnelData,
  ImportHistoryRecord,
  ImportTemplate,
  MiniProgramMetric,
  PlatformDetectResult,
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

  getCrossAnalysis: (params?: { account_id?: string }) =>
    client.get('/dashboard/videos/cross-analysis', { params }) as Promise<CrossAnalysisData>,

  getMiniProgramMetrics: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/mini-program', { params }) as Promise<MiniProgramMetric[]>,

  getAdMetrics: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/ads', { params }) as Promise<AdMetric[]>,

  getDramaMetrics: (params?: { account_id?: string }) =>
    client.get('/dashboard/dramas', { params }) as Promise<DramaMetric[]>,

  getDramaDetail: (dramaId: string, params?: { account_id?: string }) =>
    client.get(`/dashboard/dramas/${dramaId}`, { params }) as Promise<DramaDetail>,

  getFunnelTrend: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/funnel/trend', { params }) as Promise<FunnelData[]>,

  getFunnelCompare: (params?: { account_id?: string }) =>
    client.get('/dashboard/funnel/compare', { params }) as Promise<FunnelCompareData>,

  getEcosystem: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/ecosystem', { params }) as Promise<EcosystemMetric[]>,

  // ---- Smart Import ----

  smartImportUpload: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/dashboard/import/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as Promise<PlatformDetectResult>;
  },

  importPreview: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/dashboard/import/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as Promise<FilePreviewResult>;
  },

  importConfirm: (file: File, mapping: Record<string, string>, targetTable: string, accountId?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    const params = new URLSearchParams();
    params.append('mapping', JSON.stringify(mapping));
    params.append('target_table', targetTable);
    if (accountId) params.append('account_id', accountId);
    return client.post(`/dashboard/import/confirm?${params.toString()}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as Promise<{ success: boolean; imported_count: number; errors: string[] }>;
  },

  getImportTemplates: () =>
    client.get('/dashboard/import/templates') as Promise<ImportTemplate[]>,

  saveCustomTemplate: (data: { name: string; platform: string; mapping: Record<string, string>; unit_conversions?: Record<string, unknown> }) =>
    client.post('/dashboard/import/templates/custom', data) as Promise<ImportTemplate>,

  getImportHistory: () =>
    client.get('/dashboard/import/history') as Promise<ImportHistoryRecord[]>,

  // ---- Legacy Import ----

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
