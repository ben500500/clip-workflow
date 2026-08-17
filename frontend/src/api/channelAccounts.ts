import client from './client';
import type { ChannelAccount, ChannelAccountInput, ChannelOperator, ChannelOperatorInput } from '../types';

export const channelAccountsApi = {
  // ── 台账 CRUD ──
  list: (params?: { verify_type?: string; enabled?: boolean }) =>
    client.get('/channel-accounts', { params }) as Promise<ChannelAccount[]>,

  get: (id: string) => client.get(`/channel-accounts/${id}`) as Promise<ChannelAccount>,

  create: (data: ChannelAccountInput) =>
    client.post('/channel-accounts', data) as Promise<ChannelAccount>,

  update: (id: string, data: Partial<ChannelAccountInput>) =>
    client.put(`/channel-accounts/${id}`, data) as Promise<ChannelAccount>,

  remove: (id: string) => client.delete(`/channel-accounts/${id}`) as Promise<void>,

  // ── 运营者子资源 ──
  createOperator: (accountId: string, data: ChannelOperatorInput) =>
    client.post(`/channel-accounts/${accountId}/operators`, data) as Promise<ChannelOperator>,

  updateOperator: (accountId: string, opId: string, data: Partial<ChannelOperatorInput>) =>
    client.put(`/channel-accounts/${accountId}/operators/${opId}`, data) as Promise<ChannelOperator>,

  deleteOperator: (accountId: string, opId: string) =>
    client.delete(`/channel-accounts/${accountId}/operators/${opId}`) as Promise<void>,
};
