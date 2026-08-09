import client from './client';
import type { PublishProfile, PublishTask } from '../types';

export interface PublishTaskCreate {
  output_id: string;
  platform: string;
  account_name?: string;
  title?: string;
  description?: string;
  tags?: string[];
  cover_file_key?: string;
  mini_program_link?: string;
  link_attached?: boolean;
  require_manual_confirm?: boolean;
}

export const publishApi = {
  getTasks: (params?: { platform?: string; status?: string; start_date?: string; end_date?: string }) =>
    client.get('/publish/tasks', { params }) as Promise<PublishTask[]>,

  getTask: (id: string) => client.get(`/publish/tasks/${id}`) as Promise<PublishTask>,

  createTask: (data: PublishTaskCreate) => client.post('/publish/tasks', data) as Promise<PublishTask>,

  createTasks: (tasks: PublishTaskCreate[]) =>
    client.post('/publish/tasks/batch', { tasks }) as Promise<PublishTask[]>,

  confirmTask: (id: string) =>
    client.post(`/publish/tasks/${id}/confirm`) as Promise<{
      id: string;
      status: string;
      published_url: string | null;
      published_id: string | null;
    }>,

  getTaskScreenshot: (id: string) =>
    client.get(`/publish/tasks/${id}/screenshot`) as Promise<{
      task_id: string;
      screenshot_url: string | null;
    }>,

  getProfiles: () => client.get('/publish/profiles') as Promise<PublishProfile[]>,

  createProfile: (data: Partial<PublishProfile>) =>
    client.post('/publish/profiles', data) as Promise<PublishProfile>,

  updateProfile: (id: string, data: Partial<PublishProfile>) =>
    client.put(`/publish/profiles/${id}`, data) as Promise<PublishProfile>,

  deleteProfile: (id: string) => client.delete(`/publish/profiles/${id}`) as Promise<void>,
};
