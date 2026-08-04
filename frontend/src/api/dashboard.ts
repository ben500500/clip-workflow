import client from './client';

export const dashboardApi = {
  getOverview: (params?: { date?: string; account_id?: string }) =>
    client.get('/dashboard/overview', { params }),
  
  getTrend: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/overview/trend', { params }),
  
  getFunnel: (params?: { date?: string; account_id?: string }) =>
    client.get('/dashboard/overview/funnel', { params }),
  
  getTopVideos: (params?: { date?: string; account_id?: string; limit?: number }) =>
    client.get('/dashboard/overview/top-videos', { params }),
  
  getVideos: (params?: { page?: number; page_size?: number; account_id?: string; content_type?: string; drama_id?: string }) =>
    client.get('/dashboard/videos', { params }),
  
  getVideoDetail: (id: string) =>
    client.get(`/dashboard/videos/${id}`),
  
  updateVideoTags: (id: string, data: any) =>
    client.put(`/dashboard/videos/${id}/tags`, data),
  
  getVideoRanking: (params?: { sort_by?: string; limit?: number; account_id?: string }) =>
    client.get('/dashboard/videos/ranking', { params }),
  
  getMiniProgramMetrics: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/mini-program', { params }),
  
  getAdMetrics: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/ads', { params }),
  
  getDramaMetrics: (params?: { account_id?: string }) =>
    client.get('/dashboard/dramas', { params }),
  
  getFunnelTrend: (params?: { start_date?: string; end_date?: string; account_id?: string }) =>
    client.get('/dashboard/funnel/trend', { params }),
  
  importVideoMetrics: (file: File, accountId: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('account_id', accountId);
    return client.post('/dashboard/metrics/video', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  
  importMiniProgramMetrics: (file: File, accountId: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('account_id', accountId);
    return client.post('/dashboard/metrics/mini-program', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  
  importAdMetrics: (file: File, accountId: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('account_id', accountId);
    return client.post('/dashboard/metrics/ads', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  
  downloadTemplate: () =>
    client.get('/dashboard/metrics/template', { responseType: 'blob' }),
  
  getConfig: () =>
    client.get('/dashboard/config'),
  
  updateConfig: (data: any) =>
    client.put('/dashboard/config', data),
};
