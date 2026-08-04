import React, { useEffect, useState } from 'react';
import {
  Card,
  Typography,
  Spin,
  Alert,
  Button,
  Space,
  Row,
  Col,
  Form,
  InputNumber,
  Select,
  Switch,
  Input,
  message,
  Divider,
  Tabs,
  Empty,
} from 'antd';
import {
  SaveOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  NodeIndexOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { configApi } from '../api/config';
import type { SystemConfig, AutoClipConfig, IntervalDetectionConfig, DedupeConfig } from '../types';

const { Title, Text } = Typography;

const Settings: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<SystemConfig | null>(null);

  const [autoClipForm] = Form.useForm();
  const [intervalForm] = Form.useForm();
  const [dedupeForm] = Form.useForm();
  const [systemForm] = Form.useForm();

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await configApi.getSystemConfig();
      setConfig(res.data);
      // Populate forms
      autoClipForm.setFieldsValue(res.data.auto_clip);
      intervalForm.setFieldsValue(res.data.interval_detection);
      dedupeForm.setFieldsValue(res.data.dedupe);
      systemForm.setFieldsValue({
        output_dir: res.data.output_dir,
        concurrency: res.data.concurrency,
        retention_days: res.data.retention_days,
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取配置失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveAll = async () => {
    setSaving(true);
    try {
      const autoClip = await autoClipForm.validateFields();
      const intervalDetection = await intervalForm.validateFields();
      const dedupe = await dedupeForm.validateFields();
      const system = await systemForm.validateFields();

      const updatedConfig: Partial<SystemConfig> = {
        auto_clip: autoClip,
        interval_detection: intervalDetection,
        dedupe,
        ...system,
      };

      await configApi.updateSystemConfig(updatedConfig);
      message.success('系统配置已保存');
      fetchConfig();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (error) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const tabItems = [
    {
      key: 'autoclip',
      label: (
        <span>
          <ThunderboltOutlined /> AutoClip 配置
        </span>
      ),
      children: (
        <Form
          form={autoClipForm}
          layout="vertical"
          style={{ maxWidth: 600 }}
          initialValues={{
            min_clip_duration: 15,
            max_clip_duration: 300,
            min_confidence: 0.5,
            max_clips: 50,
            overlap_ratio: 0.1,
            detect_types: ['highlight', 'funny', 'exciting'],
            custom_prompt: '',
          }}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="min_clip_duration" label="最小时长(秒)">
                <InputNumber min={1} max={3600} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="max_clip_duration" label="最大时长(秒)">
                <InputNumber min={1} max={7200} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="min_confidence" label="最低置信度">
                <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="max_clips" label="最大选点数">
                <InputNumber min={1} max={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="overlap_ratio" label="重叠比例">
                <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="detect_types" label="检测类型">
                <Select
                  mode="multiple"
                  placeholder="选择检测类型"
                  options={[
                    { label: '精彩片段', value: 'highlight' },
                    { label: '搞笑片段', value: 'funny' },
                    { label: '激动时刻', value: 'exciting' },
                    { label: '感人片段', value: 'touching' },
                    { label: '教学片段', value: 'educational' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="custom_prompt" label="自定义提示词">
            <Input.TextArea rows={3} placeholder="可选：输入自定义检测提示词" />
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'interval',
      label: (
        <span>
          <NodeIndexOutlined /> 区间检测配置
        </span>
      ),
      children: (
        <Form
          form={intervalForm}
          layout="vertical"
          style={{ maxWidth: 600 }}
          initialValues={{
            min_interval_duration: 10,
            max_interval_duration: 600,
            merge_threshold: 5,
            min_silence_duration: 1,
            voice_activity_threshold: 0.5,
            detect_modes: ['silence', 'scene_change'],
          }}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="min_interval_duration" label="最小区间时长(秒)">
                <InputNumber min={1} max={3600} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="max_interval_duration" label="最大区间时长(秒)">
                <InputNumber min={1} max={7200} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="merge_threshold" label="合并阈值(秒)">
                <InputNumber min={0} max={60} step={0.5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="min_silence_duration" label="最小静音时长(秒)">
                <InputNumber min={0.1} max={30} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="voice_activity_threshold" label="语音活动阈值">
                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="detect_modes" label="检测模式">
                <Select
                  mode="multiple"
                  placeholder="选择检测模式"
                  options={[
                    { label: '静音检测', value: 'silence' },
                    { label: '场景切换', value: 'scene_change' },
                    { label: '语音活动', value: 'voice_activity' },
                    { label: '内容分析', value: 'content_analysis' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      ),
    },
    {
      key: 'dedupe',
      label: (
        <span>
          <DeleteOutlined /> 去重配置
        </span>
      ),
      children: (
        <Form
          form={dedupeForm}
          layout="vertical"
          style={{ maxWidth: 600 }}
          initialValues={{
            enabled: true,
            similarity_threshold: 0.85,
            method: 'perceptual',
            max_duplicate_ratio: 0.3,
          }}
        >
          <Form.Item name="enabled" label="启用去重" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="similarity_threshold" label="相似度阈值">
                <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="method" label="去重方法">
                <Select
                  options={[
                    { label: '哈希去重', value: 'hash' },
                    { label: '感知去重', value: 'perceptual' },
                    { label: '内容去重', value: 'content' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="max_duplicate_ratio" label="最大重复比例">
                <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      ),
    },
    {
      key: 'system',
      label: (
        <span>系统设置</span>
      ),
      children: (
        <Form
          form={systemForm}
          layout="vertical"
          style={{ maxWidth: 600 }}
          initialValues={{
            output_dir: '/data/outputs',
            concurrency: 2,
            retention_days: 30,
          }}
        >
          <Form.Item name="output_dir" label="输出目录">
            <Input placeholder="例如: /data/outputs" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="concurrency" label="并发数">
                <InputNumber min={1} max={16} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="retention_days" label="保留天数">
                <InputNumber min={1} max={365} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            系统设置
          </Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchConfig}>
              重置
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSaveAll}
            >
              保存全部配置
            </Button>
          </Space>
        </Col>
      </Row>

      <Card size="small">
        <Tabs items={tabItems} />
      </Card>
    </div>
  );
};

export default Settings;