import React, { useEffect, useState } from 'react';
import {
  Card, Table, Button, Space, Typography, message, Modal, Form, Input, Tag, Select, InputNumber,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, SaveOutlined } from '@ant-design/icons';
import { configApi } from '../api/config';
import type { PlatformProfile, SystemConfig } from '../types';
import { formatDateTime } from '../utils/format';

const { Title } = Typography;

const Settings: React.FC = () => {
  const [configs, setConfigs] = useState<SystemConfig[]>([]);
  const [profiles, setProfiles] = useState<PlatformProfile[]>([]);
  const [profileModal, setProfileModal] = useState(false);
  const [editing, setEditing] = useState<PlatformProfile | null>(null);
  const [form] = Form.useForm();

  // 受控编辑值：key -> 当前编辑文本
  const [editValues, setEditValues] = useState<Record<string, string>>({});

  const fetchAll = () => {
    configApi.getAll().then((list) => {
      setConfigs(list);
      // 初始化编辑值
      const initial: Record<string, string> = {};
      list.forEach((c) => {
        initial[c.key] = typeof c.value === 'object' && c.value !== null
          ? JSON.stringify(c.value, null, 2)
          : String(c.value ?? '');
      });
      setEditValues(initial);
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
      fetchAll();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const saveProfile = async () => {
    try {
      const values = await form.validateFields();
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

  const renderValue = (key: string, value: unknown) => {
    if (typeof value === 'object' && value !== null) {
      const text = editValues[key] ?? JSON.stringify(value, null, 2);
      return (
        <Space>
          <Input.TextArea
            value={text}
            style={{ fontFamily: 'monospace', fontSize: 12 }}
            autoSize={{ minRows: 1, maxRows: 6 }}
            onChange={(e) => setEditValues((prev) => ({ ...prev, [key]: e.target.value }))}
            onBlur={(e) => {
              try {
                const parsed = JSON.parse(e.target.value);
                saveConfig(key, parsed);
              } catch {
                message.error('JSON 格式错误，未保存');
              }
            }}
          />
          <Button
            size="small"
            icon={<SaveOutlined />}
            onClick={() => {
              try {
                const parsed = JSON.parse(editValues[key] ?? '');
                saveConfig(key, parsed);
              } catch {
                message.error('JSON 格式错误，未保存');
              }
            }}
          >保存</Button>
        </Space>
      );
    }
    return (
      <Input
        value={editValues[key] ?? String(value ?? '')}
        style={{ width: 300 }}
        onChange={(e) => setEditValues((prev) => ({ ...prev, [key]: e.target.value }))}
        onPressEnter={(e) => saveConfig(key, (e.target as HTMLInputElement).value)}
      />
    );
  };

  const configColumns = [
    { title: '配置项', dataIndex: 'key', key: 'key', width: 260, render: (k: string) => <Tag>{k}</Tag> },
    { title: '值', key: 'value', render: (_: unknown, c: SystemConfig) => renderValue(c.key, c.value) },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 170, render: (d: string) => formatDateTime(d) },
  ];

  const profileColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
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
            form.setFieldsValue({
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
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>系统设置</Title>
      <Card size="small" title="全局配置" style={{ marginBottom: 16 }}>
        <Table rowKey="key" columns={configColumns} dataSource={configs} pagination={false} size="small" />
      </Card>
      <Card size="small" title="平台去重配置" extra={<Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setProfileModal(true); }}>新增配置</Button>}>
        <Table rowKey="id" columns={profileColumns} dataSource={profiles} pagination={false} size="small" />
      </Card>
      <Modal title={editing ? '编辑平台配置' : '新增平台配置'} open={profileModal} onOk={saveProfile} onCancel={() => setProfileModal(false)} destroyOnClose>
        <Form form={form} layout="vertical">
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
