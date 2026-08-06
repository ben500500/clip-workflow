import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Table, Tag, Typography, Spin, Alert, Space, Row, Col, Button, message,
  Modal, Form, Input, InputNumber, Select, Switch, Badge, Statistic, Tooltip,
} from 'antd';
import {
  WarningOutlined, CheckCircleOutlined, SyncOutlined,
  ApiOutlined, DatabaseOutlined, CloudServerOutlined, HddOutlined,
} from '@ant-design/icons';
import { monitorApi } from '../api/monitor';

const { Title, Text } = Typography;

interface HealthCheck {
  status: string;
  service: string;
  checks: Record<string, { status: string; error?: string; usage_percent?: number }>;
}

const METRIC_LABELS: Record<string, string> = {
  worker_offline: 'Worker 离线',
  task_failed: '任务失败',
  disk_usage: '磁盘使用率',
  redis_memory: 'Redis 内存',
  queue_backlog: '队列积压',
  cookie_expiring: 'Cookie 过期',
  ecpm_low: 'eCPM 偏低',
};

const Monitor: React.FC = () => {
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [metrics, setMetrics] = useState<Record<string, number>>({});
  const [rules, setRules] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<any>(null);
  const [meta, setMeta] = useState<{ metric: string; description: string }[]>([]);
  const [form] = Form.useForm();

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [h, m, r, e, metaData] = await Promise.all([
        monitorApi.getHealth(),
        monitorApi.getMetrics(),
        monitorApi.getAlertRules(),
        monitorApi.getAlertEvents({ limit: 50 }),
        monitorApi.getAlertRuleMeta(),
      ]);
      setHealth(h);
      setMetrics(m);
      setRules(r);
      setEvents(e);
      setMeta(metaData);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载监控数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const openCreate = () => {
    setEditingRule(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (rule: any) => {
    setEditingRule(rule);
    form.setFieldsValue(rule);
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      if (editingRule) {
        await monitorApi.updateAlertRule(editingRule.id, values);
        message.success('告警规则已更新');
      } else {
        await monitorApi.createAlertRule(values);
        message.success('告警规则已创建');
      }
      setModalOpen(false);
      fetchAll();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败');
    }
  };

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '删除后该告警规则将不再生效，确定继续？',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      async onOk() {
        try {
          await monitorApi.deleteAlertRule(id);
          message.success('已删除');
          fetchAll();
        } catch (err: unknown) {
          message.error(err instanceof Error ? err.message : '删除失败');
        }
      },
    });
  };

  const handleRunCheck = async () => {
    try {
      const res = await monitorApi.runAlertCheck();
      message.success(`检查完成：触发 ${res.triggered} 条告警，已通知 ${res.notified} 条`);
      fetchAll();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '检查失败');
    }
  };

  const checkItems = health?.checks ? Object.entries(health.checks) : [];
  const checkIcons: Record<string, React.ReactNode> = {
    database: <DatabaseOutlined />,
    redis: <ApiOutlined />,
    minio: <CloudServerOutlined />,
    disk: <HddOutlined />,
  };

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ marginBottom: 0 }}>监控告警</Title>
          <Text type="secondary">健康检查 · 告警规则 · 钉钉通知（三期）</Text>
        </Col>
        <Col>
          <Space>
            <Button icon={<SyncOutlined />} onClick={fetchAll}>刷新</Button>
            <Button type="primary" icon={<WarningOutlined />} onClick={handleRunCheck}>立即检查</Button>
            <Button type="primary" onClick={openCreate}>新建规则</Button>
          </Space>
        </Col>
      </Row>

      {/* 健康检查卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {checkItems.map(([name, check]) => (
          <Col xs={12} sm={8} md={6} key={name}>
            <Card size="small">
              <Statistic
                title={name.toUpperCase()}
                value={check.status === 'ok' ? '正常' : check.status === 'degraded' ? '降级' : '异常'}
                valueStyle={{
                  color: check.status === 'ok' ? '#52c41a' : check.status === 'degraded' ? '#faad14' : '#ff4d4f',
                  fontSize: 18,
                }}
                prefix={checkIcons[name] || <CheckCircleOutlined />}
              />
              {check.usage_percent !== undefined && (
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary">使用率 {check.usage_percent}%</Text>
                </div>
              )}
              {check.error && (
                <Tooltip title={check.error}>
                  <Text type="danger" style={{ fontSize: 12 }} ellipsis>{check.error}</Text>
                </Tooltip>
              )}
            </Card>
          </Col>
        ))}
        {checkItems.length === 0 && (
          <Col span={24}><Spin /></Col>
        )}
      </Row>

      <Row gutter={[16, 16]}>
        {/* 告警规则 */}
        <Col xs={24} lg={14}>
          <Card
            size="small"
            title="告警规则"
            extra={<Text type="secondary">{rules.length} 条</Text>}
            style={{ marginBottom: 16 }}
          >
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={rules}
              pagination={false}
              columns={[
                { title: '规则名', dataIndex: 'name', key: 'name', ellipsis: true },
                {
                  title: '指标', dataIndex: 'metric', key: 'metric', width: 110,
                  render: (m: string) => METRIC_LABELS[m] || m,
                },
                {
                  title: '条件', key: 'condition', width: 110,
                  render: (_, r) => <Text>{r.operator} {r.threshold}</Text>,
                },
                {
                  title: '级别', dataIndex: 'level', key: 'level', width: 80,
                  render: (l: string) =>
                    l === 'critical' ? <Tag color="red">严重</Tag> : <Tag color="orange">警告</Tag>,
                },
                {
                  title: '状态', dataIndex: 'enabled', key: 'enabled', width: 70,
                  render: (v: boolean) => (v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
                },
                {
                  title: '操作', key: 'actions', width: 130,
                  render: (_, r) => (
                    <Space size={4}>
                      <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
                      <Button size="small" danger onClick={() => handleDelete(r.id)}>删除</Button>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </Col>

        {/* 当前指标 */}
        <Col xs={24} lg={10}>
          <Card size="small" title="当前指标" style={{ marginBottom: 16 }}>
            <Table
              rowKey="metric"
              size="small"
              loading={loading}
              dataSource={Object.entries(metrics).map(([metric, value]) => ({ metric, value }))}
              pagination={false}
              columns={[
                {
                  title: '指标', dataIndex: 'metric', key: 'metric',
                  render: (m: string) => METRIC_LABELS[m] || m,
                },
                { title: '当前值', dataIndex: 'value', key: 'value', width: 100 },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* 告警事件 */}
      <Card size="small" title="告警事件记录">
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={events}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            {
              title: '级别', dataIndex: 'level', key: 'level', width: 80,
              render: (l: string) =>
                l === 'critical' ? <Tag color="red">严重</Tag> : <Tag color="orange">警告</Tag>,
            },
            { title: '规则', dataIndex: 'rule_name', key: 'rule_name', ellipsis: true },
            { title: '内容', dataIndex: 'message', key: 'message', ellipsis: true },
            {
              title: '通知', dataIndex: 'notified', key: 'notified', width: 80,
              render: (v: boolean) => (v ? <Tag color="green">已发送</Tag> : <Tag>未发送</Tag>),
            },
            {
              title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170,
              render: (t: string) => (t ? new Date(t).toLocaleString() : '-'),
            },
          ]}
        />
      </Card>

      <Modal
        title={editingRule ? '编辑告警规则' : '新建告警规则'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="如：Worker 节点离线" />
          </Form.Item>
          <Form.Item name="metric" label="监控指标" rules={[{ required: true, message: '请选择指标' }]}>
            <Select
              placeholder="选择监控指标"
              options={meta.map((m) => ({ value: m.metric, label: `${METRIC_LABELS[m.metric] || m.metric} - ${m.description}` }))}
            />
          </Form.Item>
          <Space style={{ width: '100%' }} size={12}>
            <Form.Item name="operator" label="比较符" initialValue=">" rules={[{ required: true }]}>
              <Select style={{ width: 80 }} options={[
                { value: '>', label: '>' }, { value: '>=', label: '>=' },
                { value: '<', label: '<' }, { value: '<=', label: '<=' },
                { value: '==', label: '==' },
              ]} />
            </Form.Item>
            <Form.Item name="threshold" label="阈值" initialValue={0} rules={[{ required: true }]}>
              <InputNumber style={{ width: 140 }} min={0} />
            </Form.Item>
            <Form.Item name="level" label="级别" initialValue="warning" rules={[{ required: true }]}>
              <Select style={{ width: 100 }} options={[
                { value: 'warning', label: '警告' }, { value: 'critical', label: '严重' },
              ]} />
            </Form.Item>
          </Space>
          <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="规则说明" />
          </Form.Item>
          <Form.Item name="webhook_url" label="钉钉 Webhook（可选，留空使用全局）">
            <Input placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default Monitor;
