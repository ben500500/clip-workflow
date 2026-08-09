import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Modal, Form, Input, Select, Popconfirm, InputNumber, Alert,
} from 'antd';
import { ReloadOutlined, PlusOutlined, CheckCircleOutlined, DeleteOutlined, EyeOutlined } from '@ant-design/icons';
import { publishApi } from '../api/publish';
import type { PublishProfile, PublishTask } from '../types';
import { formatDateTime, getStatusColor, getStatusLabel } from '../utils/format';

const { Title } = Typography;

const PublishManagement: React.FC = () => {
  const [tasks, setTasks] = useState<PublishTask[]>([]);
  const [profiles, setProfiles] = useState<PublishProfile[]>([]);
  const [taskModal, setTaskModal] = useState(false);
  const [profileModal, setProfileModal] = useState(false);
  const [editingProfile, setEditingProfile] = useState<PublishProfile | null>(null);
  const [taskLoading, setTaskLoading] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);
  const [taskForm] = Form.useForm();
  const [profileForm] = Form.useForm();
  const [screenshotModal, setScreenshotModal] = useState(false);
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null);
  const [screenshotLoading, setScreenshotLoading] = useState(false);

  const fetchAll = () => {
    setTaskLoading(true);
    setProfileLoading(true);
    publishApi.getTasks().then(setTasks).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败')).finally(() => setTaskLoading(false));
    publishApi.getProfiles().then(setProfiles).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败')).finally(() => setProfileLoading(false));
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const confirmTask = async (id: string) => {
    try {
      await publishApi.confirmTask(id);
      message.success('已确认，正在发布');
      setTimeout(fetchAll, 3000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '确认失败');
    }
  };

  const viewScreenshot = async (id: string) => {
    setScreenshotModal(true);
    setScreenshotLoading(true);
    setScreenshotUrl(null);
    try {
      const res = await publishApi.getTaskScreenshot(id);
      setScreenshotUrl(res.screenshot_url);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载截图失败');
      setScreenshotModal(false);
    } finally {
      setScreenshotLoading(false);
    }
  };

  const createTask = async () => {
    try {
      const values = await taskForm.validateFields();
      await publishApi.createTask(values);
      message.success('发布任务已创建');
      setTaskModal(false);
      fetchAll();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '创建失败');
    }
  };

  const saveProfile = async () => {
    try {
      const values = await profileForm.validateFields();
      if (editingProfile) {
        await publishApi.updateProfile(editingProfile.id, values);
        message.success('配置已更新');
      } else {
        await publishApi.createProfile(values);
        message.success('配置已创建');
      }
      setProfileModal(false);
      fetchAll();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const taskColumns = [
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (t: string) => t || '-' },
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 110, render: (p: string) => <Tag>{p}</Tag> },
    { title: '账号', dataIndex: 'account_name', key: 'account_name', width: 110, render: (a: string) => a || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>,
    },
    { title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true, render: (e: string) => e || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (d: string) => formatDateTime(d) },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, t: PublishTask) =>
        t.status === 'pending_confirm' ? (
          <Space size="small" wrap>
            <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => confirmTask(t.id)}>确认发布</Button>
            {t.screenshot_key && (
              <Button size="small" icon={<EyeOutlined />} onClick={() => viewScreenshot(t.id)}>查看截图</Button>
            )}
          </Space>
        ) : (
          <span>{t.published_url ? <a href={t.published_url} target="_blank" rel="noreferrer">已发布</a> : '-'}</span>
        ),
    },
  ];

  const profileColumns = [
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 120 },
    { title: '账号', dataIndex: 'account_name', key: 'account_name' },
    { title: 'Chrome 端口', dataIndex: 'chrome_debug_port', key: 'chrome_debug_port', width: 120 },
    { title: '每日上限', dataIndex: 'max_daily_publish', key: 'max_daily_publish', width: 100 },
    { title: '发布间隔(秒)', dataIndex: 'min_interval_seconds', key: 'min_interval_seconds', width: 130 },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, p: PublishProfile) => (
        <Button size="small" danger icon={<DeleteOutlined />} onClick={async () => {
          try {
            await publishApi.deleteProfile(p.id);
            message.success('已删除');
            fetchAll();
          } catch (err: unknown) {
            message.error(err instanceof Error ? err.message : '删除失败');
          }
        }}>删除</Button>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>发布管理</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchAll}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { taskForm.resetFields(); setTaskModal(true); }}>新建发布任务</Button>
      </Space>
      <Card size="small" title="发布任务" style={{ marginBottom: 16 }}>
        <Table rowKey="id" columns={taskColumns} dataSource={tasks} loading={taskLoading} pagination={false} size="small" scroll={{ x: 900 }} />
      </Card>
      <Card size="small" title="发布配置" extra={<Button size="small" icon={<PlusOutlined />} onClick={() => { setEditingProfile(null); profileForm.resetFields(); setProfileModal(true); }}>新增配置</Button>}>
        <Table rowKey="id" columns={profileColumns} dataSource={profiles} loading={profileLoading} pagination={false} size="small" scroll={{ x: 720 }} />
      </Card>

      <Modal title="新建发布任务" open={taskModal} onOk={createTask} onCancel={() => setTaskModal(false)} destroyOnClose>
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message="创建后立即触发 RPA 自动发布；若开启了截图确认，需在任务列表「确认发布」。「发布管理」页支持多平台批量发布（在成品预览点「一键发布」）。" />
        <Form form={taskForm} layout="vertical">
          <Form.Item name="output_id" label="切片输出 ID" rules={[{ required: true, message: '请输入切片输出 ID' }]}>
            <Input placeholder="在成品预览页复制输出 ID" />
          </Form.Item>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="account_name" label="账号"><Input /></Form.Item>
          <Form.Item name="title" label="标题"><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="tags" label="标签"><Select mode="tags" placeholder="回车添加标签" /></Form.Item>
          <Form.Item name="mini_program_link" label="小程序链接"><Input /></Form.Item>
        </Form>
      </Modal>

      <Modal title={editingProfile ? '编辑发布配置' : '新增发布配置'} open={profileModal} onOk={saveProfile} onCancel={() => setProfileModal(false)} destroyOnClose>
        <Form form={profileForm} layout="vertical">
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="account_name" label="账号" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="chrome_debug_port" label="Chrome 调试端口" initialValue={9222}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="max_daily_publish" label="每日最大发布数" initialValue={20}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="min_interval_seconds" label="最小发布间隔（秒）" initialValue={300}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="require_manual_confirm" label="需要人工确认" initialValue={true}>
            <Select options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="发布确认截图"
        open={screenshotModal}
        footer={null}
        width={720}
        onCancel={() => setScreenshotModal(false)}
        destroyOnClose
      >
        {screenshotLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>加载中…</div>
        ) : screenshotUrl ? (
          <img src={screenshotUrl} alt="发布确认截图" style={{ width: '100%', borderRadius: 6 }} />
        ) : (
          <Typography.Text type="secondary">暂无截图</Typography.Text>
        )}
      </Modal>
    </div>
  );
};

export default PublishManagement;
