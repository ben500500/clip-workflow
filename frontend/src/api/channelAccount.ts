import client from './client';
import type { ChannelAccount, ChannelAccountInput } from '../types';

export const channelAccountApi = {
  // 台账列表（可按实名类型 / 合作模式 / 关联账号筛选）
  getChannelAccounts: (params?: {
    verify_type?: string;
    cooperation_mode?: string;
    video_account_id?: string;
  }) => client.get('/channel-accounts', { params }) as Promise<ChannelAccount[]>,

  getChannelAccount: (id: string) => client.get(`/channel-accounts/${id}`) as Promise<ChannelAccount>,

  createChannelAccount: (data: ChannelAccountInput) =>
    client.post('/channel-accounts', data) as Promise<ChannelAccount>,

  updateChannelAccount: (id: string, data: Partial<ChannelAccountInput>) =>
    client.put(`/channel-accounts/${id}`, data) as Promise<ChannelAccount>,

  deleteChannelAccount: (id: string) => client.delete(`/channel-accounts/${id}`) as Promise<void>,
};
