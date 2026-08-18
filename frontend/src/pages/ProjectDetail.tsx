import React, { useEffect, useState, useRef } from 'react';
import {
  Card, Table, Button, Tag, Space, Typography, Spin, Alert, Row, Col, Statistic,
  message, Upload, Breadcrumb, Descriptions, Progress, Modal, Checkbox, Popconfirm, Input,
} from 'antd';
import { UploadOutlined, ArrowLeftOutlined, VideoCameraOutlined, DeleteOutlined, InboxOutlined, MergeCellsOutlined, EyeOutlined, ReloadOutlined } from '@ant-design/icons';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { projectApi } from '../api/projects';
import { uploadApi } from '../api/upload';
import type { Episode, EpisodeWorkflowItem, EpisodeWorkflowStage, Project, ProjectWorkflowStatus, WorkflowStageStatus } from '../types';
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

  // ── 项目工作流状态聚合（P2-4） ──
  const [workflow, setWorkflow] = useState<ProjectWorkflowStatus | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);

  // ── 源视频预览：剧集列表中按需展开，点击「预览」后再加载在线播放链接 ──
  const [previewExpanded, setPreviewExpanded] = useState<Set<string>>(new Set());
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({});
  const [previewLoading, setPreviewLoading] = useState<Record<string, boolean>>({});
  const [previewErrors, setPreviewErrors] = useState<Record<string, string>>({});

  // ── 多视频合并上传（可选择是否合并成一个在当前项目下创建剧集） ──
  const [multiModalOpen, setMultiModalOpen] = useState(false);
  const [multiFiles, setMultiFiles] = useState<File[]>([]);
  const [multiMerge, setMultiMerge] = useState(true);
  const [multiTitle, setMultiTitle] = useState('');
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

  // P2-4 拉取项目工作流状态聚合
  const fetchWorkflow = async (silent = false) => {
    if (!silent) setWorkflowLoading(true);
    setWorkflowError(null);
    try {
      const data = await projectApi.getWorkflowStatus(projectId);
      if (mountedRef.current) setWorkflow(data);
    } catch (err: unknown) {
      if (mountedRef.current) {
        setWorkflowError(err instanceof Error ? err.message : '获取工作流状态失败');
      }
    } finally {
      if (mountedRef.current) setWorkflowLoading(false);
    }
  };

  useEffect(() => {
    if (projectId) {
      fetchData();
      fetchWorkflow();
    }
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

  // ── 多视频批量上传：在当前项目下创建剧集，不再新创建项目 ──
  const submitMultiUpload = async () => {
    if (multiFiles.length === 0) {
      message.warning('请先选择视频文件');
      return;
    }
    if (!projectId) {
      message.warning('缺少当前项目信息，无法上传');
      return;
    }
    setMultiUploading(true);
    setUploadProgress(0);
    try {
      const resp = await uploadApi.uploadMulti({
        projectId,
        files: multiFiles,
        merge: multiMerge,
        title: multiTitle.trim() || undefined,
        onProgress: (p) => setUploadProgress(p),
      });
      message.success(resp.message);
      setMultiModalOpen(false);
      setMultiFiles([]);
      setMultiMerge(true);
      setMultiTitle('');
      // 在当前项目下创建剧集，不跳转新项目，直接刷新当前项目的剧集列表
      await fetchData(true);
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

  // 工作流阶段标签（选点/检测/切片）
  const workflowStageColor = (s: WorkflowStageStatus | 'empty'): string => {
    switch (s) {
      case 'completed': return 'green';
      case 'running': return 'blue';
      case 'failed': return 'red';
      case 'pending': return 'default';
      case 'empty': return 'default';
      default: return 'orange';
    }
  };
  const workflowStageLabel = (s: WorkflowStageStatus): string => {
    switch (s) {
      case 'completed': return '已完成';
      case 'running': return '进行中';
      case 'failed': return '失败';
      case 'pending': return '待处理';
      default: return '未知';
    }
  };
  const workflowOverallLabel = (s: WorkflowStageStatus): string => {
    switch (s) {
      case 'completed': return '全部完成';
      case 'running': return '进行中';
      case 'failed': return '存在失败';
      case 'pending': return '待处理';
      case 'empty': return '暂无剧集';
      default: return '未知';
    }
  };

  // 工作流聚合看板渲染
  const renderWorkflowBoard = () => {
    if (!workflow) return null;
    const stageNames = ['选点', '区间检测', '切片'];
    const stageColors = ['blue', 'cyan', 'purple'];
    return (
      <Card
        size="small"
        title={
          <Space>
            <span>项目工作流状态</span>
            <Tag color={workflowStageColor(workflow.overall.status)}>{workflowOverallLabel(workflow.overall.status)}</Tag>
            {workflow.overall.progress > 0 && <Text type="secondary" style={{ fontSize: 12 }}>{workflow.overall.progress.toFixed(0)}%</Text>}
          </Space>
        }
        extra={
          <Space size="small">
            <Progress percent={Math.round(workflow.overall.progress)} size="small" style={{ width: 140 }} />
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void fetchWorkflow(true)}>刷新</Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        {workflowError ? (
          <Alert type="warning" showIcon message="工作流状态加载失败" description={workflowError} action={<Button size="small" onClick={() => void fetchWorkflow(true)}>重试</Button>} />
        ) : workflowLoading && !workflow ? (
          <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {/* 各阶段完成统计 */}
            <Row gutter={16}>
              {stageNames.map((name, i) => {
                const stageKey = ['autoclip', 'detect', 'slice'][i] as keyof typeof workflow.overall.stages;
                return (
                  <Col span={8} key={name}>
                    <Statistic
                      title={`${name}（${stageColors[i]}）`}
                      value={workflow.overall.stages[stageKey].completed}
                      suffix={`/ ${workflow.overall.stages[stageKey].total}`}
                      valueStyle={{ fontSize: 18 }}
                    />
                  </Col>
                );
              })}
            </Row>
            {/* 各剧集工作流明细表 */}
            {workflow.episodes.length === 0 ? (
              <Text type="secondary">暂无剧集，上传视频后即可在此查看选点/检测/切片三阶段进度。</Text>
            ) : (
              <Table
                rowKey={(r) => r.episode.id}
                size="small"
                pagination={false}
                dataSource={workflow.episodes}
                scroll={{ x: 720 }}
                columns={[
                  {
                    title: '剧集',
                    dataIndex: ['episode', 'episode_no'],
                    width: 70,
                    render: (v: number | null) => (v ?? '-'),
                  },
                  {
                    title: '标题',
                    dataIndex: ['episode', 'title'],
                    render: (v: string | null) => v || '(未命名)',
                  },
                  {
                    title: '总状态',
                    dataIndex: 'status',
                    width: 90,
                    render: (s: WorkflowStageStatus) => (
                      <Tag color={workflowStageColor(s)}>{workflowStageLabel(s)}</Tag>
                    ),
                  },
                  {
                    title: '选点',
                    dataIndex: ['stages', 'autoclip'],
                    width: 90,
                    render: (st: EpisodeWorkflowStage) => (
                      <Space size={4}>
                        <Tag color={workflowStageColor(st.status)}>{workflowStageLabel(st.status)}</Tag>
                        {st.run_count ? <Text type="secondary" style={{ fontSize: 12 }}>×{st.run_count}</Text> : null}
                      </Space>
                    ),
                  },
                  {
                    title: '区间检测',
                    dataIndex: ['stages', 'detect'],
                    width: 100,
                    render: (st: EpisodeWorkflowStage) => (
                      <Tag color={workflowStageColor(st.status)}>{workflowStageLabel(st.status)}</Tag>
                    ),
                  },
                  {
                    title: '切片',
                    dataIndex: ['stages', 'slice'],
                    width: 100,
                    render: (st: EpisodeWorkflowStage) => (
                      <Space size={4}>
                        <Tag color={workflowStageColor(st.status)}>{workflowStageLabel(st.status)}</Tag>
                        {st.output_count ? <Text type="secondary" style={{ fontSize: 12 }}>{st.output_count}产出</Text> : null}
                      </Space>
                    ),
                  },
                  {
                    title: '进度',
                    dataIndex: ['stages', 'slice', 'progress'],
                    width: 120,
                    render: (_v: number, record: EpisodeWorkflowItem) => {
                      const stages = [record.stages.autoclip, record.stages.detect, record.stages.slice];
                      const running = stages.find((s) => s.status === 'running');
                      const progress = running ? running.progress : (record.status === 'completed' ? 100 : 0);
                      return <Progress percent={Math.round(progress)} size="small" />;
                    },
                  },
                ]}
              />
            )}
          </Space>
        )}
      </Card>
    );
  };

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
      {/* 工作流状态聚合看板（P2-4） */}
      {renderWorkflowBoard()}
      {/* 上传正片：置于上方，占满整行 */}
      <Card size="small" title="上传正片" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Button
            type="primary"
            icon={<MergeCellsOutlined />}
            onClick={() => { setMultiMerge(true); setMultiModalOpen(true); }}
          >
            多视频上传（合并成剧集）
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

      {/* 多视频批量上传弹窗（在当前项目下创建剧集） */}
      <Modal
        title="多视频上传（当前项目下创建剧集）"
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
          <Alert type="info" showIcon message={`上传后将作为「${project?.name || '当前项目'}」下的剧集，不会新创建项目。`} />
          <Space direction="vertical" style={{ width: '100%' }} size={2}>
            <Text type="secondary" style={{ fontSize: 13 }}>标题（可选）</Text>
            <Input
              placeholder="勾选合并时作为合并剧集标题；未勾选时作为剧集标题前缀（自动追加 第01集/第02集…）"
              value={multiTitle}
              onChange={(e) => setMultiTitle(e.target.value)}
              maxLength={100}
              allowClear
            />
          </Space>
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
