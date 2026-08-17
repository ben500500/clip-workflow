import client from './client';
import type { ChannelAccount, ChannelOperator } from '../types';

export interface ChannelAccountInput {
  channel_name?: string;            // 缺省由账号库自动带出
  wechat_id?: string;               // 缺省由账号库自动带出
  verify_type?: string;          // personal / enterprise
  verify_name?: string;
  register_date?: string;        // YYYY-MM-DD
  cooperation_modes?: string[];  // IAA / IAP
  coop_company?: string;
  video_account_id: string;      // 方向1：必填，以账号库为主数据
  remark?: string;
  enabled?: boolean;
}

export interface ChannelAccountFromVideoAccountInput {
  video_account_id: string;
  verify_type?: string;
  verify_name?: string;
  register_date?: string;
  cooperation_modes?: string[];
  coop_company?: string;
  remark?: string;
  enabled?: boolean;
}

export interface OperatorInput {
  operator_user_id?: string;     // 现有用户
  operator_name?: string;        // 外部手填姓名
  operator_phone?: string;       // 外部手填电话
}

export const channelAccountApi = {
  // 台账 CRUD
  list: (params?: { keyword?: string; enabled?: boolean }) =>
    client.get('/channel-accounts', { params }) as Promise<ChannelAccount[]>,
  get: (id: string) =>
    client.get(`/channel-accounts/${id}`) as Promise<ChannelAccount>,
  create: (data: ChannelAccountInput) =>
    client.post('/channel-accounts', data) as Promise<ChannelAccount>,
  // 从账号库一键登记台账（自动带出名称/微信号，号主自动成为首个运营者）
  createFromVideoAccount: (data: ChannelAccountFromVideoAccountInput) =>
    client.post('/channel-accounts/from-video-account', data) as Promise<ChannelAccount>,
  update: (id: string, data: Partial<ChannelAccountInput>) =>
    client.put(`/channel-accounts/${id}`, data) as Promise<ChannelAccount>,
  remove: (id: string) =>
    client.delete(`/channel-accounts/${id}`) as Promise<void>,

  // 运营者管理
  addOperator: (accountId: string, data: OperatorInput) =>
    client.post(`/channel-accounts/${accountId}/operators`, data) as Promise<ChannelOperator>,
  updateOperator: (accountId: string, opId: string, data: OperatorInput) =>
    client.put(`/channel-accounts/${accountId}/operators/${opId}`, data) as Promise<ChannelOperator>,
  removeOperator: (accountId: string, opId: string) =>
    client.delete(`/channel-accounts/${accountId}/operators/${opId}`) as Promise<void>,
};
