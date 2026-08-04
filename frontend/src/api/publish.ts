import client from './client';

export const publishApi = {
  getTasks: (params?: { platform?: string; status?: string; page?: number; page_size?: number }) =>
    client.get('/publish/tasks', { params }),
  
  getTask: (id: string) =>
    client.get(`/publish/tasks/${id}`),
  
  createTask: (data: any) =>
    client.post('/publish/tasks', data),
  
  confirmTask: (id: string) =>
    client.post(`/publish/tasks/${id}/confirm`),
  
  getProfiles: () =>
    client.get('/publish/profiles'),
  
  createProfile: (data: any) =>
    client.post('/publish/profiles', data),
  
  updateProfile: (id: string, data: any) =>
    client.put(`/publish/profiles/${id}`, data),
  
  deleteProfile: (id: string) =>
    client.delete(`/publish/profiles/${id}`),
};
