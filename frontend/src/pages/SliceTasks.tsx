import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  Card,
  Typography,
  Spin,
  Alert,
  Button,
  Space,
  Row,
  Col,
  Tag,
  Table,
  Breadcrumb,
  message,
  Descriptions,
  Empty,
} from 'antd';
import {
  ArrowLeftOutlined,
  ScissorOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
} from '@ant-design/icons';
import { sliceApi } from '../api/slice';
import TaskProgressComponent from '../components/TaskProgress';
import type { SliceTask } from '../types';
import {
  formatDateTime,
  formatRelativeTime,
  getStatusColor,
  getStatusLabel,
} from '../utils/format';

const { Title, Text } = Typography;

const SliceTasksPage: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const eid = Number(episodeId);

  const [tasks, setTasks] = useState<SliceTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<SliceTask | null>(null);

  useEffect(() => {
    fetchTasks();
  }, [eid]);

  const fetchTasks = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await sliceApi.getTasks(eid);
      setTasks(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取任务列表失败');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async (taskId: number) => {
    try {
      await sliceApi.cancelTask(taskId);
      message.success('任务已取消');
      fetchTasks();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '取消任务失败');
    }
  };

  const handleRetry = async (taskId: number) => {
    try {
      await sliceApi.retryFailed(taskId);
      message.success('已重试失败项');
      fetchTasks();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '重试失败');
    }
  };

  const columns = [
    {
      title: '任务ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      width: 150,
      render: (progress: number, record: SliceTask) => (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>{progress}%</span>
            <span>
              {record.completed_clips}/{record.total_clips}
            </span>
          </div>
        </div>
      ),
    },
    {
      title: '总剪辑数',
      dataIndex: 'total_clips',
      key: 'total_clips',
      width: 100,
    },
    {
      title: '已完成',
      dataIndex: 'completed_clips',
      key: 'completed_clips',
      width: 80,
      render: (val: number) => <span style={{ color: '#52c41a' }}>{val}</span>,
    },
    {
      title: '失败',
      dataIndex: 'failed_clips',
      key: 'failed_clips',
      width: 80,
      render: (val: number) => (
        <span style={{ color: val > 0 ? '#ff4d4f' : undefined }}>{val}</span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (date: string) => formatDateTime(date),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: SliceTask) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => setSelectedTask(record)}
          >
            详情
          </Button>
          {record.status === 'running' && (
            <Button
              type="link"
              size="small"
              danger
              icon={<PauseCircleOutlined />}
              onClick={() => handleCancel(record.id)}
            >
              取消
            </Button>
          )}
          {record.status === 'failed' && (
            <Button
              type="link"
              size="small"
              onClick={() => handleRetry(record.id)}
            >
              重试
            </Button>
          )}
        </Space>
      ),
    },
  ];

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

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">项目管理</Link> },
          { title: <Link to={`/episodes/${eid}`}>剧集详情</Link> },
          { title: '切片任务' },
        ]}
        style={{ marginBottom: 16 }}
      />

      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/episodes/${eid}`)}>
              返回
            </Button>
            <Title level={4} style={{ margin: 0 }}>
              切片任务 - 剧集 #{eid}
            </Title>
          </Space>
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={fetchTasks}>
            刷新
          </Button>
        </Col>
      </Row>

      {/* 选中任务的详情 */}
      {selectedTask && (
        <TaskProgressComponent
          task={selectedTask}
          visible
          onCancel={() => {
            handleCancel(selectedTask.id);
            setSelectedTask(null);
          }}
          onRetry={() => {
            handleRetry(selectedTask.id);
            setSelectedTask(null);
          }}
        />
      )}

      {/* 任务列表 */}
      <Card size="small" title="任务列表">
        {tasks.length > 0 ? (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={tasks}
            size="middle"
            pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 个任务` }}
            scroll={{ x: 900 }}
          />
        ) : (
          <Empty description="暂无切片任务" />
        )}
      </Card>
    </div>
  );
};

export default SliceTasksPage;