import React, { useEffect, useRef, useState } from 'react';
import {
  Card, Button, Space, Typography, Spin, Alert, Breadcrumb, Descriptions, Tag, message, Select, Row, Col, Progress,
  Steps,
} from 'antd';
import {
  ArrowLeftOutlined, ThunderboltOutlined, RadarChartOutlined, ScissorOutlined,
  CheckCircleOutlined, ClockCircleOutlined, InfoCircleOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import { autoclipApi } from '../api/autoclip';
import { intervalApi } from '../api/intervals';
import { sliceApi } from '../api/slice';
import type { Episode } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text, Paragraph } = Typography;

// ─── 切片模式说明 ─────────────────────────────────────
const SLICE_MODE_HELP: Record<string, { label: string; desc: string; detail: string }> = {
  fast: {
    label: '快速模式',
    desc: '直接按选点结果切割，不做去重处理',
    detail: '根据已通过的片段审核结果，直接将视频切割成多个片段输出。速度最快，但不会处理重复内容，适合初次出片测试。',
  },
  dedupe: {
    label: '去重模式',
    desc: '切割时进行画面去重处理',
    detail: '在切割的同时对每个片段进行画面相似度检测，去除重复度高的内容片段。适用于需要批量发布到多个平台的场景，减少重复内容被平台限流的风险。',
  },
  scrub: {
    label: '挖洞模式',
    desc: '在去重基础上随机挖洞',
    detail: '在去重模式的基础上，进一步对片段中随机位置进行微小的画面挖洞处理（替换为纯色帧），使每个输出片段的指纹更加独特。适合高频发布场景，有效降低平台查重处罚。',
  },
};

// ─── 工作流步骤定义 ───────────────────────────────────
const WORKFLOW_STEPS = [
  { key: 'upload', title: '上传视频', description: '上传原始视频素材' },
  { key: 'autoclip', title: 'AI 智能选点', description: '自动分析并推荐精彩片段' },
  { key: 'review', title: '片段审核', description: '审核并调整选点结果' },
  { key: 'intervals', title: '区间检测', description: '检测片尾/静止/水印区域' },
  { key: 'slice', title: '切片执行', description: '按配置切割输出成品' },
  { key: 'preview', title: '成品预览', description: '预览并下载切片结果' },
];

const EpisodeDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const episodeId = id || '';

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detectMode, setDetectMode] = useState('credits');
  const [sliceMode, setSliceMode] = useState('fast');
  const [autoclipProgress, setAutoclipProgress] = useState<{ status: string; progress: number; message: string } | null>(null);
  const [autoclipRunning, setAutoclipRunning] = useState(false);
  const [detectRunning, setDetectRunning] = useState(false);
  const [detectProgress, setDetectProgress] = useState<{ status: string; progress: number; message: string } | null>(null);
  const [sliceRunning, setSliceRunning] = useState(false);

  const autoclipTimerRef = useRef<number | null>(null);
  const detectTimerRef = useRef<number | null>(null);
  const sliceTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (autoclipTimerRef.current) {
        window.clearInterval(autoclipTimerRef.current);
      }
      if (detectTimerRef.current) {
        window.clearTimeout(detectTimerRef.current);
      }
      if (sliceTimerRef.current) {
        window.clearTimeout(sliceTimerRef.current);
      }
    };
  }, []);

  const fetchEpisode = () => {
    setLoading(true);
    projectApi
      .getEpisode(episodeId)
      .then((data) => {
        if (mountedRef.current) setEpisode(data);
      })
      .catch((err: unknown) => {
        if (mountedRef.current) setError(err instanceof Error ? err.message : '获取剧集失败');
      })
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
  };

  useEffect(() => {
    if (episodeId) fetchEpisode();
  }, [episodeId]);

  // 计算当前工作流进度
  const getCurrentStep = (): number => {
    if (!episode) return 0;
    const status = episode.status;
    // uploaded -> clips_detected -> intervals_detected -> slicing -> completed
    if (status === 'uploaded') return 1;
    if (status === 'clips_detected') return 2;
    if (status === 'intervals_detected') return 3;
    if (status === 'slicing') return 4;
    if (status === 'completed') return 5;
    return 1;
  };

  // ─── 选点任务恢复轮询 ───────────────────────────────
  const resumeAutoclipPolling = async () => {
    try {
      const p = await autoclipApi.progress(episodeId);
      if (p && (p.status === 'pending' || p.status === 'processing' || p.status === 'running')) {
        setAutoclipRunning(true);
        setAutoclipProgress(p);
        autoclipTimerRef.current = window.setInterval(async () => {
          try {
            const prog = await autoclipApi.progress(episodeId);
            if (!mountedRef.current) {
              if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
              return;
            }
            setAutoclipProgress(prog);
            if (prog.status === 'completed' || prog.status === 'failed') {
              if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
              autoclipTimerRef.current = null;
              setAutoclipRunning(false);
              if (prog.status === 'completed') {
                message.success('选点分析已完成！请前往「片段审核」查看并确认选点结果');
              } else {
                message.error('选点分析失败');
              }
              fetchEpisode();
            }
          } catch {
            if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
            autoclipTimerRef.current = null;
            if (mountedRef.current) setAutoclipRunning(false);
          }
        }, 3000);
      } else if (p && (p.status === 'completed' || p.status === 'failed')) {
        setAutoclipProgress(p);
      }
    } catch {
      // 没有运行中的任务，忽略
    }
  };

  // ─── 区间检测任务轮询 ───────────────────────────────
  const resumeDetectPolling = async () => {
    try {
      const p = await intervalApi.progress(episodeId);
      if (p && (p.status === 'pending' || p.status === 'processing' || p.status === 'running')) {
        setDetectRunning(true);
        setDetectProgress(p);
        detectTimerRef.current = window.setInterval(async () => {
          try {
            const prog = await intervalApi.progress(episodeId);
            if (!mountedRef.current) {
              if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
              return;
            }
            setDetectProgress(prog);
            if (prog.status === 'completed' || prog.status === 'failed') {
              if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
              detectTimerRef.current = null;
              setDetectRunning(false);
              if (prog.status === 'completed') {
                message.success('区间检测已完成！检测结果已自动保存');
              } else {
                message.error('区间检测失败');
              }
              fetchEpisode();
            }
          } catch {
            if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
            detectTimerRef.current = null;
            if (mountedRef.current) setDetectRunning(false);
          }
        }, 3000);
      } else if (p && (p.status === 'completed' || p.status === 'failed')) {
        setDetectProgress(p);
      }
    } catch {
      // 没有运行中的任务，忽略
    }
  };

  useEffect(() => {
    if (episodeId && episode) {
      resumeAutoclipPolling();
      resumeDetectPolling();
    }
  }, [episodeId, episode?.id]);

  // ─── 启动选点 ───────────────────────────────────────
  const runAutoClip = async () => {
    setAutoclipRunning(true);
    setAutoclipProgress({ status: 'pending', progress: 0, message: '正在启动选点任务…' });
    try {
      const res = await autoclipApi.run(episodeId, {});
      message.success(res.message);
      autoclipTimerRef.current = window.setInterval(async () => {
        try {
          const p = await autoclipApi.progress(episodeId);
          if (!mountedRef.current) {
            if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
            return;
          }
          setAutoclipProgress(p);
          if (p.status === 'completed' || p.status === 'failed') {
            if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
            autoclipTimerRef.current = null;
            setAutoclipRunning(false);
            if (p.status === 'completed') {
              message.success('选点分析已完成！请前往「片段审核」查看并确认选点结果');
            } else {
              message.error('选点分析失败');
            }
            fetchEpisode();
          }
        } catch {
          if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
          autoclipTimerRef.current = null;
          if (mountedRef.current) setAutoclipRunning(false);
        }
      }, 3000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动选点失败');
      setAutoclipRunning(false);
      setAutoclipProgress(null);
    }
  };

  // ─── 启动区间检测 ───────────────────────────────────
  const runDetect = async () => {
    setDetectRunning(true);
    setDetectProgress({ status: 'running', progress: 10, message: '正在启动区间检测任务，请稍候…' });
    try {
      const res = await intervalApi.detect(episodeId, detectMode, {});
      // 更新为更详细的反馈信息，提示用户正在处理中
      setDetectProgress({ status: 'running', progress: 20, message: `检测任务已提交（${detectMode === 'credits' ? '片尾字幕' : detectMode === 'static' ? '静止画面' : '水印'}模式），正在分析视频内容…` });
      message.success('检测任务已成功提交，正在后台分析中');
      detectTimerRef.current = window.setInterval(async () => {
        try {
          const p = await intervalApi.progress(episodeId);
          if (!mountedRef.current) {
            if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
            return;
          }
          if (p) {
            setDetectProgress(p);
            if (p.status === 'completed' || p.status === 'failed') {
              if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
              detectTimerRef.current = null;
              setDetectRunning(false);
              if (p.status === 'completed') {
                message.success('区间检测已完成！检测结果已自动保存');
              } else {
                message.error('区间检测失败');
              }
              fetchEpisode();
            }
          }
        } catch {
          if (detectTimerRef.current) window.clearInterval(detectTimerRef.current);
          detectTimerRef.current = null;
          if (mountedRef.current) setDetectRunning(false);
        }
      }, 3000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动检测失败');
      setDetectRunning(false);
      setDetectProgress(null);
    }
  };

  // ─── 启动切片 ───────────────────────────────────────
  const runSlice = async () => {
    setSliceRunning(true);
    try {
      const res = await sliceApi.run(episodeId, sliceMode, {});
      message.success(res.message);
      sliceTimerRef.current = window.setTimeout(() => {
        sliceTimerRef.current = null;
        if (mountedRef.current) {
          fetchEpisode();
          setSliceRunning(false);
        }
      }, 2000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动切片失败');
      setSliceRunning(false);
    }
  };

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />;
  }
  if (error || !episode) {
    return <Alert type="error" message="加载失败" description={error} showIcon />;
  }

  const currentStep = getCurrentStep();

  // ─── 工作流步骤引导提示 ─────────────────────────────
  const workflowGuide = () => {
    if (episode.status === 'clips_detected') {
      // 选点完成→引导去审核
      return (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          message="选点已完成！下一步操作"
          description={
            <Space direction="vertical" size={4}>
              <Text>1. 点击下方「片段审核」查看 AI 推荐的精彩片段，审核通过或拒绝每个片段</Text>
              <Text>2. 审核完成后，可进行「区间检测」识别需要裁剪的区域（片尾字幕、静止画面等）</Text>
              <Text>3. 最后选择切片模式，执行「切片」生成成品视频</Text>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      );
    }
    if (episode.status === 'intervals_detected') {
      // 区间检测完成→引导去切片
      return (
        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          message="区间检测已完成！下一步操作"
          description={
            <Space direction="vertical" size={4}>
              <Text>1. 区间检测结果已自动保存，您可以在「区间检测」工作台查看详情</Text>
              <Text>2. 接下来选择下方的「切片模式」，然后点击「开始切片」生成成品视频</Text>
              <Text>3. 切片完成后，前往「成品预览」查看和下载结果</Text>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      );
    }
    if (episode.status === 'uploaded') {
      // 刚上传完成→引导去选点
      return (
        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          message="视频已上传，下一步操作"
          description={
            <Space direction="vertical" size={4}>
              <Text>1. 点击下方「AI 智能选点」启动自动分析，系统将推荐精彩片段</Text>
              <Text>2. 选点完成后，在「片段审核」中审核和调整选点结果</Text>
              <Text>3. 之后依次进行「区间检测」→「切片执行」→「成品预览」</Text>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      );
    }
    return null;
  };

  const actions: { title: string; node: React.ReactNode }[] = [
    {
      title: 'AI 智能选点',
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={autoclipRunning} onClick={runAutoClip} block>
            启动选点
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            自动分析视频内容，推荐精彩片段作为切片候选
          </Text>
        </Space>
      ),
    },
    {
      title: '通用区间检测',
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space>
            <Select value={detectMode} onChange={setDetectMode} style={{ width: 120 }}
              options={[
                { value: 'credits', label: '片尾字幕' },
                { value: 'static', label: '静止画面' },
                { value: 'watermark', label: '水印' },
              ]}
            />
            <Button icon={<RadarChartOutlined />} loading={detectRunning} onClick={runDetect}>开始检测</Button>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            检测视频中的特定区间（片尾字幕/静止画面/水印），检测结果将用于切片时自动裁剪
          </Text>
        </Space>
      ),
    },
    {
      title: '切片执行',
      node: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space>
            <Select value={sliceMode} onChange={setSliceMode} style={{ width: 120 }}
              options={[
                { value: 'fast', label: '快速模式' },
                { value: 'dedupe', label: '去重模式' },
                { value: 'scrub', label: '挖洞模式' },
              ]}
            />
            <Button icon={<ScissorOutlined />} loading={sliceRunning} onClick={runSlice}>开始切片</Button>
          </Space>
          {/* 切片模式详细说明 */}
          <Card size="small" style={{ background: '#f0f5ff', border: '1px solid #d6e4ff', width: '100%' }}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text strong style={{ fontSize: 13, color: '#1d39c4' }}>
                <InfoCircleOutlined style={{ marginRight: 6 }} />
                {SLICE_MODE_HELP[sliceMode]?.label}
              </Text>
              <Text style={{ fontSize: 13, color: '#1d39c4' }}>
                {SLICE_MODE_HELP[sliceMode]?.desc}
              </Text>
              <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.6 }}>
                {SLICE_MODE_HELP[sliceMode]?.detail}
              </Text>
            </Space>
          </Card>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Breadcrumb style={{ marginBottom: 16 }}
        items={[
          { title: <a onClick={() => navigate('/projects')}>项目管理</a> },
          { title: <a onClick={() => navigate(`/projects/${episode.project_id}`)}>项目详情</a> },
          { title: episode.title || episode.id },
        ]}
      />
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/projects/${episode.project_id}`)}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>{episode.title || '(未命名剧集)'}</Title>
        <Tag color={getStatusColor(episode.status)}>{getStatusLabel(episode.status)}</Tag>
      </Space>

      {/* 工作流步骤条 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Steps
          current={currentStep}
          size="small"
          items={WORKFLOW_STEPS.map((step, idx) => ({
            title: step.title,
            description: step.description,
            status: idx < currentStep ? 'finish' : idx === currentStep ? 'process' : 'wait',
            icon: idx < currentStep ? <CheckCircleOutlined /> : <ClockCircleOutlined />,
          }))}
        />
      </Card>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={4}>
          <Descriptions.Item label="集数">{episode.episode_no ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="时长">{formatDuration(episode.duration)}</Descriptions.Item>
          <Descriptions.Item label="文件大小">{formatFileSize(episode.file_size)}</Descriptions.Item>
          <Descriptions.Item label="上传时间">{formatDateTime(episode.created_at)}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 工作流步骤引导提示 */}
      {workflowGuide()}

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {actions.map((a) => (
          <Col xs={24} md={8} key={a.title}>
            <Card size="small" title={a.title}>{a.node}</Card>
          </Col>
        ))}
      </Row>

      {/* 选点进度 */}
      {autoclipProgress && (
        <Card size="small" style={{ marginBottom: 16 }} title="选点进度">
          <Progress
            percent={autoclipProgress.progress}
            status={autoclipProgress.status === 'failed' ? 'exception' : 'active'}
          />
          <Text type="secondary">{autoclipProgress.message}</Text>
        </Card>
      )}

      {/* 区间检测进度 */}
      {detectProgress && (
        <Card size="small" style={{ marginBottom: 16 }} title="区间检测进度">
          <Progress
            percent={detectProgress.progress}
            status={detectProgress.status === 'failed' ? 'exception' : 'active'}
          />
          <Text type="secondary">{detectProgress.message}</Text>
        </Card>
      )}

      <Card size="small" title="工作台入口">
        <Space wrap>
          <Button onClick={() => navigate(`/episodes/${episodeId}/clips`)}>片段审核</Button>
          <Button onClick={() => navigate(`/episodes/${episodeId}/intervals`)}>区间检测</Button>
          <Button onClick={() => navigate(`/episodes/${episodeId}/slice`)}>切片任务</Button>
          <Button onClick={() => navigate(`/episodes/${episodeId}/preview`)}>成品预览</Button>
        </Space>
      </Card>
    </div>
  );
};

export default EpisodeDetail;