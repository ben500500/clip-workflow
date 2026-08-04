import React, { useEffect, useState } from 'react';
import {
  Card,
  Tabs,
  Table,
  Tag,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Switch,
  message,
  Typography,
  Popconfirm,
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  SendOutlined,
  CheckOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { publishApi } from '../api/publish';
import type {
  PublishTask,
  PublishProfile,
  PublishPlatform,
  PublishStatus,
} from '../types';

const { Title, Text } = Typography;
const { TextArea } = Input;

// ========== 常量映射 ==========

const platformLabels: Record<PublishPlatform, string> = {
  wechat_channels: '微信视频号',
  douyin: '抖音',
  kuaishou: '快手',
};

const platformColors: Record<PublishPlatform, string> = {
  wechat_channels: 'green',
  douyin: 'volcano',
  kuaishou: 'orange',
};

const statusLabels: Record<PublishStatus, string> = {
  pending: '待发布',
  uploading: '上传中',
  processing: '处理中',
  pending_confirm: '待确认',
  published: '已发布',
  failed: '失败',
};

const statusColors: Record<PublishStatus, string> = {
  pending: 'blue',
  uploading: 'orange',
  processing: 'orange',
  pending_confirm: 'gold',
  published: 'green',
  failed: 'red',
};

// ========== Mock 数据 ==========

const mockTasks: PublishTask[] = [
  {
    id: '1',
    output_id: 'out-001',
    platform: 'wechat_channels',
    account_name: '短剧精选',
    status: 'published',
    title: '霸总逆袭第一集',
    description: '精彩短剧，不容错过',
    tags: ['短剧', '霸总', '逆袭'],
    link_attached: true,
    published_url: 'https://channels.weixin.qq.com/xxx',
    published_at: '2024-03-15T10:30:00Z',
    require_manual_confirm: false,
    created_at: '2024-03-15T09:00:00Z',
    updated_at: '2024-03-15T10:30:00Z',
  },
  {
    id: '2',
    output_id: 'out-002',
    platform: 'douyin',
    account_name: '热播剧场',
    status: 'pending_confirm',
    title: '甜蜜复仇第二集',
    description: '复仇之路正式开始',
    tags: ['短剧', '复仇', '甜蜜'],
    link_attached: true,
    require_manual_confirm: true,
    screenshot_key: 'screenshots/task2.png',
    created_at: '2024-03-15T11:00:00Z',
    updated_at: '2024-03-15T11:30:00Z',
  },
  {
    id: '3',
    output_id: 'out-003',
    platform: 'kuaishou',
    account_name: '快手短剧号',
    status: 'failed',
    title: '都市情缘第三集',
    description: '缘分天注定',
    tags: ['短剧', '都市', '情缘'],
    link_attached: false,
    error_message: '上传超时，请重试',
    require_manual_confirm: false,
    created_at: '2024-03-15T12:00:00Z',
    updated_at: '2024-03-15T12:30:00Z',
  },
  {
    id: '4',
    output_id: 'out-004',
    platform: 'wechat_channels',
    account_name: '短剧精选',
    status: 'uploading',
    title: '豪门恩怨第四集',
    description: '豪门深处的秘密',
    tags: ['短剧', '豪门', '恩怨'],
    link_attached: true,
    require_manual_confirm: false,
    created_at: '2024-03-15T13:00:00Z',
    updated_at: '2024-03-15T13:05:00Z',
  },
];

const mockProfiles: PublishProfile[] = [
  {
    id: 'p1',
    platform: 'wechat_channels',
    account_name: '短剧精选',
    chrome_debug_port: 9222,
    title_template: '{title} - 精彩短剧推荐',
    description_template: '{description} #短剧 #推荐',
    default_tags: ['短剧', '推荐'],
    mini_program_link: 'https://mp.weixin.qq.com/xxx',
    publish_mode: 'immediate',
    require_manual_confirm: true,
    min_interval_seconds: 300,
    max_daily_publish: 20,
    created_at: '2024-03-01T00:00:00Z',
  },
  {
    id: 'p2',
    platform: 'douyin',
    account_name: '热播剧场',
    chrome_debug_port: 9223,
    title_template: '{title}',
    description_template: '{description}',
    default_tags: ['短剧', '热播'],
    publish_mode: 'scheduled',
    require_manual_confirm: false,
    min_interval_seconds: 600,
    max_daily_publish: 10,
    created_at: '2024-03-05T00:00:00Z',
  },
];

// ========== 组件 ==========

const PublishManagement: React.FC = () => {
  const [activeTab, setActiveTab] = useState('tasks');
  const [tasks, setTasks] = useState<PublishTask[]>(mockTasks);
  const [profiles, setProfiles] = useState<PublishProfile[]>(mockProfiles);
  const [loading, setLoading] = useState(false);
  const [taskModalOpen, setTaskModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<PublishProfile | null>(null);
  const [taskForm] = Form.useForm();
  const [profileForm] = Form.useForm();

  // 加载数据（使用 mock）
  const fetchTasks = async () => {
    setLoading(true);
    try {
      // const res = await publishApi.getTasks();
      // setTasks(res.data.items);
      setTasks(mockTasks);
    } catch {
      message.error('获取发布任务列表失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchProfiles = async () => {
    try {
      // const res = await publishApi.getProfiles();
      // setProfiles(res.data);
      setProfiles(mockProfiles);
    } catch {
      message.error('获取发布配置失败');
    }
  };

  useEffect(() => {
    fetchTasks();
    fetchProfiles();
  }, []);

  // 确认发布
  const handleConfirmPublish = async (id: string) => {
    try {
      await publishApi.confirmTask(id);
      message.success('已确认发布');
      fetchTasks();
    } catch {
      message.success('已确认发布（Mock）');
      setTasks((prev) =>
        prev.map((t) => (t.id === id ? { ...t, status: 'published' as PublishStatus, published_at: new Date().toISOString() } : t))
      );
    }
  };

  // 创建发布任务
  const handleCreateTask = async () => {
    try {
      const values = await taskForm.validateFields();
      await publishApi.createTask(values);
      message.success('发布任务创建成功');
      setTaskModalOpen(false);
      taskForm.resetFields();
      fetchTasks();
    } catch {
      message.success('发布任务创建成功（Mock）');
      setTaskModalOpen(false);
      taskForm.resetFields();
    }
  };

  // 保存发布配置
  const handleSaveProfile = async () => {
    try {
      const values = await profileForm.validateFields();
      if (editingProfile) {
        await publishApi.updateProfile(editingProfile.id, values);
        message.success('配置更新成功');
      } else {
        await publishApi.createProfile(values);
        message.success('配置创建成功');
      }
      setProfileModalOpen(false);
      setEditingProfile(null);
      profileForm.resetFields();
      fetchProfiles();
    } catch {
      message.success('配置保存成功（Mock）');
      setProfileModalOpen(false);
      setEditingProfile(null);
      profileForm.resetFields();
    }
  };

  // 删除发布配置
  const handleDeleteProfile = async (id: string) => {
    try {
      await publishApi.deleteProfile(id);
      message.success('配置已删除');
      fetchProfiles();
    } catch {
      message.success('配置已删除（Mock）');
      setProfiles((prev) => prev.filter((p) => p.id !== id));
    }
  };

  // ========== 任务表格列 ==========

  const taskColumns: ColumnsType<PublishTask> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 200,
      ellipsis: true,
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 120,
      render: (platform: PublishPlatform) => (
        <Tag color={platformColors[platform]}>{platformLabels[platform]}</Tag>
      ),
    },
    {
      title: '账号',
      dataIndex: 'account_name',
      key: 'account_name',
      width: 120,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: PublishStatus) => (
        <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
      ),
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      width: 200,
      render: (tags: string[]) => (
        <Space size={[0, 4]} wrap>
          {tags.map((tag) => (
            <Tag key={tag}>{tag}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '发布时间',
      dataIndex: 'published_at',
      key: 'published_at',
      width: 170,
      render: (date: string) => (date ? new Date(date).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      key: 'error_message',
      width: 180,
      ellipsis: true,
      render: (msg: string) => (msg ? <Text type="danger">{msg}</Text> : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      fixed: 'right',
      render: (_: unknown, record: PublishTask) => (
        <Space>
          {record.status === 'pending_confirm' && (
            <Tooltip title="确认发布">
              <Button
                type="primary"
                size="small"
                icon={<CheckOutlined />}
                onClick={() => handleConfirmPublish(record.id)}
              >
                确认
              </Button>
            </Tooltip>
          )}
          {record.status === 'failed' && (
            <Button size="small" onClick={() => message.info('重试功能开发中')}>
              重试
            </Button>
          )}
          {record.published_url && (
            <Button size="small" type="link" href={record.published_url} target="_blank">
              查看
            </Button>
          )}
        </Space>
      ),
    },
  ];

  // ========== 配置表格列 ==========

  const profileColumns: ColumnsType<PublishProfile> = [
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 120,
      render: (platform: PublishPlatform) => (
        <Tag color={platformColors[platform]}>{platformLabels[platform]}</Tag>
      ),
    },
    {
      title: '账号名称',
      dataIndex: 'account_name',
      key: 'account_name',
      width: 150,
    },
    {
      title: '调试端口',
      dataIndex: 'chrome_debug_port',
      key: 'chrome_debug_port',
      width: 100,
    },
    {
      title: '发布模式',
      dataIndex: 'publish_mode',
      key: 'publish_mode',
      width: 100,
      render: (mode: string) => (mode === 'immediate' ? '立即发布' : '定时发布'),
    },
    {
      title: '需手动确认',
      dataIndex: 'require_manual_confirm',
      key: 'require_manual_confirm',
      width: 110,
      render: (val: boolean) => (val ? <Tag color="gold">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '最小间隔(秒)',
      dataIndex: 'min_interval_seconds',
      key: 'min_interval_seconds',
      width: 110,
    },
    {
      title: '每日上限',
      dataIndex: 'max_daily_publish',
      key: 'max_daily_publish',
      width: 100,
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      fixed: 'right',
      render: (_: unknown, record: PublishProfile) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditingProfile(record);
              profileForm.setFieldsValue(record);
              setProfileModalOpen(true);
            }}
          >
            编辑
          </Button>
          <Popconfirm title="确定删除此配置？" onConfirm={() => handleDeleteProfile(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ========== Tab 内容 ==========

  const tabItems = [
    {
      key: 'tasks',
      label: '发布任务',
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
            <Space>
              <Select placeholder="平台筛选" allowClear style={{ width: 140 }}
                options={Object.entries(platformLabels).map(([k, v]) => ({ value: k, label: v }))}
              />
              <Select placeholder="状态筛选" allowClear style={{ width: 140 }}
                options={Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))}
              />
            </Space>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={fetchTasks}>刷新</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setTaskModalOpen(true)}>
                新建发布
              </Button>
            </Space>
          </div>
          <Table
            rowKey="id"
            columns={taskColumns}
            dataSource={tasks}
            loading={loading}
            pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
            scroll={{ x: 1200 }}
            size="middle"
          />
        </div>
      ),
    },
    {
      key: 'profiles',
      label: '发布配置',
      children: (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => {
              setEditingProfile(null);
              profileForm.resetFields();
              setProfileModalOpen(true);
            }}>
              新增配置
            </Button>
          </div>
          <Table
            rowKey="id"
            columns={profileColumns}
            dataSource={profiles}
            pagination={false}
            scroll={{ x: 1000 }}
            size="middle"
          />
        </div>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>
        <SendOutlined style={{ marginRight: 8 }} />
        发布管理
      </Title>

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Card>

      {/* 新建发布任务弹窗 */}
      <Modal
        title="新建发布任务"
        open={taskModalOpen}
        onOk={handleCreateTask}
        onCancel={() => { setTaskModalOpen(false); taskForm.resetFields(); }}
        width={600}
        okText="创建"
        cancelText="取消"
      >
        <Form form={taskForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="output_id" label="输出文件" rules={[{ required: true, message: '请选择输出文件' }]}>
            <Select placeholder="请选择要发布的输出文件" />
          </Form.Item>
          <Form.Item name="platform" label="平台" rules={[{ required: true, message: '请选择平台' }]}>
            <Select
              placeholder="请选择发布平台"
              options={Object.entries(platformLabels).map(([k, v]) => ({ value: k, label: v }))}
            />
          </Form.Item>
          <Form.Item name="profile_id" label="发布配置" rules={[{ required: true, message: '请选择发布配置' }]}>
            <Select
              placeholder="请选择发布配置"
              options={profiles.map((p) => ({
                value: p.id,
                label: `${platformLabels[p.platform]} - ${p.account_name}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="请输入发布标题" maxLength={100} showCount />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea placeholder="请输入描述" rows={3} maxLength={500} showCount />
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Select mode="tags" placeholder="输入后按回车添加标签" />
          </Form.Item>
          <Form.Item name="cover_mode" label="封面模式" initialValue="auto">
            <Select
              options={[
                { value: 'auto', label: '自动截取' },
                { value: 'manual', label: '手动上传' },
              ]}
            />
          </Form.Item>
          <Form.Item name="publish_mode" label="发布模式" initialValue="immediate">
            <Select
              options={[
                { value: 'immediate', label: '立即发布' },
                { value: 'scheduled', label: '定时发布' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 发布配置弹窗 */}
      <Modal
        title={editingProfile ? '编辑发布配置' : '新增发布配置'}
        open={profileModalOpen}
        onOk={handleSaveProfile}
        onCancel={() => { setProfileModalOpen(false); setEditingProfile(null); profileForm.resetFields(); }}
        width={640}
        okText="保存"
        cancelText="取消"
      >
        <Form form={profileForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="platform" label="平台" rules={[{ required: true, message: '请选择平台' }]}>
            <Select
              placeholder="请选择平台"
              options={Object.entries(platformLabels).map(([k, v]) => ({ value: k, label: v }))}
            />
          </Form.Item>
          <Form.Item name="account_name" label="账号名称" rules={[{ required: true, message: '请输入账号名称' }]}>
            <Input placeholder="请输入账号名称" />
          </Form.Item>
          <Form.Item name="chrome_debug_port" label="Chrome 调试端口" rules={[{ required: true, message: '请输入端口号' }]}>
            <InputNumber placeholder="9222" min={1024} max={65535} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="title_template" label="标题模板">
            <Input placeholder="例: {title} - 精彩短剧推荐" />
          </Form.Item>
          <Form.Item name="description_template" label="描述模板">
            <TextArea placeholder="例: {description} #短剧" rows={2} />
          </Form.Item>
          <Form.Item name="default_tags" label="默认标签">
            <Select mode="tags" placeholder="输入后按回车添加" />
          </Form.Item>
          <Form.Item name="mini_program_link" label="小程序链接">
            <Input placeholder="请输入小程序链接（可选）" />
          </Form.Item>
          <Form.Item name="publish_mode" label="发布模式" initialValue="immediate">
            <Select
              options={[
                { value: 'immediate', label: '立即发布' },
                { value: 'scheduled', label: '定时发布' },
              ]}
            />
          </Form.Item>
          <Form.Item name="require_manual_confirm" label="需要手动确认" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="min_interval_seconds" label="最小发布间隔(秒)">
            <InputNumber min={0} style={{ width: '100%' }} placeholder="300" />
          </Form.Item>
          <Form.Item name="max_daily_publish" label="每日发布上限">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="20" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default PublishManagement;
