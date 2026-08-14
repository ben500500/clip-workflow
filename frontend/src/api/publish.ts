import client from './client';
import type { PublishProfile, PublishTask, PublishBatch, VideoAccount, MiniProgram } from '../types';

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
  video_account_id?: string;
  mini_program_id?: string;
  prompt_record_id?: string;
  material_id?: string;
}

export interface VideoAccountInput {
  account_name: string;
  platform: string;
  group_name?: string;
  wxid?: string;
  account_uid?: string;
  profile_id?: string;
  mini_program_enabled?: boolean;
  remark?: string;
  enabled?: boolean;
  operator_id?: string;
}

export interface PublishTaskAssignInput {
  output_id: string;
  platform: string;
  account_id?: string;
  operator_ids?: string[];
  strategy?: string;
  title?: string;
  description?: string;
  tags?: string[];
  cover_file_key?: string;
  mini_program_link?: string;
}

export interface MiniProgramInput {
  name: string;
  appid?: string;
  path?: string;
  full_link: string;
  remark?: string;
  enabled?: boolean;
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

  // ── 账号矩阵（视频号/抖音/快手） ──
  getVideoAccounts: (params?: { platform?: string; group_name?: string }) =>
    client.get('/publish/video-accounts', { params }) as Promise<VideoAccount[]>,

  createVideoAccount: (data: VideoAccountInput) =>
    client.post('/publish/video-accounts', data) as Promise<VideoAccount>,

  createVideoAccountsBatch: (accounts: VideoAccountInput[], skipDuplicates = true) =>
    client.post('/publish/video-accounts/batch', { accounts, skip_duplicates: skipDuplicates }) as Promise<{
      imported: number;
      skipped: number;
      errors: { account_name: string; error: string }[];
    }>,

  updateVideoAccount: (id: string, data: Partial<VideoAccountInput>) =>
    client.put(`/publish/video-accounts/${id}`, data) as Promise<VideoAccount>,

  deleteVideoAccount: (id: string) => client.delete(`/publish/video-accounts/${id}`) as Promise<void>,

  // ── 多运营者发布批次（R14） ──
  getBatches: () => client.get('/publish/batches') as Promise<PublishBatch[]>,

  getBatch: (id: string) =>
    client.get(`/publish/batches/${id}`) as Promise<PublishBatch & { tasks: PublishTask[] }>,

  assignBatch: (data: PublishTaskAssignInput) =>
    client.post('/publish/batches/assign', data) as Promise<PublishBatch & { tasks: PublishTask[] }>,

  // ── 小程序链接库 ──
  getMiniPrograms: (params?: { enabled_only?: boolean }) =>
    client.get('/publish/mini-programs', { params }) as Promise<MiniProgram[]>,

  createMiniProgram: (data: MiniProgramInput) =>
    client.post('/publish/mini-programs', data) as Promise<MiniProgram>,

  updateMiniProgram: (id: string, data: Partial<MiniProgramInput>) =>
    client.put(`/publish/mini-programs/${id}`, data) as Promise<MiniProgram>,

  deleteMiniProgram: (id: string) => client.delete(`/publish/mini-programs/${id}`) as Promise<void>,
};
