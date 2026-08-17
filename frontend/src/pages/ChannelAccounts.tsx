import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Form, Input, Button, Select, Switch, Space, Table, Tag, Modal, message,
  Typography, Popconfirm, Divider, Tooltip, DatePicker, List,
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, TeamOutlined,
  UserAddOutlined, BarChartOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useNavigate } from 'react-router-dom';
import { channelAccountApi, ChannelAccountInput, OperatorInput } from '../api/channelAccounts';
import { publishApi } from '../api/publish';
import { authApi } from '../api/auth';
import type { ChannelAccount, ChannelOperator, VideoAccount, User } from '../types';

const { Text } = Typography;

// 实名类型
const VERIFY_TYPES = [
  { value: 'personal', label: '个人' },
  { value: 'enterprise', label: '企业' },
];

// 合作模式（多选 Tag）
const COOP_MODES = [
  { value: 'IAA', label: 'IAA' },
  { value: 'IAP', label: 'IAP' },
];

const COOP_MODE_COLOR: Record<string, string> = {
  IAA: 'blue',
  IAP: 'purple',
};

interface OperatorForm {
  operator_user_id?: string;
  operator_name?: string;
  operator_phone?: string;
}

const ChannelAccounts: React.FC = () => {
  const navigate = useNavigate();
  const [data, setData] = useState<ChannelAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [videoAccounts, setVideoAccounts] = useState<VideoAccount[]>([]);
  const [users, setUsers] = useState<User[]>([]);

  // 台账表单
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ChannelAccount | null>(null);
  const [form] = Form.useForm();

  // 运营者弹窗
  const [opModalOpen, setOpModalOpen] = useState(false);
  const [currentAccount, setCurrentAccount] = useState<ChannelAccount | null>(null);
  const [opForm] = Form.useForm();
  const [operatorList, setOperatorList] = useState<ChannelOperator[]>([]);

  const fetchData = useCallback(async (kw?: string) => {
    setLoading(true);
    try {
      const list = await channelAccountApi.list({ keyword: kw });
      setData(list);
    } catch (e) {
      message.error((e as Error).message || '加载视频号列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // 加载关联下拉数据（发布账号库 + 系统用户）
  useEffect(() => {
    publishApi.getVideoAccounts().then(setVideoAccounts).catch(() => setVideoAccounts([]));
    authApi.getUsers().then(setUsers).catch(() => setUsers([]));
  }, []);

  // ── 新增/编辑 ──
  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (acc: ChannelAccount) => {
    setEditing(acc);
    form.setFieldsValue({
      channel_name: acc.channel_name,
      wechat_id: acc.wechat_id || undefined,
      verify_type: acc.verify_type || undefined,
      verify_name: acc.verify_name || undefined,
      register_date: acc.register_date ? dayjs(acc.register_date) : undefined,
      cooperation_modes: acc.cooperation_modes || [],
      coop_company: acc.coop_company || undefined,
      video_account_id: acc.video_account_id || undefined,
      remark: acc.remark || undefined,
      enabled: acc.enabled,
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      const payload: ChannelAccountInput = {
        ...values,
        register_date: values.register_date
          ? values.register_date.format('YYYY-MM-DD')
          : undefined,
      };
      if (editing) {
        await channelAccountApi.update(editing.id, payload);
        message.success('视频号列表已更新');
      } else {
        await channelAccountApi.create(payload);
        message.success('视频号列表已创建');
      }
      setModalOpen(false);
      fetchData(keyword);
    } catch (e) {
      if ((e as Error).message) message.error((e as Error).message);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await channelAccountApi.remove(id);
      message.success('已删除');
      fetchData(keyword);
    } catch (e) {
      message.error((e as Error).message || '删除失败');
    }
  };

  // ── 运营者管理 ──
  const openOperator = (acc: ChannelAccount) => {
    setCurrentAccount(acc);
    setOperatorList(acc.operators || []);
    opForm.resetFields();
    setOpModalOpen(true);
  };

  const handleAddOperator = async () => {
    if (!currentAccount) return;
    try {
      const values = await opForm.validateFields();
      const payload: OperatorInput = {
        operator_user_id: values.operator_user_id,
        operator_name: values.operator_name,
        operator_phone: values.operator_phone,
      };
      // 双轨校验兜底
      if (!payload.operator_user_id && !payload.operator_name) {
        message.error('请从系统选择用户或填写外部姓名（至少填一个）');
        return;
      }
      const op = await channelAccountApi.addOperator(currentAccount.id, payload);
      setOperatorList((prev) => [...prev, op]);
      opForm.resetFields();
      message.success('运营者已添加');
      // 刷新主列表以同步
      fetchData(keyword);
    } catch (e) {
      const msg = (e as Error).message;
      if (msg) message.error(msg);
    }
  };

  const handleRemoveOperator = async (op: ChannelOperator) => {
    if (!currentAccount) return;
    try {
      await channelAccountApi.removeOperator(currentAccount.id, op.id);
      setOperatorList((prev) => prev.filter((x) => x.id !== op.id));
      message.success('运营者已移除');
      fetchData(keyword);
    } catch (e) {
      message.error((e as Error).message || '移除失败');
    }
  };

  // ── 表格列 ──
  const columns: ColumnsType<ChannelAccount> = [
    {
      title: '视频号名称',
      dataIndex: 'channel_name',
      width: 160,
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '微信号',
      dataIndex: 'wechat_id',
      width: 150,
      render: (v: string) => v || '-',
    },
    {
      title: '实名类型',
      dataIndex: 'verify_type',
      width: 90,
      render: (v: string) =>
        v ? <Tag color={v === 'enterprise' ? 'orange' : 'green'}>{v === 'enterprise' ? '企业' : '个人'}</Tag> : '-',
    },
    {
      title: '实名人',
      dataIndex: 'verify_name',
      width: 100,
      render: (v: string) => v || '-',
    },
    {
      title: '注册日期',
      dataIndex: 'register_date',
      width: 110,
      render: (v: string) => v || '-',
    },
    {
      title: '合作模式',
      dataIndex: 'cooperation_modes',
      width: 120,
      render: (modes: string[]) =>
        modes && modes.length ? (
          <Space size={4}>
            {modes.map((m) => (
              <Tag key={m} color={COOP_MODE_COLOR[m] || 'default'}>
                {m}
              </Tag>
            ))}
          </Space>
        ) : (
          '-'
        ),
    },
    {
      title: '合作公司',
      dataIndex: 'coop_company',
      width: 140,
      ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: '运营者',
      key: 'operators',
      width: 120,
      render: (_, record) => {
        const ops = record.operators || [];
        return ops.length ? (
          <Tooltip
            title={ops
              .map((o) => o.operator_name || o.operator_user_id || '')
              .join('、')}
          >
            <Tag icon={<TeamOutlined />} color="cyan">
              {ops.length} 人
            </Tag>
          </Tooltip>
        ) : (
          '-'
        );
      },
    },
    {
      title: '关联发布账号',
      dataIndex: 'video_account_id',
      width: 120,
      render: (v: string) => {
        if (!v) return <Text type="secondary">未关联</Text>;
        const acc = videoAccounts.find((a) => a.id === v);
        return acc ? <Tag color="geekblue">{acc.account_name}</Tag> : <Tag>已关联</Tag>;
      },
    },
    {
      title: '累计播放',
      key: 'report_play_count',
      width: 110,
      align: 'right' as const,
      render: (_, record) =>
        record.report_play_count != null ? record.report_play_count.toLocaleString() : '-',
    },
    {
      title: '归因收益',
      key: 'report_attributed_revenue',
      width: 110,
      align: 'right' as const,
      render: (_, record) =>
        record.report_attributed_revenue != null
          ? `¥${Number(record.report_attributed_revenue).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
          : '-',
    },
    {
      title: '广告收益',
      key: 'report_ad_revenue',
      width: 110,
      align: 'right' as const,
      render: (_, record) =>
        record.report_ad_revenue != null
          ? `¥${Number(record.report_ad_revenue).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
          : '-',
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 70,
      render: (v: boolean) => (v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '操作',
      key: 'action',
      width: 260,
      render: (_, record) => (
        <Space split={<Divider type="vertical" />}>
          <Button type="link" size="small" icon={<BarChartOutlined />} onClick={() => navigate('/analytics/shortdrama')}>
            报表
          </Button>
          <Button type="link" size="small" icon={<TeamOutlined />} onClick={() => openOperator(record)}>
            运营者
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除该视频号列表？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="视频号列表"
      extra={
        <Space>
          <Input
            placeholder="搜索名称/微信号"
            prefix={<SearchOutlined />}
            allowClear
            style={{ width: 220 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={() => fetchData(keyword)}
          />
          <Button onClick={() => fetchData(keyword)}>查询</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增
          </Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        scroll={{ x: 1400 }}
      />

      {/* 新增/编辑 */}
      <Modal
        title={editing ? '编辑视频号列表' : '新增视频号列表'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ enabled: true }}>
          <Form.Item
            name="channel_name"
            label="视频号名称"
            rules={[{ required: true, message: '请输入视频号名称' }]}
          >
            <Input placeholder="如：主号-剧集A" />
          </Form.Item>
          <Form.Item name="wechat_id" label="微信号">
            <Input placeholder="选填" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size="large">
            <Form.Item name="verify_type" label="实名类型">
              <Select
                placeholder="个人/企业"
                options={VERIFY_TYPES}
                style={{ width: 160 }}
                allowClear
              />
            </Form.Item>
            <Form.Item name="verify_name" label="实名人">
              <Input placeholder="选填" style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="register_date" label="注册日期">
              <DatePicker style={{ width: 150 }} />
            </Form.Item>
          </Space>
          <Form.Item name="cooperation_modes" label="合作模式（可多选，IAA/IAP 可共存）">
            <Select
              mode="multiple"
              placeholder="选择合作模式"
              options={COOP_MODES}
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item name="coop_company" label="合作公司">
            <Input placeholder="选填" />
          </Form.Item>
          <Form.Item
            name="video_account_id"
            label="关联发布账号（可先登记后关联）"
            extra="从现有发布账号库选择，发布通道配置"
          >
            <Select
              placeholder="选填，可稍后关联"
              allowClear
              showSearch
              optionFilterProp="label"
              options={videoAccounts.map((a) => ({
                value: a.id,
                label: `${a.account_name} (${a.platform})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} placeholder="选填" />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 运营者管理 */}
      <Modal
        title={`运营者管理 - ${currentAccount?.channel_name || ''}`}
        open={opModalOpen}
        onCancel={() => setOpModalOpen(false)}
        footer={null}
        width={520}
      >
        <div style={{ marginBottom: 16 }}>
          <Form form={opForm} layout="vertical">
            <Space style={{ display: 'flex' }} align="start">
              <Form.Item name="operator_user_id" label="从系统选择用户">
                <Select
                  placeholder="现有系统用户"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  style={{ width: 220 }}
                  options={users
                    .filter((u) => u.is_active)
                    .map((u) => ({
                      value: u.id,
                      label: u.display_name || u.username,
                    }))}
                />
              </Form.Item>
              <Form.Item name="operator_name" label="或手填外部姓名">
                <Input placeholder="外部人员姓名" style={{ width: 200 }} />
              </Form.Item>
            </Space>
            <Form.Item name="operator_phone" label="外部电话（选填）">
              <Input placeholder="手填外部人员电话" style={{ width: 220 }} />
            </Form.Item>
            <Button type="primary" icon={<UserAddOutlined />} onClick={handleAddOperator}>
              添加运营者
            </Button>
          </Form>
        </div>
        <Divider style={{ margin: '8px 0' }} />
        <List
          dataSource={operatorList}
          locale={{ emptyText: '暂无运营者' }}
          renderItem={(op) => (
            <List.Item
              actions={[
                <Popconfirm
                  key="del"
                  title="移除该运营者？"
                  onConfirm={() => handleRemoveOperator(op)}
                >
                  <Button type="link" danger size="small">
                    移除
                  </Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  op.operator_name ||
                  users.find((u) => u.id === op.operator_user_id)?.display_name ||
                  users.find((u) => u.id === op.operator_user_id)?.username ||
                  '未命名运营者'
                }
                description={
                  op.operator_user_id
                    ? `系统用户`
                    : [op.operator_phone, '外部人员'].filter(Boolean).join(' · ')
                }
              />
            </List.Item>
          )}
        />
      </Modal>
    </Card>
  );
};

export default ChannelAccounts;
