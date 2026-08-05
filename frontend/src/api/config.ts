import client from './client';
import type { PlatformProfile, SystemConfig } from '../types';

export const configApi = {
  getAll: () => client.get('/config') as Promise<SystemConfig[]>,

  update: (key: string, value: unknown) =>
    client.put('/config', { key, value }) as Promise<SystemConfig>,

  getPlatformProfiles: () => client.get('/config/platform-profiles') as Promise<PlatformProfile[]>,

  createPlatformProfile: (data: Partial<PlatformProfile>) =>
    client.post('/config/platform-profiles', data) as Promise<PlatformProfile>,

  updatePlatformProfile: (id: string, data: Partial<PlatformProfile>) =>
    client.put(`/config/platform-profiles/${id}`, data) as Promise<PlatformProfile>,

  deletePlatformProfile: (id: string) =>
    client.delete(`/config/platform-profiles/${id}`) as Promise<void>,
};
