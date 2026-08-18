import React, { useEffect, useState, useRef } from 'react';
import {
  Card, Table, Button, Tag, Space, Typography, Spin, Alert, Row, Col, Statistic,
  message, Upload, Breadcrumb, Descriptions, Progress, Modal, Input, Checkbox, Popconfirm,
} from 'antd';
import { UploadOutlined, ArrowLeftOutlined, VideoCameraOutlined, DeleteOutlined, InboxOutlined, MergeCellsOutlined, EyeOutlined } from '@ant-design/icons';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { projectApi } from '../api/projects';
import { uploadApi } from '../api/upload';
import type { Episode, Project } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;
const { Dragger } = Upload;

const ProjectDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const projectId = id || '';

  const [project, setProject] = useState<Project | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  // ── 源视频预览：剧集列表中按需展开，点击「预览」后再加载在线播放链接 ──
  const [previewExpanded, setPreviewExpanded] = useState<Set<string>>(new Set());
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({});
  const [previewLoading, setPreviewLoading] = useState<Record<string, boolean>>({});
  const [previewErrors, setPreviewErrors] = useState<Record<string, string>>({});

  // ── 多视频合并上传（可选择是否合并成一个创建项目，项目名称由用户输入） ──
  const [multiModalOpen, setMultiModalOpen] = useState(false);
  const [multiFiles, setMultiFiles] = useState<File[]>([]);
  const [multiProjectName, setMultiProjectName] = useState('');
  const [multiMerge, setMultiMerge] = useState(true);
  const [multiUploading, setMultiUploading] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, []);

  const fetchData = async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [p, ep] = await Promise.all([
        projectApi.getById(projectId),
        projectApi.getEpisodes(projectId),
      ]);
      setProject(p);
      setEpisodes(ep.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取项目详情失败');
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    if (projectId) fetchData();
  }, [projectId]);

  const handleUpload = async (file: File) => {
    // 取消之前的上传
    if (abortRef.current) {
      abortRef.current.abort();
    }
    abortRef.current = new AbortController();
    
    setUploading(true);
    setUploadProgress(0);
    try {
      await uploadApi.uploadFile(projectId, file, (p) => {
        if (mountedRef.current) setUploadProgress(p);
      }, abortRef.current.signal);
      if (mountedRef.current) {
        message.success(`${file.name} 上传成功`);
        fetchData(true);
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'CanceledError') {
        message.info('上传已取消');
      } else if (mountedRef.current) {
        message.error(err instanceof Error ? err.message : '上传失败');
      }
    } finally {
      if (mountedRef.current) {
        setUploading(false);
      }
      abortRef.current = null;
    }
  };

  // ── 多视频批量上传：可合并成一个项目，项目名称由用户输入 ──
  const submitMultiUpload = async () => {
    if (multiFiles.length === 0) {
      message.warning('请先选择视频文件');
      return;
    }
    const name = multiProjectName.trim();
    if (!name) {
      message.warning('请输入项目名称');
      return;
    }
    setMultiUploading(true);
    setUploadProgress(0);
    try {
      const resp = await uploadApi.uploadMulti({
        projectName: name,
        files: multiFiles,
        merge: multiMerge,
        onProgress: (p) => setUploadProgress(p),
      });
      message.success(resp.message);
      setMultiModalOpen(false);
      setMultiFiles([]);
      setMultiProjectName('');
      setMultiMerge(true);
      // 合并上传创建的是新项目：跳转到新项目详情
      navigate(`/projects/${resp.project_id}`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '批量上传失败');
    } finally {
      setMultiUploading(false);
    }
  };

  // ── 源视频预览：展开/收起，展开时按需加载在线播放链接 ──
  const togglePreview = async (record: Episode, expanded?: boolean) => {
    const id = record.id;
    const willExpand = expanded ?? !previewExpanded.has(id);
    if (!willExpand) {
      // 收起：移除展开状态与链接，释放资源
      setPreviewExpanded((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      setPreviewUrls((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setPreviewErrors((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      return;
    }
    setPreviewExpanded((prev) => new Set(prev).add(id));
    if (previewUrls[id]) return;
    setPreviewLoading((prev) => ({ ...prev, [id]: true }));
    setPreviewErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    try {
      const res = await projectApi.getVideoUrl(id);
      if (mountedRef.current) setPreviewUrls((prev) => ({ ...prev, [id]: res.url }));
    } catch (err: unknown) {
      if (mountedRef.current) {
        setPreviewErrors((prev) => ({ ...prev, [id]: err instanceof Error ? err.message : '源视频链接获取失败' }));
      }
    } finally {
      if (mountedRef.current) setPreviewLoading((prev) => ({ ...prev, [id]: false }));
    }
  };

  const refreshPreview = (id: string) => {
    setPreviewUrls((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setPreviewErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setPreviewLoading((prev) => ({ ...prev, [id]: true }));
    projectApi
      .getVideoUrl(id)
      .then((res) => {
        if (mountedRef.current) setPreviewUrls((prev) => ({ ...prev, [id]: res.url }));
      })
      .catch((err: unknown) => {
        if (mountedRef.current) {
          setPreviewErrors((prev) => ({ ...prev, [id]: err instanceof Error ? err.message : '源视频链接获取失败' }));
        }
      })
      .finally(() => {
        if (mountedRef.current) setPreviewLoading((prev) => ({ ...prev, [id]: false }));
      });
  };

  const renderSourcePreview = (record: Episode) => {
    const id = record.id;
    if (!previewExpanded.has(id)) return null;
    if (!record.source_file_key) {
      return (
        <div style={{ padding: '16px 0', textAlign: 'center' }}>
          <Text type="secondary">该剧集没有源视频文件</Text>
        </div>
      );
    }
    if (previewLoading[id]) {
      return (
        <div style={{ padding: '28px 0', textAlign: 'center' }}>
          <Spin size="small" />
        </div>
      );
    }
    if (previewErrors[id]) {
      return (
        <div style={{ padding: '16px 0', textAlign: 'center' }}>
          <Space direction="vertical" size={8}>
            <Text type="danger">{previewErrors[id]}</Text>
            <Button size="small" type="primary" onClick={() => refreshPreview(id)}>重试</Button>
          </Space>
        </div>
      );
    }
    if (previewUrls[id]) {
      return (
        <video
          controls
          preload="metadata"
          src={previewUrls[id]}
          style={{ width: '100%', maxHeight: 380, background: '#000', borderRadius: 6 }}
          onError={() => {
            setPreviewUrls((prev) => {
              const next = { ...prev };
              delete next[id];
              return next;
            });
            setPreviewErrors((prev) => ({ ...prev, [id]: '源视频加载失败（链接可能已过期），可点击「刷新链接」重试' }));
          }}
        />
      );
    }
    return (
      <div style={{ padding: '16px 0', textAlign: 'center' }}>
        <Space direction="vertical" size={8}>
          <Text type="secondary">暂无预览</Text>
        </Space>
      </div>
    );
  };

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }
  if (error || !project) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const episodeColumns = [
    {
      title: '集数',
      dataIndex: 'episode_no',
      key: 'episode_no',
      width: 80,
      render: (v: number | null) => (v ?? '-'),
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (title: string, record: Episode) => (
        <Link to={`/episodes/${record.id}`}>
          <VideoCameraOutlined style={{ marginRight: 6 }} />
          {title || '(未命名)'}
        </Link>
      ),
    },
    {
      title: '时长',
      dataIndex: 'duration',
      key: 'duration',
      width: 100,
      render: (d: number) => formatDuration(d),
    },
    {
      title: '文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 110,
      render: (s: number) => formatFileSize(s),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (s: string) => <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>,
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (d: string) => formatDateTime(d),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: Episode) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => void togglePreview(record)}
          >
            {previewExpanded.has(record.id) ? '收起' : '预览'}
          </Button>
          <Button type="link" size="small" onClick={() => navigate(`/episodes/${record.id}`)}>处理</Button>
          <Popconfirm
            title="确定删除该剧集？"
            description="其下所有切片任务和产出文件将被一并清除，且无法恢复。"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={async () => {
              try {
                await projectApi.deleteEpisode(record.id);
                message.success('剧集已删除');
                fetchData(true);
              } catch (err: unknown) {
                message.error(err instanceof Error ? err.message : '删除失败');
              }
            }}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Breadcrumb style={{ marginBottom: 16 }} items={[{ title: <a onClick={() => navigate('/projects')}>短剧切片</a> }, { title: project.name }]} />
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')}>返回</Button>
            <Title level={4} style={{ margin: 0 }}>{project.name}</Title>
            <Tag color={getStatusColor(project.status)}>{getStatusLabel(project.status)}</Tag>
          </Space>
        </Col>
      </Row>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={4}>
          <Descriptions.Item label="描述">{project.description || '-'}</Descriptions.Item>
          <Descriptions.Item label="剧集数">{project.episode_count}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{formatDateTime(project.created_at)}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{formatDateTime(project.updated_at)}</Descriptions.Item>
        </Descriptions>
      </Card>
      {/* 上传正片：置于上方，占满整行 */}
      <Card size="small" title="上传正片" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Button
            type="primary"
            icon={<MergeCellsOutlined />}
            onClick={() => { setMultiMerge(true); setMultiModalOpen(true); }}
          >
            多视频上传（可合并成项目）
          </Button>
          <Dragger
            accept=".mp4,.avi,.mov,.mkv,.webm"
            showUploadList={false}
            beforeUpload={(file) => {
              handleUpload(file as File);
              return false;
            }}
            disabled={uploading}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽单个视频到此处上传（上传到当前项目）</p>
            {uploading && (
              uploadProgress < 0 ? (
                <Space size={4}><Spin size="small" /><Text type="secondary" style={{ fontSize: 12 }}>上传中…</Text></Space>
              ) : (
                <Progress percent={uploadProgress} size="small" status="active" />
              )
            )}
          </Dragger>
        </Space>
      </Card>
      {/* 剧集列表：位于上传正片下方 */}
      <Card size="small" title="剧集列表" extra={<Button size="small" icon={<UploadOutlined />} onClick={() => navigate('/settings')}>去系统设置</Button>}>
        <Table
          rowKey="id"
          columns={episodeColumns}
          dataSource={episodes}
          pagination={false}
          size="small"
          scroll={{ x: 920 }}
          expandable={{
            expandedRowKeys: Array.from(previewExpanded),
            onExpand: (expanded, record) => void togglePreview(record, expanded),
            expandedRowRender: (record) => renderSourcePreview(record),
            expandIconColumnIndex: -1,
          }}
        />
      </Card>

      {/* 多视频批量上传弹窗（可合并成一个视频创建项目，项目名称由用户输入） */}
      <Modal
        title="多视频上传（创建项目）"
        open={multiModalOpen}
        onOk={submitMultiUpload}
        onCancel={() => setMultiModalOpen(false)}
        okText="上传"
        cancelText="取消"
        confirmLoading={multiUploading}
        width={560}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong>项目名称</Text>
            <Input
              style={{ marginTop: 6 }}
              placeholder="请输入项目名称"
              value={multiProjectName}
              onChange={(e) => setMultiProjectName(e.target.value)}
            />
          </div>
          <Dragger
            accept=".mp4,.avi,.mov,.mkv,.webm"
            multiple
            beforeUpload={(file) => {
              setMultiFiles((prev) => {
                const exists = prev.some((f) => f.name === file.name && f.size === file.size);
                return exists ? prev : [...prev, file];
              });
              return false;
            }}
            fileList={multiFiles.map((f) => ({
              uid: `${f.name}-${f.size}`,
              name: f.name,
              status: 'done' as const,
            }))}
            onRemove={(file) => {
              setMultiFiles((prev) => prev.filter((f) => `${f.name}-${f.size}` !== file.uid));
            }}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽多个视频到此处</p>
          </Dragger>
          <Checkbox checked={multiMerge} onChange={(e) => setMultiMerge(e.target.checked)}>
            合并成一个视频（作为一个正片进入选点/切片处理）
          </Checkbox>
          {multiMerge && multiFiles.length > 1 && (
            <Alert type="info" showIcon message="合并将直接无损拼接（不转码），各视频需编码/分辨率/帧率一致；若素材不一致建议取消勾选，每个视频分别作为一集。" />
          )}
          {multiUploading && (
            uploadProgress < 0 ? (
              <Space size={4}><Spin size="small" /><Text type="secondary" style={{ fontSize: 12 }}>上传中…</Text></Space>
            ) : (
              <Progress percent={uploadProgress} size="small" status="active" />
            )
          )}
        </Space>
      </Modal>
    </div>
  );
};

export default ProjectDetail;
