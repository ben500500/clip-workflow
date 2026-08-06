import client from './client';
import type { ApiList, Episode, Project, ProjectFormValues, ProjectStats } from '../types';

export interface ProjectListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
}

export const projectApi = {
  getList: (params?: ProjectListParams) =>
    client.get('/projects', { params }) as Promise<ApiList<Project>>,

  getById: (id: string) =>
    client.get(`/projects/${id}`) as Promise<Project>,

  create: (data: ProjectFormValues) =>
    client.post('/projects', data) as Promise<Project>,

  update: (id: string, data: Partial<ProjectFormValues>) =>
    client.put(`/projects/${id}`, data) as Promise<Project>,

  remove: (id: string) =>
    client.delete(`/projects/${id}`) as Promise<void>,

  getStats: () =>
    client.get('/projects/stats') as Promise<ProjectStats>,

  getEpisodes: (projectId: string) =>
    client.get(`/projects/${projectId}/episodes`) as Promise<{ items: Episode[]; total: number }>,

  getEpisode: (episodeId: string) =>
    client.get(`/episodes/${episodeId}`) as Promise<Episode>,

  deleteEpisode: (episodeId: string) =>
    client.delete(`/episodes/${episodeId}`) as Promise<void>,

  getVideoUrl: (episodeId: string) =>
    client.get(`/episodes/${episodeId}/video-url`) as Promise<{
      url: string;
      duration: number | null;
      title: string | null;
    }>,
};
