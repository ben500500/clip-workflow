import React, { useEffect, useState } from 'react';
import {
  Card, Form, InputNumber, Select, Button, Typography, Spin, Alert, message, Divider, Tag, Space, Input,
} from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { dashboardApi } from '../api/dashboard';

const { Title, Text } = Typography;

interface DashboardConfig {
  default_account_id: string | null;
  default_date_range: number;
  chart_colors: string[];
  auto_refresh_interval: number;
  enable_funnel: boolean;
  enable_ecosystem: boolean;
  [key: string]: unknown;
}

const DashboardSettings: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<DashboardConfig>({
    default_account_id: null,
    default_date_range: 30,
    chart_colors: ['#1890ff', '#52c41a', '#faad14', '#f5222d'],
    auto_refresh_interval: 300,
    enable_funnel: true,
    enable_ecosystem: true,
  });
  const [form] = Form.useForm();

  useEffect(() => {
    dashboardApi.getConfig()
      .then((res) => {
        const c = res.config as DashboardConfig;
        setConfig(c);
        form.setFieldsValue(c);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async (values: Record<string, unknown>) => {
    setSaving(true);
    try {
      await dashboardApi.updateConfig(values);
      message.success('配置已保存');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }
  if (error) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>看板设置</Title>

      <Form
        form={form}
        layout="vertical"
        onFinish={handleSave}
        initialValues={config}
        style={{ maxWidth: 600 }}
      >
        <Card size="small" title="指标口径" style={{ marginBottom: 16 }}>
          <Form.Item label="eCPM 计算公式" name="ecpm_formula">
            <Input placeholder="收益 ÷ 曝光 × 1000" />
          </Form.Item>
          <Form.Item label="单UV收益公式" name="revenue_per_uv_formula">
            <Input placeholder="收益 ÷ 小程序UV" />
          </Form.Item>
          <Form.Item label="跳转率公式" name="jump_rate_formula">
            <Input placeholder="跳转点击 ÷ 播放量" />
          </Form.Item>
        </Card>

        <Card size="small" title="预警阈值" style={{ marginBottom: 16 }}>
          <Form.Item label="收益骤降告警百分比 (%)" name={['alerts', 'revenue_drop_percent']}>
            <InputNumber min={0} max={100} addonAfter="%" style={{ width: 200 }} />
          </Form.Item>
          <Form.Item label="eCPM 最低值 (元)" name={['alerts', 'ecpm_min_value']}>
            <InputNumber min={0} precision={2} addonBefore="¥" style={{ width: 200 }} />
          </Form.Item>
          <Form.Item label="跳转率最低值 (%)" name={['alerts', 'jump_rate_min_percent']}>
            <InputNumber min={0} max={100} addonAfter="%" style={{ width: 200 }} />
          </Form.Item>
        </Card>

        <Card size="small" title="归因配置" style={{ marginBottom: 16 }}>
          <Form.Item label="归因方式" name={['attribution', 'method']}>
            <Select style={{ width: 200 }}
              options={[
                { value: 'channel_param', label: '渠道参数归因' },
                { value: 'indirect', label: '间接归因' },
              ]}
            />
          </Form.Item>
          <Form.Item label="归因时间窗口 (天)" name={['attribution', 'time_window_days']}>
            <InputNumber min={1} max={30} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item label="默认单UV收益 (元)" name={['attribution', 'default_uv_revenue']}>
            <InputNumber min={0} precision={4} addonBefore="¥" style={{ width: 200 }} />
          </Form.Item>
        </Card>

        <Card size="small" title="显示设置" style={{ marginBottom: 16 }}>
          <Form.Item label="默认日期范围 (天)" name="default_date_range">
            <InputNumber min={1} max={365} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item label="自动刷新间隔 (秒)" name="auto_refresh_interval">
            <InputNumber min={0} max={3600} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item label="图表颜色" name="chart_colors">
            <Select mode="tags" open={false} style={{ width: 300 }}
              placeholder="输入颜色值后回车"
            />
          </Form.Item>
        </Card>

        <Button type="primary" htmlType="submit" loading={saving}>保存配置</Button>
      </Form>
    </div>
  );
};

export default DashboardSettings;