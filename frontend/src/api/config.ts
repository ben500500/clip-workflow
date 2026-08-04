import client from './client';
import type { ApiResponse, SystemConfig, PlatformProfile } from '../types';

export const configApi = {
  /** 获取系统配置 */
  getSystemConfig() {
    return client.get<ApiResponse<SystemConfig>>('/config/system');
  },

  /** 更新系统配置 */
  updateSystemConfig(data: Partial<SystemConfig>) {
    return client.put<ApiResponse<SystemConfig>>('/config/system', data);
  },

  /** 获取平台配置列表 */
  getPlatformProfiles() {
    return client.get<ApiResponse<PlatformProfile[]>>('/config/platforms');
  },

  /** 创建平台配置 */
  createPlatformProfile(data: Partial<PlatformProfile>) {
    return client.post<ApiResponse<PlatformProfile>>('/config/platforms', data);
  },

  /** 更新平台配置 */
  updatePlatformProfile(id: number, data: Partial<PlatformProfile>) {
    return client.put<ApiResponse<PlatformProfile>>(`/config/platforms/${id}`, data);
  },

  /** 删除平台配置 */
  deletePlatformProfile(id: number) {
    return client.delete<ApiResponse<null>>(`/config/platforms/${id}`);
  },
};