import React, { useEffect, useState } from 'react';
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Typography,
  Spin,
  Alert,
  Row,
  Col,
  Statistic,
  message,
  Upload,
  Breadcrumb,
  Descriptions,
  Progress,
  Empty,
  Tooltip,
} from 'antd';
import {
  UploadOutlined,
  ArrowLeftOutlined,
  VideoCameraOutlined,
  ScissorOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  InboxOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { projectApi } from '../api/projects';
import { uploadApi } from '../api/upload';
import type { Project, Episode } from '../types';
import {
  formatDateTime,
  formatDuration,
  formatFileSize,
  formatRelativeTime,
  getStatusColor,
  getStatusLabel,
} from '../utils/format';
import UploadProgress from '../components/UploadProgress';
import type { UploadFile } from 'antd';

const { Title, Text } = Typography;
const { Dragger } = Upload;

const ProjectDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const projectId = Number(id);

  const [project, setProject] = useState<Project | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Upload state
  const [uploadVisible, setUploadVisible] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [currentFile, setCurrentFile] = useState<File | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [uploadedFiles, setUploadedFiles] = useState<UploadFile[]>([]);

  useEffect(() => {
    fetchProjectDetail();
  }, [projectId]);

  const fetchProjectDetail = async () => {
    setLoading(true);
    setError(null);
    try {
      const [projectRes, episodesRes] = await Promise.all([
        projectApi.getById(projectId),
        // TODO: add episode list API
        Promise.resolve({ data: [] as Episode[] }),
      ]);
      setProject(projectRes.data);
      setEpisodes(episodesRes.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取项目详情失败');
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (file: File) => {
    setCurrentFile(file);
    setUploadVisible(true);
    setUploadStatus('uploading');
    setUploadProgress(0);
    setUploading(true);

    try {
      await uploadApi.uploadFile(projectId, file, (percent) => {
        setUploadProgress(percent);
      });
      setUploadStatus('success');
      setUploadedFiles((prev) => [...prev, { uid: String(Date.now()), name: file.name, status: 'done' } as UploadFile]);
      message.success(`${file.name} 上传成功`);
      fetchProjectDetail();
    } catch (err: unknown) {
      setUploadStatus('error');
      setErrorMessage(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const handleCancelUpload = () => {
    setUploadVisible(false);
    setUploadStatus('idle');
    setUploadProgress(0);
    setCurrentFile(null);
  };

  const handleCloseUpload = () => {
    setUploadVisible(false);
    setUploadStatus('idle');
    setUploadProgress(0);
    setCurrentFile(null);
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (error || !project) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const episodeColumns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (title: string, record: Episode) => (
        <Link to={`/episodes/${record.id}`}>
          <VideoCameraOutlined style={{ marginRight: 6 }} />
          {title}
        </Link>
      ),
    },
    {
      title: '时长',
      dataIndex: 'duration',
      key: 'duration',
      width: 100,
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
      width: 120,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: '选点数',
      dataIndex: 'clip_count',
      key: 'clip_count',
      width: 80,
    },
    {
      title: '区间数',
      dataIndex: 'interval_count',
      key: 'interval_count',
      width: 80,
    },
    {
      title: '切片数',
      dataIndex: 'slice_count',
      key: 'slice_count',
      width: 80,
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (date: string) => formatDateTime(date),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: Episode) => (
        <Button
          type="link"
          size="small"
          icon={<PlayCircleOutlined />}
          onClick={() => navigate(`/episodes/${record.id}`)}
        >
          处理
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">项目管理</Link> },
          { title: project.name },
        ]}
        style={{ marginBottom: 16 }}
      />

      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')}>
              返回
            </Button>
            <Title level={4} style={{ margin: 0 }}>
              {project.name}
            </Title>
          </Space>
        </Col>
        <Col>
          <Button
            type="primary"
            icon={<UploadOutlined />}
            onClick={() => setUploadVisible(true)}
          >
            上传视频
          </Button>
        </Col>
      </Row>

      {/* 项目信息 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
          <Descriptions.Item label="项目ID">{project.id}</Descriptions.Item>
          <Descriptions.Item label="目标平台">
            <Tag>{project.platform}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={getStatusColor(project.status)}>
              {getStatusLabel(project.status)}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {formatDateTime(project.created_at)}
          </Descriptions.Item>
          <Descriptions.Item label="描述" span={4}>
            {project.description || '暂无描述'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 统计 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="总剧集数" value={project.total_episodes} suffix="集" />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="已处理"
              value={project.processed_episodes}
              suffix={`/ ${project.total_episodes}`}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 剧集列表 */}
      <Card
        title="剧集列表"
        size="small"
        extra={
          <Text type="secondary">共 {episodes.length} 集</Text>
        }
      >
        {episodes.length > 0 ? (
          <Table
            rowKey="id"
            columns={episodeColumns}
            dataSource={episodes}
            size="middle"
            pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 集` }}
            scroll={{ x: 1000 }}
          />
        ) : (
          <Empty
            description="暂无剧集"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button
              type="primary"
              icon={<UploadOutlined />}
              onClick={() => setUploadVisible(true)}
            >
              上传视频文件
            </Button>
          </Empty>
        )}
      </Card>

      {/* 上传区域 */}
      {!episodes.length && (
        <Card size="small" style={{ marginTop: 16 }}>
          <Dragger
            showUploadList={false}
            beforeUpload={(file) => {
              handleUpload(file);
              return false;
            }}
            accept="video/*"
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽视频文件到此区域上传</p>
            <p className="ant-upload-hint">
              支持 MP4, AVI, MOV, MKV 等常见视频格式
            </p>
          </Dragger>
        </Card>
      )}

      <UploadProgress
        visible={uploadVisible}
        uploading={uploading}
        uploadProgress={uploadProgress}
        currentFile={currentFile}
        uploadStatus={uploadStatus}
        errorMessage={errorMessage}
        uploadedFiles={uploadedFiles}
        onCancel={handleCancelUpload}
        onClose={handleCloseUpload}
      />
    </div>
  );
};

export default ProjectDetail;