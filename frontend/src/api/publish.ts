import client from './client';
import type { PublishProfile, PublishTask, PublishBatch, VideoAccount, MiniProgram, OperatorRouteRow, OperatorStat, PublishAuditItem, LoginAuditItem, RiskEventItem, AuditResult, MultiOpVerification } from '../types';

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
  // 发布跳转配置：['native'] / ['mini_program'] / 两者都选
  publish_jump?: string[];
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

  batchAssignProfile: (accountIds: string[], profileId?: string) =>
    client.post('/publish/video-accounts/batch-assign-profile', {
      account_ids: accountIds,
      profile_id: profileId,
    }) as Promise<{ updated: number; errors: { account_id: string; error: string }[] }>,

  // ── 多运营者发布批次（R14） ──
  getBatches: () => client.get('/publish/batches') as Promise<PublishBatch[]>,

  getBatch: (id: string) =>
    client.get(`/publish/batches/${id}`) as Promise<PublishBatch & { tasks: PublishTask[] }>,

  assignBatch: (data: PublishTaskAssignInput) =>
    client.post('/publish/batches/assign', data) as Promise<PublishBatch & { tasks: PublishTask[] }>,

  // ── 方向② 批量发布体验：批次进度统计 + 死信重发 ──
  getBatchStats: (id: string) =>
    client.get(`/publish/batches/${id}/stats`) as Promise<{
      batch_id: string;
      total: number;
      status: { pending: number; running: number; pending_confirm: number; published: number; failed: number };
      dead_letter: number;
    }>,

  requeueTask: (taskId: string) =>
    client.post(`/publish/tasks/${taskId}/requeue`) as Promise<{
      id: string;
      status: string;
      celery_task_id: string;
      message: string;
    }>,

  // ── 小程序链接库 ──
  getMiniPrograms: (params?: { enabled_only?: boolean }) =>
    client.get('/publish/mini-programs', { params }) as Promise<MiniProgram[]>,

  createMiniProgram: (data: MiniProgramInput) =>
    client.post('/publish/mini-programs', data) as Promise<MiniProgram>,

  updateMiniProgram: (id: string, data: Partial<MiniProgramInput>) =>
    client.put(`/publish/mini-programs/${id}`, data) as Promise<MiniProgram>,

  deleteMiniProgram: (id: string) => client.delete(`/publish/mini-programs/${id}`) as Promise<void>,

  // ── 多运营者：端口矩阵 + 审计（P1 问题10） ──
  getOperatorMatrix: () =>
    client.get('/publish/multi-operator/matrix') as Promise<OperatorRouteRow[]>,

  getOperatorStats: () =>
    client.get('/publish/multi-operator/operators') as Promise<OperatorStat[]>,

  getAuditLogs: (params?: { action?: string; kind?: string; request_id?: string; limit?: number }) =>
    client.get('/publish/audit', { params }) as Promise<AuditResult>,

  traceAudit: (requestId: string) =>
    client.get(`/publish/audit/trace/${requestId}`) as Promise<{
      request_id: string;
      publish: PublishAuditItem[];
      login: LoginAuditItem[];
      cookie: Array<{ id: string; profile_id: string | null; account_id: string | null; actor_id: string | null; operator_id: string | null; purpose: string | null; ip_address: string | null; request_id: string | null; created_at: string | null }>;
      risk: RiskEventItem[];
    }>,

  // ── 登录态自服务扫码（P0 主题1 / 4.1） ──
  applyLoginQr: (account_id: string) =>
    client.post('/publish/login/qr', { account_id }) as Promise<{
      claim_token: string;
      expires_in: number;
      qr_key: string;
      account_id: string;
      operator_id: string | null;
      message: string;
    }>,

  claimLoginQr: (token: string) =>
    client.get(`/publish/login/qr/claim/${token}`) as Promise<{
      qr_url: string;
      account_id: string;
      operator_id: string | null;
      expires_in: number;
    }>,

  loginScanCallback: (payload: {
    account_id: string;
    operator_id?: string;
    scanner_name?: string;
    result?: string;
    message?: string;
  }) => client.post('/publish/login/scan/callback', payload) as Promise<{
    account_id: string;
    state: string;
  }>,

  getLoginStatus: (account_id: string) =>
    client.get(`/publish/login/status/${account_id}`) as Promise<Record<string, unknown>>,

  loginHeartbeat: (account_id: string) =>
    client.post(`/publish/login/heartbeat/${account_id}`) as Promise<{
      account_id: string;
      status: string;
    }>,

  // ── 多运营者验证向导（引导完成整套验证流程） ──
  getVerificationStatus: () =>
    client.get('/publish/multi-operator/verification') as Promise<MultiOpVerification>,

  setMultiOperatorFlag: (enabled: boolean) =>
    client.post('/publish/multi-operator/verification/flag', { enabled }) as Promise<{
      flag_on: boolean;
      message: string;
    }>,
};
