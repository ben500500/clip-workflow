import React, { useEffect, useState } from 'react';
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Statistic,
  Row,
  Col,
  message,
  Tooltip,
  Switch,
  Progress,
} from 'antd';
import {
  ReloadOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
  DesktopOutlined,
  CloudServerOutlined,
  ApiOutlined,
  PoweroffOutlined,
  PlusOutlined,
  MinusOutlined,
} from '@ant-design/icons';
import { sliceApi } from '../api/slice';
import type { WorkerNode } from '../types';

const { Title, Text } = Typography;

const WorkersPage: React.FC = () => {
  const [workers, setWorkers] = useState<WorkerNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const fetchWorkers = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await sliceApi.listWorkers();
      setWorkers(data);
    } catch (err: unknown) {
      if (!silent) {
        message.error(err instanceof Error ? err.message : '获取 Worker 节点列表失败');
      }
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const syncFromRedis = async () => {
    setSyncing(true);
    try {
      const result = await sliceApi.syncWorkers();
      message.success(result.message);
      fetchWorkers();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '同步失败');
    } finally {
      setSyncing(false);
    }
  };

  // 启停节点
  const toggleWorker = async (node: WorkerNode, enabled: boolean) => {
    setTogglingId(node.node_id);
    try {
      if (enabled) {
        const res = await sliceApi.enableWorker(node.node_id);
        message.success(res.message);
      } else {
        const res = await sliceApi.disableWorker(node.node_id);
        message.success(res.message);
      }
      fetchWorkers();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setTogglingId(null);
    }
  };

  // 调整节点 CPU 分配比例
  const adjustCpuPercent = async (node: WorkerNode, delta: number) => {
    const current = Math.max(1, Math.min(100, node.cpu_percent ?? 50));
    const next = Math.max(1, Math.min(100, current + delta));
    if (next === current) {
      message.warning('CPU 分配已达上限/下限（1~100%）');
      return;
    }
    setTogglingId(node.node_id);
    try {
      const res = await sliceApi.setWorkerCpuPercent(node.node_id, next);
      message.success(res.message);
      fetchWorkers();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '调整 CPU 分配失败');
    } finally {
      setTogglingId(null);
    }
  };

  useEffect(() => {
    fetchWorkers();
    const interval = setInterval(() => fetchWorkers(true), 10000);
    return () => clearInterval(interval);
  }, []);

  const onlineCount = workers.filter((w) => w.status === 'online' && w.enabled !== false).length;
  const enabledCount = workers.filter((w) => w.enabled !== false).length;
  const totalConcurrent = workers.reduce((s, w) => s + (w.max_concurrent || 0), 0);
  const totalRunning = workers.reduce((s, w) => s + (w.current_tasks || 0), 0);
  const totalCompleted = workers.reduce((s, w) => s + (w.total_tasks_completed || 0), 0);

  const columns = [
    {
      title: '节点 ID',
      dataIndex: 'node_id',
      key: 'node_id',
      width: 180,
      ellipsis: true,
      render: (id: string, record: WorkerNode) => (
        <Space size={6}>
          <DesktopOutlined style={{ color: record.status === 'online' ? '#52c41a' : '#999' }} />
          <Text code style={{ fontSize: 12 }}>{id}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string, record: WorkerNode) => {
        if (record.enabled === false) {
          return <Tag icon={<PoweroffOutlined />} color="default">已停用</Tag>;
        }
        if (status === 'online') {
          return <Tag icon={<CheckCircleOutlined />} color="success">在线</Tag>;
        }
        if (status === 'offline') {
          return <Tag icon={<CloseCircleOutlined />} color="error">离线</Tag>;
        }
        return <Tag icon={<MinusCircleOutlined />}>{status}</Tag>;
      },
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      key: 'ip',
      width: 130,
      ellipsis: true,
      render: (ip: string) => ip && ip !== 'unknown' ? <Text style={{ fontSize: 12 }}>{ip}</Text> : <Text type="secondary" style={{ fontSize: 12 }}>-</Text>,
    },
    {
      title: '系统/架构',
      key: 'os_arch',
      width: 120,
      render: (_: unknown, record: WorkerNode) => (
        <Space size={4}>
          <CloudServerOutlined />
          <Text style={{ fontSize: 12 }}>{record.os || '?'}/{record.arch || '?'}</Text>
        </Space>
      ),
    },
    {
      title: 'FFmpeg',
      dataIndex: 'ffmpeg_version',
      key: 'ffmpeg_version',
      width: 170,
      ellipsis: true,
      render: (v: string) => {
        if (!v || v === 'unknown') return <Text type="secondary" style={{ fontSize: 12 }}>未知</Text>;
        const short = v.length > 24 ? v.substring(0, 24) + '...' : v;
        return <Tooltip title={v}><Text style={{ fontSize: 12 }}>{short}</Text></Tooltip>;
      },
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      width: 130,
      render: (tags: string[]) => (
        <Space size={4} wrap>
          {(tags || []).length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>-</Text>
          ) : (
            (tags || []).map((tag) => <Tag key={tag} style={{ fontSize: 11, marginInlineEnd: 4 }}>{tag}</Tag>)
          )}
        </Space>
      ),
    },
    {
      title: '并发',
      key: 'concurrent',
      width: 110,
      render: (_: unknown, record: WorkerNode) => (
        <Text style={{ fontSize: 12 }}>
          {record.current_tasks || 0} / {record.max_concurrent || 2}
        </Text>
      ),
    },
    {
      title: 'CPU 分配',
      key: 'cpu_percent',
      width: 150,
      render: (_: unknown, record: WorkerNode) => (
        <Space size={2}>
          <Button
            type="text"
            size="small"
            icon={<MinusOutlined />}
            disabled={togglingId === record.node_id || (record.cpu_percent ?? 50) <= 1}
            onClick={() => adjustCpuPercent(record, -10)}
          />
          <Tooltip title="该节点切片时使用的 CPU 资源分配比例（可通过此处实时调整，下次任务生效）">
            <Text style={{ fontSize: 12 }}>{record.cpu_percent ?? 50}%</Text>
          </Tooltip>
          <Button
            type="text"
            size="small"
            icon={<PlusOutlined />}
            disabled={togglingId === record.node_id || (record.cpu_percent ?? 50) >= 100}
            onClick={() => adjustCpuPercent(record, 10)}
          />
        </Space>
      ),
    },
    {
      title: '运行进度',
      key: 'progress',
      width: 150,
      render: (_: unknown, record: WorkerNode) => {
        const running = record.current_tasks || 0;
        if (running <= 0) {
          return <Text type="secondary" style={{ fontSize: 12 }}>空闲</Text>;
        }
        // 优先展示 Redis 汇总的真实任务平均进度；无实时进度时用并发占用率兜底
        const pct = record.running_progress && record.running_progress > 0
          ? Math.round(record.running_progress)
          : Math.min(100, Math.round((running / (record.max_concurrent || 2)) * 100));
        return (
          <Space size={4} style={{ width: '100%' }}>
            <Progress percent={pct} size="small" style={{ width: 90, margin: 0 }} status="active" />
            <Text type="secondary" style={{ fontSize: 11 }}>{running} 任务</Text>
          </Space>
        );
      },
    },
    {
      title: '完成/失败',
      key: 'stats',
      width: 90,
      render: (_: unknown, record: WorkerNode) => (
        <Space size={3}>
          <Text type="success" style={{ fontSize: 12 }}>{record.total_tasks_completed || 0}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>/</Text>
          <Text type="danger" style={{ fontSize: 12 }}>{record.total_tasks_failed || 0}</Text>
        </Space>
      ),
    },
    {
      title: '最后心跳',
      dataIndex: 'last_heartbeat',
      key: 'last_heartbeat',
      width: 150,
      render: (t: string) => {
        if (!t) return <Text type="secondary" style={{ fontSize: 12 }}>-</Text>;
        const d = new Date(t);
        const now = new Date();
        const diffSec = (now.getTime() - d.getTime()) / 1000;
        const isRecent = diffSec < 60;
        return (
          <Text type={isRecent ? 'success' : 'warning'} style={{ fontSize: 12 }}>
            {d.toLocaleString('zh-CN')}
          </Text>
        );
      },
    },
    {
      title: '启停',
      key: 'enable',
      width: 90,
      render: (_: unknown, record: WorkerNode) => (
        <Switch
          size="small"
          checked={record.enabled !== false}
          loading={togglingId === record.node_id}
          onChange={(checked) => toggleWorker(record, checked)}
          checkedChildren="开"
          unCheckedChildren="关"
        />
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <ApiOutlined /> Worker 节点管理
          </Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<SyncOutlined />} loading={syncing} onClick={syncFromRedis}>
              从 Redis 同步
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => fetchWorkers()}>
              刷新
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="节点总数"
              value={workers.length}
              suffix={<Text type="secondary">个</Text>}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="启用节点"
              value={enabledCount}
              valueStyle={{ color: enabledCount > 0 ? '#52c41a' : '#999' }}
              prefix={<PoweroffOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="在线节点"
              value={onlineCount}
              valueStyle={{ color: onlineCount > 0 ? '#52c41a' : '#ff4d4f' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="任务运行中"
              value={totalRunning}
              suffix={<Text type="secondary">/ {totalConcurrent} 并发</Text>}
            />
          </Card>
        </Col>
      </Row>

      {/* 节点列表 */}
      <Card>
        <Table
          dataSource={workers}
          columns={columns}
          rowKey="node_id"
          loading={loading}
          pagination={false}
          size="small"
          rowClassName={() => 'worker-row-compact'}
        />
      </Card>
      <style>{`
        .worker-row-compact .ant-table-cell { padding: 8px 8px !important; }
      `}</style>
    </div>
  );
};

export default WorkersPage;