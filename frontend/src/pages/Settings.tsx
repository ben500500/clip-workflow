import React, { useEffect, useState } from 'react';
import {
  Card, Table, Button, Space, Typography, message, Modal, Form, Input, Tag, Select, InputNumber, Tooltip,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons';
import { configApi } from '../api/config';
import type { PlatformProfile, SystemConfig } from '../types';
import { formatDateTime } from '../utils/format';

const { Title, Text } = Typography;

const Settings: React.FC = () => {
  const [configs, setConfigs] = useState<SystemConfig[]>([]);
  const [profiles, setProfiles] = useState<PlatformProfile[]>([]);
  const [profileModal, setProfileModal] = useState(false);
  const [configModal, setConfigModal] = useState(false);
  const [editing, setEditing] = useState<PlatformProfile | null>(null);
  const [editingConfig, setEditingConfig] = useState<SystemConfig | null>(null);
  const [configForm] = Form.useForm();
  const [profileForm] = Form.useForm();

  const fetchAll = () => {
    configApi.getAll().then((list) => {
      setConfigs(list);
    }).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'));
    configApi.getPlatformProfiles().then(setProfiles).catch((err: unknown) => message.error(err instanceof Error ? err.message : '加载失败'));
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const saveConfig = async (key: string, value: unknown) => {
    try {
      await configApi.update(key, value);
      message.success('配置已保存');
      setConfigModal(false);
      setEditingConfig(null);
      fetchAll();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleConfigEdit = (config: SystemConfig) => {
    setEditingConfig(config);
    const val = typeof config.value === 'object' && config.value !== null
      ? JSON.stringify(config.value, null, 2)
      : String(config.value ?? '');
    configForm.setFieldsValue({ value: val });
    setConfigModal(true);
  };

  const handleConfigSave = async () => {
    try {
      const values = await configForm.validateFields();
      if (!editingConfig) return;
      const raw = values.value;
      try {
        if (typeof editingConfig.value === 'object' && editingConfig.value !== null) {
          const parsed = JSON.parse(raw);
          await saveConfig(editingConfig.key, parsed);
        } else {
          await saveConfig(editingConfig.key, raw);
        }
      } catch {
        message.error('JSON 格式错误，请检查输入内容');
      }
    } catch {
      // 表单验证未通过，忽略
    }
  };

  const saveProfile = async () => {
    try {
      const values = await profileForm.validateFields();
      const payload = {
        ...values,
        dedupe_config: values.dedupe_config ? JSON.parse(values.dedupe_config) : null,
      };
      if (editing) {
        await configApi.updatePlatformProfile(editing.id, payload);
        message.success('配置已更新');
      } else {
        await configApi.createPlatformProfile(payload);
        message.success('配置已创建');
      }
      setProfileModal(false);
      fetchAll();
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        message.error('去重配置必须是合法 JSON');
        return;
      }
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const renderConfigValue = (config: SystemConfig) => {
    const displayText = typeof config.value === 'object' && config.value !== null
      ? JSON.stringify(config.value, null, 2)
      : String(config.value ?? '');

    const isLongText = displayText.length > 80;
    const display = isLongText ? displayText.substring(0, 80) + '…' : displayText;

    return (
      <Space>
        <Tooltip title={isLongText ? displayText : undefined}>
          <Text
            style={{
              fontFamily: 'monospace',
              fontSize: 12,
              maxWidth: 400,
              display: 'inline-block',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {display}
          </Text>
        </Tooltip>
        <Button size="small" icon={<EditOutlined />} onClick={() => handleConfigEdit(config)}>编辑</Button>
      </Space>
    );
  };

  const configColumns = [
    { title: '配置项', dataIndex: 'key', key: 'key', width: 240, render: (k: string) => <Tag>{k}</Tag> },
    {
      title: '值',
      key: 'value',
      width: 550,
      render: (_: unknown, c: SystemConfig) => renderConfigValue(c),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (d: string) => formatDateTime(d),
    },
  ];

  const profileColumns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 160 },
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 120, render: (p: string) => <Tag>{p}</Tag> },
    { title: '目标分辨率', dataIndex: 'target_resolution', key: 'target_resolution', width: 120, render: (v: string) => v || '-' },
    { title: '目标码率', dataIndex: 'target_bitrate', key: 'target_bitrate', width: 120, render: (v: string) => v || '-' },
    { title: '最大时长', dataIndex: 'max_duration', key: 'max_duration', width: 100, render: (v: number) => v ?? '-' },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: unknown, p: PlatformProfile) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditing(p);
            profileForm.setFieldsValue({
              name: p.name,
              platform: p.platform,
              target_resolution: p.target_resolution,
              target_bitrate: p.target_bitrate,
              max_duration: p.max_duration,
              dedupe_config: p.dedupe_config ? JSON.stringify(p.dedupe_config, null, 2) : '',
            });
            setProfileModal(true);
          }}>编辑</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={async () => {
            try {
              await configApi.deletePlatformProfile(p.id);
              message.success('已删除');
              fetchAll();
            } catch (err: unknown) {
              message.error(err instanceof Error ? err.message : '删除失败');
            }
          }}>删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1200, overflow: 'hidden' }}>
      <Title level={4} style={{ marginBottom: 16 }}>系统设置</Title>
      <Card size="small" title="全局配置" style={{ marginBottom: 16 }}>
        <Table
          rowKey="key"
          columns={configColumns}
          dataSource={configs}
          pagination={false}
          size="small"
          scroll={{ x: 960 }}
        />
      </Card>
      <Card
        size="small"
        title="平台去重配置"
        extra={
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => {
            setEditing(null);
            profileForm.resetFields();
            setProfileModal(true);
          }}>新增配置</Button>
        }
      >
        <Table
          rowKey="id"
          columns={profileColumns}
          dataSource={profiles}
          pagination={false}
          size="small"
          scroll={{ x: 800 }}
        />
      </Card>

      {/* 编辑全局配置弹窗 */}
      <Modal
        title={editingConfig ? `编辑配置: ${editingConfig.key}` : '编辑配置'}
        open={configModal}
        onOk={handleConfigSave}
        onCancel={() => {
          setConfigModal(false);
          setEditingConfig(null);
        }}
        destroyOnClose
        width={600}
      >
        <Form form={configForm} layout="vertical">
          <Form.Item
            name="value"
            label="配置值"
            rules={[{ required: true, message: '请输入配置值' }]}
          >
            <Input.TextArea
              rows={8}
              style={{ fontFamily: 'monospace', fontSize: 13 }}
              placeholder="请输入配置值…"
            />
          </Form.Item>
          {editingConfig && typeof editingConfig.value === 'object' && editingConfig.value !== null && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              提示：该配置项为 JSON 格式，请确保输入合法的 JSON 字符串
            </Text>
          )}
        </Form>
      </Modal>

      {/* 编辑平台配置弹窗 */}
      <Modal
        title={editing ? '编辑平台配置' : '新增平台配置'}
        open={profileModal}
        onOk={saveProfile}
        onCancel={() => setProfileModal(false)}
        destroyOnClose
        width={560}
      >
        <Form form={profileForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={[{ value: 'wechat_channel', label: '视频号' }, { value: 'douyin', label: '抖音' }, { value: 'kuaishou', label: '快手' }]} />
          </Form.Item>
          <Form.Item name="target_resolution" label="目标分辨率"><Input placeholder="1920x1080" /></Form.Item>
          <Form.Item name="target_bitrate" label="目标码率"><Input placeholder="4000k" /></Form.Item>
          <Form.Item name="max_duration" label="最大时长（秒）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="dedupe_config" label="去重配置 JSON"><Input.TextArea rows={6} style={{ fontFamily: 'monospace' }} placeholder='{"speed_change": true, "speed_factor": 1.04}' /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default Settings;