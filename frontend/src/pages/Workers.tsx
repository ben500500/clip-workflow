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
} from 'antd';
import {
  ReloadOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
  DesktopOutlined,
  CpuOutlined,
  ApiOutlined,
} from '@ant-design/icons';
import { sliceApi } from '../api/slice';
import type { WorkerNode } from '../types';

const { Title, Text } = Typography;

const WorkersPage: React.FC = () => {
  const [workers, setWorkers] = useState<WorkerNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

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

  useEffect(() => {
    fetchWorkers();
    const interval = setInterval(() => fetchWorkers(true), 10000);
    return () => clearInterval(interval);
  }, []);

  const onlineCount = workers.filter((w) => w.status === 'online').length;
  const totalConcurrent = workers.reduce((s, w) => s + (w.max_concurrent || 0), 0);
  const totalRunning = workers.reduce((s, w) => s + (w.current_tasks || 0), 0);
  const totalCompleted = workers.reduce((s, w) => s + (w.total_tasks_completed || 0), 0);

  const columns = [
    {
      title: '节点 ID',
      dataIndex: 'node_id',
      key: 'node_id',
      render: (id: string) => (
        <Space>
          <DesktopOutlined />
          <Text code>{id}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
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
      width: 140,
      render: (ip: string) => ip || '-',
    },
    {
      title: '系统/架构',
      key: 'os_arch',
      width: 140,
      render: (_: unknown, record: WorkerNode) => (
        <Space size={4}>
          <CpuOutlined />
          <Text>{record.os || '?'}/{record.arch || '?'}</Text>
        </Space>
      ),
    },
    {
      title: 'FFmpeg',
      dataIndex: 'ffmpeg_version',
      key: 'ffmpeg_version',
      width: 200,
      ellipsis: true,
      render: (v: string) => {
        if (!v || v === 'unknown') return <Text type="secondary">未知</Text>;
        const short = v.length > 30 ? v.substring(0, 30) + '...' : v;
        return <Tooltip title={v}>{short}</Tooltip>;
      },
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      width: 150,
      render: (tags: string[]) => (
        <Space size={4} wrap>
          {(tags || []).length === 0 ? (
            <Text type="secondary">-</Text>
          ) : (
            (tags || []).map((tag) => <Tag key={tag}>{tag}</Tag>)
          )}
        </Space>
      ),
    },
    {
      title: '并发',
      key: 'concurrent',
      width: 120,
      render: (_: unknown, record: WorkerNode) => (
        <Text>
          {record.current_tasks || 0} / {record.max_concurrent || 2}
        </Text>
      ),
    },
    {
      title: '完成/失败',
      key: 'stats',
      width: 130,
      render: (_: unknown, record: WorkerNode) => (
        <Space size={4}>
          <Text type="success">{record.total_tasks_completed || 0}</Text>
          <Text type="secondary">/</Text>
          <Text type="danger">{record.total_tasks_failed || 0}</Text>
        </Space>
      ),
    },
    {
      title: '最后心跳',
      dataIndex: 'last_heartbeat',
      key: 'last_heartbeat',
      width: 180,
      render: (t: string) => {
        if (!t) return <Text type="secondary">-</Text>;
        const d = new Date(t);
        const now = new Date();
        const diffSec = (now.getTime() - d.getTime()) / 1000;
        const isRecent = diffSec < 60;
        return (
          <Text type={isRecent ? 'success' : 'warning'}>
            {d.toLocaleString('zh-CN')}
          </Text>
        );
      },
    },
    {
      title: '启动时间',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 180,
      render: (t: string) => {
        if (!t) return <Text type="secondary">-</Text>;
        return new Date(t).toLocaleString('zh-CN');
      },
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
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="累计完成"
              value={totalCompleted}
              valueStyle={{ color: '#52c41a' }}
              suffix={<Text type="secondary">个</Text>}
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
        />
      </Card>
    </div>
  );
};

export default WorkersPage;