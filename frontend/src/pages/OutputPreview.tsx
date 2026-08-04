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
  Tooltip,
  Empty,
  Modal,
  List,
} from 'antd';
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  SendOutlined,
  EyeOutlined,
  FileOutlined,
} from '@ant-design/icons';
import { previewApi } from '../api/preview';
import type { SliceOutput, Publication } from '../types';
import {
  formatDateTime,
  formatDuration,
  formatFileSize,
  getStatusColor,
  getStatusLabel,
} from '../utils/format';

const { Title, Text } = Typography;

const OutputPreviewPage: React.FC = () => {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const eid = Number(episodeId);

  const [outputs, setOutputs] = useState<SliceOutput[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [publications, setPublications] = useState<Record<number, Publication[]>>({});

  useEffect(() => {
    fetchOutputs();
  }, [eid]);

  const fetchOutputs = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await previewApi.getOutputs(eid);
      setOutputs(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取成品列表失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async (outputId: number) => {
    try {
      const res = await previewApi.getDownloadUrl(outputId);
      const { url, filename } = res.data;
      // Trigger download via hidden link
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      message.success('开始下载');
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '下载失败');
    }
  };

  const handlePreview = async (outputId: number) => {
    try {
      const res = await previewApi.getStreamUrl(outputId);
      setPreviewUrl(res.data.url);
      setPreviewVisible(true);
    } catch (err: unknown) {
      message.error('获取预览地址失败');
    }
  };

  const handlePublish = async (outputId: number, platform: string) => {
    try {
      await previewApi.publish(outputId, platform);
      message.success('已发布到平台');
      fetchOutputs();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '发布失败');
    }
  };

  const handleShowPublications = async (outputId: number) => {
    try {
      const res = await previewApi.getPublications(outputId);
      setPublications((prev) => ({ ...prev, [outputId]: res.data }));
    } catch {
      message.error('获取发布状态失败');
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
    {
      title: '标签',
      dataIndex: 'label',
      key: 'label',
      width: 120,
      render: (label: string) => <Text strong>{label}</Text>,
    },
    {
      title: '时间范围',
      key: 'time_range',
      width: 180,
      render: (_: unknown, record: SliceOutput) => (
        <Text code>
          {formatDuration(record.start_time)} - {formatDuration(record.end_time)}
        </Text>
      ),
    },
    {
      title: '时长',
      dataIndex: 'duration',
      key: 'duration',
      width: 80,
      render: (duration: number) => formatDuration(duration),
    },
    {
      title: '文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (size: number) => formatFileSize(size),
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
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (date: string) => formatDateTime(date),
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      render: (_: unknown, record: SliceOutput) => (
        <Space size="small" wrap>
          <Tooltip title="预览">
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => handlePreview(record.id)}
            >
              预览
            </Button>
          </Tooltip>
          <Tooltip title="下载">
            <Button
              type="link"
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload(record.id)}
            >
              下载
            </Button>
          </Tooltip>
          <Tooltip title="发布状态">
            <Button
              type="link"
              size="small"
              icon={<SendOutlined />}
              onClick={() => handleShowPublications(record.id)}
            >
              发布
            </Button>
          </Tooltip>
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
          { title: '成品预览' },
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
              成品预览 - 剧集 #{eid}
            </Title>
          </Space>
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={fetchOutputs}>
            刷新
          </Button>
        </Col>
      </Row>

      <Card size="small" title="成品列表">
        {outputs.length > 0 ? (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={outputs}
            size="middle"
            pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 个成品` }}
            scroll={{ x: 1000 }}
          />
        ) : (
          <Empty description="暂无成品，请先完成切片任务" />
        )}
      </Card>

      {/* 预览 Modal */}
      <Modal
        title="视频预览"
        open={previewVisible}
        onCancel={() => {
          setPreviewVisible(false);
          setPreviewUrl(null);
        }}
        footer={null}
        width={800}
        destroyOnClose
      >
        {previewUrl && (
          <video
            controls
            style={{ width: '100%' }}
            src={previewUrl}
          >
            您的浏览器不支持视频播放
          </video>
        )}
      </Modal>

      {/* 发布状态 Modal */}
      {Object.keys(publications).length > 0 && (
        <Modal
          title="发布状态"
          open={Object.values(publications).some((p) => p.length > 0)}
          onCancel={() => setPublications({})}
          footer={null}
          width={500}
        >
          {Object.entries(publications).map(([outputId, pubs]) => (
            <div key={outputId}>
              <Text strong>成品 #{outputId}</Text>
              <List
                size="small"
                dataSource={pubs}
                renderItem={(pub) => (
                  <List.Item>
                    <Space>
                      <Tag>{pub.platform}</Tag>
                      <Tag color={getStatusColor(pub.status)}>
                        {getStatusLabel(pub.status)}
                      </Tag>
                      {pub.published_url && (
                        <a href={pub.published_url} target="_blank" rel="noreferrer">
                          查看链接
                        </a>
                      )}
                      {pub.error_message && (
                        <Text type="danger">{pub.error_message}</Text>
                      )}
                    </Space>
                  </List.Item>
                )}
              />
            </div>
          ))}
        </Modal>
      )}
    </div>
  );
};

export default OutputPreviewPage;