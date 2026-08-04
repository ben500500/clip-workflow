import client from './client';
import type { ApiResponse, PaginatedResponse, Project, ProjectFormValues } from '../types';

export interface ProjectListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  platform?: string;
}

export const projectApi = {
  /** 获取项目列表 */
  getList(params?: ProjectListParams) {
    return client.get<ApiResponse<PaginatedResponse<Project>>>('/projects', { params });
  },

  /** 获取单个项目 */
  getById(id: number) {
    return client.get<ApiResponse<Project>>(`/projects/${id}`);
  },

  /** 创建项目 */
  create(data: ProjectFormValues) {
    return client.post<ApiResponse<Project>>('/projects', data);
  },

  /** 更新项目 */
  update(id: number, data: Partial<ProjectFormValues>) {
    return client.put<ApiResponse<Project>>(`/projects/${id}`, data);
  },

  /** 删除项目 */
  delete(id: number) {
    return client.delete<ApiResponse<null>>(`/projects/${id}`);
  },

  /** 获取项目统计 */
  getStats() {
    return client.get<ApiResponse<{
      total_projects: number;
      active_projects: number;
      total_episodes: number;
      processed_episodes: number;
      total_slices: number;
      recent_projects: Project[];
    }>>('/projects/stats');
  },
};