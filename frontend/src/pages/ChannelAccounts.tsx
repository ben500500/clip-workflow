import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Modal, Form, Input,
  Select, DatePicker, Switch, Popconfirm, Tooltip,
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, TeamOutlined,
  ReloadOutlined, LinkOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { channelAccountsApi } from '../api/channelAccounts';
import { publishApi } from '../api/publish';
import type { ChannelAccount, ChannelAccountInput, ChannelOperator, VideoAccount } from '../types';
import { formatDateTime } from '../utils/format';

const { Title } = Typography;
const { TextArea } = Input;

const VERIFY_TYPE_LABELS: Record<string, string> = {
  personal: '个人号',
  enterprise: '企业号',
};

const COOP_MODE_LABELS: Record<string, string> = {
  IAA: 'IAA（广告变现）',
  IAP: 'IAP（内购付费）',
};

const ChannelAccounts: React.FC = () => {
  const [accounts, setAccounts] = useState<ChannelAccount[]>([]);
  const [videoAccounts, setVideoAccounts] = useState<VideoAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ChannelAccount | null>(null);
  const [form] = Form.useForm();

  // 运营者弹窗
  const [opModalOpen, setOpModalOpen] = useState(false);
  const [opAccount, setOpAccount] = useState<ChannelAccount | null>(null);
  const [opEditing, setOpEditing] = useState<ChannelOperator | null>(null);
  const [opForm] = Form.useForm();

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await channelAccountsApi.list();
      setAccounts(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载台账失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchVideoAccounts = useCallback(async () => {
    try {
      const data = await publishApi.getVideoAccounts();
      // 发布通道账号库仅取「视频号」平台，作为关联下拉回填
      setVideoAccounts(data.filter((a) => a.platform === 'wechat_channel'));
    } catch {
      setVideoAccounts([]);
    }
  }, []);

  useEffect(() => {
    fetchAccounts();
    fetchVideoAccounts();
  }, [fetchAccounts, fetchVideoAccounts]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ enabled: true, cooperation_modes: [] });
    setModalOpen(true);
  };

  const openEdit = (acc: ChannelAccount) => {
    setEditing(acc);
    form.resetFields();
    form.setFieldsValue({
      channel_name: acc.channel_name,
      wechat_id: acc.wechat_id,
      verify_type: acc.verify_type,
      verify_name: acc.verify_name,
      register_date: acc.register_date ? dayjs(acc.register_date) : undefined,
      cooperation_modes: acc.cooperation_modes || [],
      coop_company: acc.coop_company,
      video_account_id: acc.video_account_id,
      remark: acc.remark,
      enabled: acc.enabled,
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    const payload: ChannelAccountInput = {
      channel_name: values.channel_name,
      wechat_id: values.wechat_id ?? null,
      verify_type: values.verify_type ?? null,
      verify_name: values.verify_name ?? null,
      register_date: values.register_date
        ? (values.register_date as Dayjs).format('YYYY-MM-DD')
        : null,
      cooperation_modes: values.cooperation_modes || [],
      coop_company: values.coop_company ?? null,
      video_account_id: values.video_account_id ?? null,
      remark: values.remark ?? null,
      enabled: values.enabled ?? true,
    };
    try {
      if (editing) {
        await channelAccountsApi.update(editing.id, payload);
        message.success('台账已更新');
      } else {
        await channelAccountsApi.create(payload);
        message.success('台账已创建');
      }
      setModalOpen(false);
      fetchAccounts();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleDelete = async (acc: ChannelAccount) => {
    try {
      await channelAccountsApi.remove(acc.id);
      message.success('台账已删除');
      fetchAccounts();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  // ── 运营者管理 ──
  const openOperators = (acc: ChannelAccount) => {
    setOpAccount(acc);
    setOpEditing(null);
    opForm.resetFields();
    setOpModalOpen(true);
  };

  const openOperatorEdit = (op: ChannelOperator) => {
    setOpEditing(op);
    opForm.setFieldsValue({
      operator_user_id: op.operator_user_id,
      operator_name: op.operator_name,
      operator_phone: op.operator_phone,
    });
  };

  const handleOperatorSubmit = async () => {
    if (!opAccount) return;
    const values = await opForm.validateFields();
    if (!values.operator_user_id && !values.operator_name) {
      message.warning('运营者系统账号与姓名至少填写一个');
      return;
    }
    try {
      if (opEditing) {
        await channelAccountsApi.updateOperator(opAccount.id, opEditing.id, values);
        message.success('运营者已更新');
      } else {
        await channelAccountsApi.createOperator(opAccount.id, values);
        message.success('运营者已添加');
      }
      fetchAccounts();
      // 刷新当前台账展示
      const refreshed = await channelAccountsApi.get(opAccount.id);
      setOpAccount(refreshed);
      setOpEditing(null);
      opForm.resetFields();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleOperatorDelete = async (op: ChannelOperator) => {
    if (!opAccount) return;
    try {
      await channelAccountsApi.deleteOperator(opAccount.id, op.id);
      message.success('运营者已移除');
      const refreshed = await channelAccountsApi.get(opAccount.id);
      setOpAccount(refreshed);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  const videoAccountMap = new Map(videoAccounts.map((v) => [v.id, v]));

  const operatorColumns = [
    {
      title: '姓名',
      dataIndex: 'operator_name',
      render: (v: string | null, r: ChannelOperator) =>
        v || (r.operator_user_id ? `用户 #${r.operator_user_id.slice(0, 8)}` : '—'),
    },
    { title: '联系电话', dataIndex: 'operator_phone', render: (v: string | null) => v || '—' },
    {
      title: '系统账号',
      dataIndex: 'operator_user_id',
      render: (v: string | null) => (v ? <Tag color="blue">已绑定</Tag> : <Tag>外部人员</Tag>),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, r: ChannelOperator) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openOperatorEdit(r)}>
            编辑
          </Button>
          <Popconfirm title="确认移除该运营者？" onConfirm={() => handleOperatorDelete(r)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              移除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const columns = [
    {
      title: '视频号名称',
      dataIndex: 'channel_name',
      render: (v: string) => <strong>{v}</strong>,
    },
    {
      title: '微信号',
      dataIndex: 'wechat_id',
      render: (v: string | null) => v || '—',
    },
    {
      title: '认证类型',
      dataIndex: 'verify_type',
      render: (v: string | null) => (v ? <Tag>{VERIFY_TYPE_LABELS[v] || v}</Tag> : '—'),
    },
    {
      title: '实名人',
      dataIndex: 'verify_name',
      render: (v: string | null) => v || '—',
    },
    {
      title: '合作模式',
      dataIndex: 'cooperation_modes',
      render: (v: string[] | null) =>
        v && v.length ? (
          <Space size={4}>
            {v.map((m) => (
              <Tag key={m} color="geekblue">
                {COOP_MODE_LABELS[m] || m}
              </Tag>
            ))}
          </Space>
        ) : (
          '—'
        ),
    },
    {
      title: '合作公司',
      dataIndex: 'coop_company',
      render: (v: string | null) => v || '—',
    },
    {
      title: '关联通道账号',
      dataIndex: 'video_account_id',
      render: (v: string | null) =>
        v && videoAccountMap.has(v) ? (
          <Tooltip title="已关联发布通道账号">
            <Tag color="green">
              <LinkOutlined /> {videoAccountMap.get(v)?.account_name}
            </Tag>
          </Tooltip>
        ) : (
          <Tag>未关联</Tag>
        ),
    },
    {
      title: '运营者',
      dataIndex: 'operators',
      render: (_: ChannelOperator[] | undefined, r: ChannelAccount) => (
        <Button
          type="link"
          size="small"
          icon={<TeamOutlined />}
          onClick={() => openOperators(r)}
        >
          {(r.operators || []).length} 人
        </Button>
      ),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      render: (v: boolean) => (v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      render: (v: string) => formatDateTime(v),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, r: ChannelAccount) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Button type="link" size="small" icon={<TeamOutlined />} onClick={() => openOperators(r)}>
            运营者
          </Button>
          <Popconfirm title="确认删除该台账？" onConfirm={() => handleDelete(r)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}>
          <Title level={4} style={{ margin: 0 }}>
            视频号台账
          </Title>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchAccounts}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新建台账
            </Button>
          </Space>
        </Space>

        <Table<ChannelAccount>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={accounts}
          pagination={{ pageSize: 10, showSizeChanger: true }}
        />
      </Card>

      {/* 台账 新建/编辑 */}
      <Modal
        title={editing ? '编辑台账' : '新建台账'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ enabled: true, cooperation_modes: [] }}>
          <Form.Item name="channel_name" label="视频号名称" rules={[{ required: true, message: '请输入视频号名称' }]}>
            <Input maxLength={100} placeholder="如：主号-剧集A" />
          </Form.Item>
          <Form.Item name="wechat_id" label="微信号">
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="verify_type" label="认证类型">
            <Select
              allowClear
              placeholder="选择认证类型"
              options={[
                { value: 'personal', label: '个人号' },
                { value: 'enterprise', label: '企业号' },
              ]}
            />
          </Form.Item>
          <Form.Item name="verify_name" label="实名人">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="register_date" label="注册日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="cooperation_modes" label="合作模式">
            <Select
              mode="multiple"
              allowClear
              placeholder="可多选"
              options={[
                { value: 'IAA', label: 'IAA（广告变现）' },
                { value: 'IAP', label: 'IAP（内购付费）' },
              ]}
            />
          </Form.Item>
          <Form.Item name="coop_company" label="合作公司">
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="video_account_id" label="关联发布通道账号（先登记后关联）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="可选：从发布通道账号库回填"
              options={videoAccounts.map((v) => ({ value: v.id, label: v.account_name }))}
            />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 运营者管理 */}
      <Modal
        title={opAccount ? `运营者管理：${opAccount.channel_name}` : '运营者管理'}
        open={opModalOpen}
        onCancel={() => setOpModalOpen(false)}
        footer={null}
        width={680}
        destroyOnClose
      >
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setOpEditing(null); opForm.resetFields(); }}>
            新增运营者
          </Button>
        </Space>
        <Form form={opForm} layout="inline" style={{ marginBottom: 16, rowGap: 12 }}>
          <Form.Item name="operator_name" label="姓名">
            <Input placeholder="外部人员姓名" style={{ width: 150 }} />
          </Form.Item>
          <Form.Item name="operator_phone" label="电话">
            <Input placeholder="联系兜底电话" style={{ width: 150 }} />
          </Form.Item>
          <Form.Item name="operator_user_id" label="系统账号ID">
            <Input placeholder="有账号则填用户ID" style={{ width: 200 }} />
          </Form.Item>
          <Button type="primary" onClick={handleOperatorSubmit}>
            {opEditing ? '保存' : '添加'}
          </Button>
        </Form>
        <Table<ChannelOperator>
          rowKey="id"
          size="small"
          columns={operatorColumns}
          dataSource={opAccount?.operators || []}
          pagination={false}
        />
      </Modal>
    </div>
  );
};

export default ChannelAccounts;
