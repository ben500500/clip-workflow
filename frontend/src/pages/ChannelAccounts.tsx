import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Modal, Form, Input, Select, DatePicker, InputNumber, Tooltip, Switch, Popconfirm,
} from 'antd';
import { ReloadOutlined, PlusOutlined, EditOutlined, DeleteOutlined, TeamOutlined, LinkOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { channelAccountApi } from '../api/channelAccount';
import { publishApi } from '../api/publish';
import { authApi } from '../api/auth';
import type { ChannelAccount, ChannelAccountInput, VideoAccount } from '../types';
import { formatDateTime } from '../utils/format';

const { Title, Text } = Typography;

const VERIFY_TYPE_LABELS: Record<string, string> = {
  personal: '个人',
  enterprise: '企业',
};

const COOP_MODE_LABELS: Record<string, string> = {
  IAA: 'IAA',
  IAP: 'IAP',
};

// 运营者：从系统用户选 或 手填外部姓名
const OperatorSelect: React.FC<{
  value?: { operator_id?: string | null; operator_name?: string | null }[];
  onChange?: (v: { operator_id?: string | null; operator_name?: string | null }[]) => void;
}> = ({ value = [], onChange }) => {
  const [users, setUsers] = useState<{ id: string; display_name: string | null; username: string }[]>([]);
  useEffect(() => {
    // 从用户管理 API 拉取系统用户，用于运营者下拉
    authApi.getUsers().then((rows: any[]) => setUsers(rows || [])).catch(() => {
      /* 静默：无权限时退回手填 */
    });
  }, []);

  const handleAdd = () => {
    onChange?.([...value, {}]);
  };
  const handleChange = (idx: number, patch: Partial<{ operator_id: string; operator_name: string }>) => {
    const next = value.map((op, i) => (i === idx ? { ...op, ...patch } : op));
    onChange?.(next);
  };
  const handleRemove = (idx: number) => {
    onChange?.(value.filter((_, i) => i !== idx));
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {value.map((op, idx) => (
        <Space key={idx} style={{ width: '100%' }} align="baseline">
          <Select
            allowClear
            placeholder="从系统用户选择（可选）"
            style={{ width: 220 }}
            value={op.operator_id || undefined}
            onChange={(v) => handleChange(idx, { operator_id: v || '', operator_name: '' })}
            options={users.map((u) => ({
              value: u.id,
              label: u.display_name || u.username,
            }))}
          />
          <Input
            placeholder="外部人员姓名（无系统账号时手填）"
            style={{ width: 200 }}
            value={op.operator_name || ''}
            onChange={(e) => handleChange(idx, { operator_name: e.target.value })}
          />
          <Button type="text" danger icon={<DeleteOutlined />} onClick={() => handleRemove(idx)} />
        </Space>
      ))}
      <Button type="dashed" icon={<PlusOutlined />} onClick={handleAdd} block>
        添加运营者
      </Button>
    </Space>
  );
};

const ChannelAccounts: React.FC = () => {
  const [channels, setChannels] = useState<ChannelAccount[]>([]);
  const [videoAccounts, setVideoAccounts] = useState<VideoAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ChannelAccount | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const [verifyFilter, setVerifyFilter] = useState<string | undefined>();
  const [coopFilter, setCoopFilter] = useState<string | undefined>();

  const fetchChannels = useCallback((verify?: string, coop?: string) => {
    setLoading(true);
    channelAccountApi.getChannelAccounts({ verify_type: verify, cooperation_mode: coop })
      .then(setChannels)
      .catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const fetchVideoAccounts = useCallback(() => {
    publishApi.getVideoAccounts({ platform: 'wechat_channel' })
      .then(setVideoAccounts)
      .catch(() => setVideoAccounts([]));
  }, []);

  useEffect(() => { fetchChannels(); fetchVideoAccounts(); }, [fetchChannels, fetchVideoAccounts]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ enabled: true, operators: [] });
    setModalOpen(true);
  };

  const openEdit = (row: ChannelAccount) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({
      ...row,
      register_date: row.register_date ? dayjs(row.register_date) : undefined,
      operators: row.operators?.length ? row.operators.map((o) => ({ operator_id: o.operator_id, operator_name: o.operator_name })) : [],
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const payload: ChannelAccountInput = {
        channel_name: values.channel_name,
        wechat_id: values.wechat_id,
        verify_type: values.verify_type,
        verify_name: values.verify_name,
        register_date: values.register_date ? values.register_date.format('YYYY-MM-DD') : null,
        cooperation_mode: values.cooperation_mode,
        coop_company: values.coop_company,
        video_account_id: values.video_account_id || null,
        remark: values.remark,
        enabled: values.enabled !== false,
        operators: (values.operators || [])
          .filter((op: any) => op.operator_id || op.operator_name)
          .map((op: any) => ({ operator_id: op.operator_id || null, operator_name: op.operator_name || null })),
      };
      if (editing) {
        await channelAccountApi.updateChannelAccount(editing.id, payload);
        message.success('台账已更新');
      } else {
        await channelAccountApi.createChannelAccount(payload);
        message.success('台账已创建');
      }
      setModalOpen(false);
      fetchChannels(verifyFilter, coopFilter);
    } catch (err: unknown) {
      if (err instanceof Error) message.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await channelAccountApi.deleteChannelAccount(id);
      message.success('台账已删除');
      fetchChannels(verifyFilter, coopFilter);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  const columns = [
    { title: '视频号名称', dataIndex: 'channel_name', key: 'channel_name', width: 160, ellipsis: true },
    { title: '微信号', dataIndex: 'wechat_id', key: 'wechat_id', width: 150, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '实名类型', dataIndex: 'verify_type', key: 'verify_type', width: 90,
      render: (v: string | null) => v ? <Tag color={v === 'enterprise' ? 'blue' : 'green'}>{VERIFY_TYPE_LABELS[v] || v}</Tag> : '-',
    },
    { title: '实名人', dataIndex: 'verify_name', key: 'verify_name', width: 130, ellipsis: true, render: (v: string | null) => v || '-' },
    { title: '注册日期', dataIndex: 'register_date', key: 'register_date', width: 110, render: (v: string | null) => v || '-' },
    {
      title: '合作模式', dataIndex: 'cooperation_mode', key: 'cooperation_mode', width: 90,
      render: (v: string | null) => v ? <Tag color="orange">{COOP_MODE_LABELS[v] || v}</Tag> : '-',
    },
    { title: '合作公司', dataIndex: 'coop_company', key: 'coop_company', width: 150, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '运营者', dataIndex: 'operators', key: 'operators', width: 160,
      render: (ops: ChannelAccount['operators']) => ops?.length
        ? ops.map((o, i) => <Tag key={i} icon={<TeamOutlined />} style={{ marginBottom: 2 }}>{o.operator_name || '系统用户'}</Tag>)
        : <Text type="secondary">-</Text>,
    },
    {
      title: '关联账号', dataIndex: 'video_account_name', key: 'video_account_name', width: 150, ellipsis: true,
      render: (v: string | null, row: ChannelAccount) => v
        ? <Tag icon={<LinkOutlined />} color="purple">{v}</Tag>
        : <Text type="secondary">-</Text>,
    },
    {
      title: '状态', dataIndex: 'enabled', key: 'enabled', width: 80,
      render: (v: boolean) => v ? <Tag color="success">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 160, render: (v: string) => formatDateTime(v) },
    {
      title: '操作', key: 'action', width: 120, fixed: 'right' as const,
      render: (_: unknown, row: ChannelAccount) => (
        <Space>
          <Tooltip title="编辑"><Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} /></Tooltip>
          <Popconfirm title="确认删除该台账？" onConfirm={() => handleDelete(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={
        <Space>
          <Title level={4} style={{ margin: 0 }}>视频号列表</Title>
          <Text type="secondary">登记视频号工商/合作信息，可关联发布账号</Text>
        </Space>
      }
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => fetchChannels(verifyFilter, coopFilter)}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增视频号</Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          allowClear placeholder="实名类型" style={{ width: 120 }}
          value={verifyFilter} onChange={(v) => { setVerifyFilter(v); fetchChannels(v, coopFilter); }}
          options={[{ value: 'personal', label: '个人' }, { value: 'enterprise', label: '企业' }]}
        />
        <Select
          allowClear placeholder="合作模式" style={{ width: 120 }}
          value={coopFilter} onChange={(v) => { setCoopFilter(v); fetchChannels(verifyFilter, v); }}
          options={[{ value: 'IAA', label: 'IAA' }, { value: 'IAP', label: 'IAP' }]}
        />
      </Space>

      <Table
        rowKey="id" loading={loading} dataSource={channels} columns={columns}
        scroll={{ x: 1600 }} pagination={{ pageSize: 20, showSizeChanger: true }}
      />

      <Modal
        title={editing ? '编辑视频号' : '新增视频号'}
        open={modalOpen} onOk={handleSave} onCancel={() => setModalOpen(false)}
        confirmLoading={saving} width={720} destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="channel_name" label="视频号名称" rules={[{ required: true, message: '请输入视频号名称' }]}>
            <Input placeholder="如：主号-剧集A" />
          </Form.Item>
          <Form.Item name="wechat_id" label="微信号"><Input placeholder="视频号绑定的微信" /></Form.Item>
          <Space style={{ width: '100%' }} size="large">
            <Form.Item name="verify_type" label="实名类型" style={{ width: 200 }}>
              <Select allowClear placeholder="选择" options={[
                { value: 'personal', label: '个人' },
                { value: 'enterprise', label: '企业' },
              ]} />
            </Form.Item>
            <Form.Item name="verify_name" label="实名人" style={{ flex: 1 }}>
              <Input placeholder="个人姓名 / 企业全称" />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size="large">
            <Form.Item name="register_date" label="注册日期">
              <DatePicker style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="cooperation_mode" label="合作模式" style={{ width: 200 }}>
              <Select allowClear placeholder="选择" options={[
                { value: 'IAA', label: 'IAA（广告变现）' },
                { value: 'IAP', label: 'IAP（内购变现）' },
              ]} />
            </Form.Item>
            <Form.Item name="coop_company" label="合作公司" style={{ flex: 1 }}>
              <Input placeholder="合作公司名称" />
            </Form.Item>
          </Space>
          <Form.Item name="video_account_id" label="关联发布账号（可选）" extra="从发布账号矩阵中选择，打通发布流程">
            <Select
              allowClear showSearch placeholder="选择发布账号"
              optionFilterProp="label"
              options={videoAccounts.map((a) => ({ value: a.id, label: a.account_name }))}
            />
          </Form.Item>
          <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="operators" label="运营者身份（可添加多人）">
            <OperatorSelect />
          </Form.Item>
          <Form.Item name="enabled" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" defaultChecked />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
};

export default ChannelAccounts;
