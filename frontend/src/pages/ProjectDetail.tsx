import React, { useEffect, useState, useRef, useCallback } from 'react';
import {
  Card, Table, Button, Tag, Space, Typography, Spin, Alert, Row, Col, Statistic,
  message, Upload, Breadcrumb, Descriptions, Progress, Modal, Checkbox, Popconfirm, Input, Tabs, Switch, Select, Divider, InputNumber,
} from 'antd';
import { ArrowLeftOutlined, VideoCameraOutlined, DeleteOutlined, InboxOutlined, MergeCellsOutlined, EyeOutlined, PlayCircleOutlined, ThunderboltOutlined, PictureOutlined, ReloadOutlined, DownloadOutlined } from '@ant-design/icons';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { projectApi } from '../api/projects';
import type { ProjectOutputItem } from '../api/projects';
import { uploadApi } from '../api/upload';
import { sliceApi } from '../api/slice';
import { autoclipApi } from '../api/autoclip';
import type { Episode, EpisodeWorkflowItem, EpisodeWorkflowStage, Project, ProjectWorkflowStatus, WorkflowStageStatus } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;
const { Dragger } = Upload;

// 批量一键切片配置（面向已上传剧集，复用一键切片核心参数 + 视频封面）
interface BatchSliceConfig {
  mode: string;              // fast / dedupe
  maxClips: number;
  minScoreThreshold: number | null;
  minClipDuration: number | null;
  maxClipDuration: number | null;
  frameAnalysis: boolean;
  autoClipIfNeeded: boolean; // 无候选片段时自动补一轮 AI 选点
  vert2horizEnabled: boolean;
  subtitleEnabled: boolean;
  // 视频封面：选择图片作为视频首帧（MinIO key）
  coverImageKey: string | null;
  coverImageName: string | null;
}

const DEFAULT_BATCH_CONFIG: BatchSliceConfig = {
  mode: 'fast',
  maxClips: 10,
  minScoreThreshold: null,
  minClipDuration: null,
  maxClipDuration: null,
  frameAnalysis: true,
  autoClipIfNeeded: true,
  vert2horizEnabled: false,
  subtitleEnabled: false,
  coverImageKey: null,
  coverImageName: null,
};

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

  // ── 剧集多选 + 批量一键切片 ──
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [sliceModalOpen, setSliceModalOpen] = useState(false);
  const [batchConfig, setBatchConfig] = useState<BatchSliceConfig>({ ...DEFAULT_BATCH_CONFIG });
  const [batchSlicing, setBatchSlicing] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number; current: string } | null>(null);
  const [coverUploading, setCoverUploading] = useState(false);

  // ── 成品预览 Tab：项目下所有剧集的已完成切片产出 ──
  const [activeTab, setActiveTab] = useState('episodes');
  const [outputs, setOutputs] = useState<ProjectOutputItem[]>([]);
  const [outputsLoading, setOutputsLoading] = useState(false);
  const [outputsLoaded, setOutputsLoaded] = useState(false);
  const [previewModal, setPreviewModal] = useState(false);
  const [previewItem, setPreviewItem] = useState<ProjectOutputItem | null>(null);

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

  // ── 主上传区拖入多个视频：每个视频单独一个剧集 ──
  const handleMultiFileUpload = async (files: File[]) => {
    if (files.length === 0) return;
    if (!projectId) {
      message.warning('缺少当前项目信息，无法上传');
      return;
    }
    // 单文件走原有单文件快路径；多文件则每个视频单独一个剧集
    if (files.length === 1) {
      await handleUpload(files[0]);
      return;
    }
    // 取消进行中的单文件上传，避免并发冲突
    if (abortRef.current) {
      abortRef.current.abort();
    }
    setUploading(true);
    setUploadProgress(0);
    try {
      const resp = await uploadApi.uploadMulti({
        projectId,
        files,
        merge: false,
        onProgress: (p) => setUploadProgress(p),
      });
      if (mountedRef.current) {
        message.success(`已上传 ${resp.episodes.length} 个视频，每个单独作为一个剧集`);
        setSelectedRowKeys([]);
        await fetchData(true);
      }
    } catch (err: unknown) {
      if (mountedRef.current) {
        message.error(err instanceof Error ? err.message : '批量上传失败');
      }
    } finally {
      if (mountedRef.current) setUploading(false);
      abortRef.current = null;
    }
  };

  // ── 成品预览 Tab：拉取项目下所有剧集的已完成切片产出 ──
  const loadProjectOutputs = useCallback(async () => {
    setOutputsLoading(true);
    try {
      const data = await projectApi.getOutputs(projectId);
      if (mountedRef.current) {
        setOutputs(data.items);
        setOutputsLoaded(true);
      }
    } catch (err: unknown) {
      if (mountedRef.current) {
        message.error(err instanceof Error ? err.message : '获取成品列表失败');
      }
    } finally {
      if (mountedRef.current) setOutputsLoading(false);
    }
  }, [projectId]);

  // 切换到成品预览 Tab 时拉取一次（避免每次切换都请求）
  const handleTabChange = (key: string) => {
    setActiveTab(key);
    if (key === 'outputs' && !outputsLoaded) {
      loadProjectOutputs();
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

  // ── 视频封面：选择图片上传（作为视频首帧） ──
  const handleCoverUpload = async (file: File) => {
    setCoverUploading(true);
    try {
      const res = await sliceApi.uploadBadge(file);
      if (mountedRef.current) {
        setBatchConfig((prev) => ({
          ...prev,
          coverImageKey: res.file_key,
          coverImageName: res.file_name,
        }));
        message.success(`封面已上传：${res.file_name}`);
      }
    } catch (err: unknown) {
      if (mountedRef.current) {
        message.error(err instanceof Error ? err.message : '封面上传失败');
      }
    } finally {
      if (mountedRef.current) setCoverUploading(false);
    }
    return false;
  };

  // 对单个剧集执行一次「一键切片」（无候选时自动补选点，等价于剧集详情页的一键切片）
  const runOneClickSlice = async (episode: Episode) => {
    const cfg = batchConfig;
    // 无候选片段时自动补一轮 AI 选点
    if (cfg.autoClipIfNeeded) {
      try {
        const candidates = await autoclipApi.getCandidates(episode.id);
        if (candidates.length === 0) {
          await autoclipApi.run(episode.id, {
            max_clips: cfg.maxClips,
            min_score_threshold: cfg.minScoreThreshold ?? undefined,
            min_duration: cfg.minClipDuration ?? undefined,
            max_duration: cfg.maxClipDuration ?? undefined,
            frame_analysis: cfg.frameAnalysis,
          });
          let selected = false;
          for (let i = 0; i < 200 && !selected; i++) {
            await new Promise((r) => setTimeout(r, 3000));
            const p = await autoclipApi.progress(episode.id);
            if (p.status === 'completed') {
              selected = true;
            } else if (p.status === 'failed') {
              throw new Error(p.error_message || `${episode.title || episode.episode_no} AI 选点失败`);
            }
          }
          if (!selected) throw new Error(`${episode.title || episode.episode_no} AI 选点超时`);
          // 等候选真正落库
          for (let i = 0; i < 10; i++) {
            const after = await autoclipApi.getCandidates(episode.id);
            if (after.length > 0) break;
            await new Promise((r) => setTimeout(r, 2000));
          }
        }
      } catch (err: unknown) {
        // 选点失败不阻断：后端会自动回退整片切片
        if (err instanceof Error && /选点失败|选点超时/.test(err.message)) throw err;
      }
    }
    await sliceApi.run(episode.id, cfg.mode, {
      auto_accept_all: true,
      vert2horiz_enabled: cfg.vert2horizEnabled,
      subtitle_enabled: cfg.subtitleEnabled,
      // 视频封面：作为视频首帧
      cover_image_key: cfg.coverImageKey || undefined,
    });
  };

  // 批量一键切片：对选中的剧集逐个启动一键切片
  const runBatchSlice = async () => {
    const selected = episodes.filter((e) => selectedRowKeys.includes(e.id));
    if (selected.length === 0) return;
    setBatchSlicing(true);
    setBatchProgress({ done: 0, total: selected.length, current: '' });
    let done = 0;
    const failed: string[] = [];
    for (const ep of selected) {
      setBatchProgress({ done, total: selected.length, current: `${ep.title || ep.episode_no || ep.id}` });
      try {
        await runOneClickSlice(ep);
      } catch (err: unknown) {
        failed.push(ep.title || `第 ${ep.episode_no} 集`);
      }
      done += 1;
      setBatchProgress({ done, total: selected.length, current: '' });
    }
    setBatchSlicing(false);
    setBatchProgress(null);
    if (failed.length > 0) {
      message.warning(`部分剧集启动失败：${failed.join('、')}，请到对应剧集详情页重试`);
    } else {
      message.success(`已为 ${selected.length} 个剧集启动一键切片，完成后可到「成品预览」Tab 查看结果`);
    }
    setSliceModalOpen(false);
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
            multiple
            showUploadList={false}
            beforeUpload={(file, fileList) => {
              // antd 会为批量中的每个文件各调用一次 beforeUpload（fileList 为整批），
              // 只在第一个文件时触发一次整批上传，避免重复发起
              if (file === fileList[0]) {
                void handleMultiFileUpload(fileList.map((f) => f as unknown as File));
              }
              return false;
            }}
            disabled={uploading}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽视频到此处上传（可一次拖入多个，每个视频单独作为一个剧集）</p>
            <p className="ant-upload-hint">单个视频也会作为一个剧集；需要合并请在下方使用「多视频上传」</p>
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
      {/* 剧集列表 + 成品预览 Tab：位于上传正片下方 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          items={[
            {
              key: 'episodes',
              label: `剧集列表（${episodes.length}）`,
              children: (
                <>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Button
                      type="primary"
                      icon={<ThunderboltOutlined />}
                      disabled={selectedRowKeys.length === 0 || batchSlicing}
                      onClick={() => setSliceModalOpen(true)}
                    >
                      批量一键切片{selectedRowKeys.length > 0 ? `（${selectedRowKeys.length}）` : ''}
                    </Button>
                    {selectedRowKeys.length > 0 && (
                      <Button size="small" onClick={() => setSelectedRowKeys([])}>清空选择</Button>
                    )}
                    {batchProgress && (
                      <Space size={6}>
                        <Spin size="small" />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          正在为「{batchProgress.current}」启动一键切片 {batchProgress.done}/{batchProgress.total}…
                        </Text>
                      </Space>
                    )}
                  </Space>
                  <Table
                    rowKey="id"
                    columns={episodeColumns}
                    dataSource={episodes}
                    pagination={false}
                    size="small"
                    scroll={{ x: 920 }}
                    rowSelection={{
                      selectedRowKeys,
                      onChange: setSelectedRowKeys,
                      getCheckboxProps: (record: Episode) => ({ disabled: batchSlicing }),
                    }}
                    expandable={{
                      expandedRowKeys: Array.from(previewExpanded),
                      onExpand: (expanded, record) => void togglePreview(record, expanded),
                      expandedRowRender: (record) => renderSourcePreview(record),
                      expandIconColumnIndex: -1,
                    }}
                  />
                </>
              ),
            },
            {
              key: 'outputs',
              label: `成品预览（${outputsLoaded ? outputs.length : ''}）`,
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <Alert type="info" showIcon message="项目下所有剧集的已完成切片产出，可预览/下载。" />
                  {outputsLoading ? (
                    <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
                  ) : outputs.length === 0 ? (
                    <Text type="secondary">暂无成品。请先对剧集执行切片（可勾选多个剧集后使用「批量一键切片」），完成后即可在此预览。</Text>
                  ) : (
                    <Table
                      rowKey="output_id"
                      size="small"
                      pagination={{ pageSize: 10, showSizeChanger: false }}
                      dataSource={outputs}
                      columns={[
                        {
                          title: '所属剧集',
                          key: 'episode',
                          width: 180,
                          render: (_: unknown, r: ProjectOutputItem) => (
                            <Link to={`/episodes/${r.episode_id}`}>
                              {r.episode_title || (r.episode_no != null ? `第 ${r.episode_no} 集` : '(未命名剧集)')}
                            </Link>
                          ),
                        },
                        {
                          title: '成品',
                          dataIndex: 'file_name',
                          key: 'file_name',
                          ellipsis: true,
                          render: (v: string | null) => v || '(未命名)'
                        },
                        {
                          title: '模式',
                          dataIndex: 'mode',
                          key: 'mode',
                          width: 90,
                          render: (m: string | null) => (m ? <Tag>{m}</Tag> : '-'),
                        },
                        {
                          title: '时长',
                          dataIndex: 'duration',
                          key: 'duration',
                          width: 90,
                          render: (d: number | null) => (d != null ? formatDuration(d) : '-'),
                        },
                        {
                          title: '分辨率',
                          dataIndex: 'resolution',
                          key: 'resolution',
                          width: 100,
                          render: (v: string | null) => v || '-',
                        },
                        {
                          title: '大小',
                          dataIndex: 'file_size',
                          key: 'file_size',
                          width: 100,
                          render: (s: number | null) => (s != null ? formatFileSize(s) : '-'),
                        },
                        {
                          title: '生成时间',
                          dataIndex: 'created_at',
                          key: 'created_at',
                          width: 150,
                          render: (d: string) => formatDateTime(d),
                        },
                        {
                          title: '操作',
                          key: 'action',
                          width: 150,
                          render: (_: unknown, r: ProjectOutputItem) => (
                            <Space size="small">
                              <Button size="small" icon={<PlayCircleOutlined />} onClick={() => { setPreviewItem(r); setPreviewModal(true); }}>预览</Button>
                              {r.presigned_url && (
                                <a href={r.presigned_url} target="_blank" rel="noreferrer">下载</a>
                              )}
                            </Space>
                          ),
                        },
                      ]}
                    />
                  )}
                  {outputsLoaded && (
                    <Button size="small" icon={<ReloadOutlined />} onClick={() => loadProjectOutputs()}>刷新成品</Button>
                  )}
                </Space>
              ),
            },
          ]}
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

      {/* 批量一键切片配置弹窗 */}
      <Modal
        title={`批量一键切片（${selectedRowKeys.length} 个剧集）`}
        open={sliceModalOpen}
        onOk={() => void runBatchSlice()}
        onCancel={() => { if (!batchSlicing) setSliceModalOpen(false); }}
        okText="开始批量切片"
        cancelText="取消"
        confirmLoading={batchSlicing}
        width={640}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert type="info" showIcon message="将对选中的每个剧集执行一次「一键切片」（免审核直接出片）。没有候选片段的剧集会自动补一轮 AI 选点。" />

          {/* 视频封面：选择图片作为视频首帧 */}
          <Space direction="vertical" style={{ width: '100%' }} size={6}>
            <Text strong>视频封面（可选）</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>选择一张图片作为视频的首帧（成品开头会先展示封面画面）。不选择则直接按源视频首帧出片。</Text>
            <Space wrap>
              <Upload
                accept="image/*"
                showUploadList={false}
                beforeUpload={(file) => handleCoverUpload(file as File)}
                disabled={coverUploading}
              >
                <Button icon={<PictureOutlined />} loading={coverUploading}>选择封面图片</Button>
              </Upload>
              {batchConfig.coverImageKey && (
                <Tag closable onClose={() => setBatchConfig((prev) => ({ ...prev, coverImageKey: null, coverImageName: null }))}>
                  封面：{batchConfig.coverImageName || '已选择'}
                </Tag>
              )}
            </Space>
          </Space>

          <Divider style={{ margin: '4px 0' }} />

          <Space style={{ width: '100%' }} wrap>
            <Space>
              <Text style={{ fontSize: 13 }}>切片模式</Text>
              <Select
                size="small"
                style={{ width: 120 }}
                value={batchConfig.mode}
                onChange={(v) => setBatchConfig((prev) => ({ ...prev, mode: v }))}
                options={[
                  { value: 'fast', label: '普通切片' },
                  { value: 'dedupe', label: '去重切片' },
                ]}
              />
            </Space>
            <Space>
              <Text style={{ fontSize: 13 }}>AI 选点上限</Text>
              <InputNumber
                size="small"
                style={{ width: 80 }}
                min={1}
                value={batchConfig.maxClips}
                onChange={(v) => setBatchConfig((prev) => ({ ...prev, maxClips: v ?? 10 }))}
              />
            </Space>
          </Space>

          <Space style={{ width: '100%' }} wrap>
            <Switch
              checked={batchConfig.autoClipIfNeeded}
              onChange={(v) => setBatchConfig((prev) => ({ ...prev, autoClipIfNeeded: v }))}
            />
            <Text style={{ fontSize: 13 }}>无候选片段时自动补一轮 AI 选点</Text>
          </Space>
          <Space style={{ width: '100%' }} wrap>
            <Switch
              checked={batchConfig.vert2horizEnabled}
              onChange={(v) => setBatchConfig((prev) => ({ ...prev, vert2horizEnabled: v }))}
            />
            <Text style={{ fontSize: 13 }}>竖屏转横屏智能裁切</Text>
          </Space>
          <Space style={{ width: '100%' }} wrap>
            <Switch
              checked={batchConfig.subtitleEnabled}
              onChange={(v) => setBatchConfig((prev) => ({ ...prev, subtitleEnabled: v }))}
            />
            <Text style={{ fontSize: 13 }}>ASR 字幕烧录</Text>
          </Space>

          {batchProgress && batchSlicing && (
            <Progress percent={Math.round((batchProgress.done / batchProgress.total) * 100)} size="small" status="active" />
          )}
        </Space>
      </Modal>

      {/* 成品预览弹窗 */}
      <Modal
        title={previewItem ? `成品预览 · ${previewItem.file_name || ''}` : '成品预览'}
        open={previewModal}
        onCancel={() => setPreviewModal(false)}
        footer={previewItem?.presigned_url ? <a href={previewItem.presigned_url} target="_blank" rel="noreferrer"><Button type="primary" icon={<DownloadOutlined />}>下载</Button></a> : null}
        width={820}
        destroyOnClose
      >
        {previewItem?.presigned_url ? (
          <video
            controls
            preload="metadata"
            src={previewItem.presigned_url}
            style={{ width: '100%', maxHeight: 460, background: '#000', borderRadius: 6 }}
          />
        ) : (
          <Text type="secondary">该成品暂无可用预览地址（链接可能已过期），请尝试重新加载列表。</Text>
        )}
      </Modal>
    </div>
  );
};

export default ProjectDetail;
