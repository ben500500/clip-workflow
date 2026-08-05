import React, { useEffect, useRef, useState } from 'react';
import {
  Card, Button, Space, Typography, Spin, Alert, Breadcrumb, Descriptions, Tag, message, Select, Row, Col, Progress,
} from 'antd';
import { ArrowLeftOutlined, ThunderboltOutlined, RadarChartOutlined, ScissorOutlined } from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { projectApi } from '../api/projects';
import { autoclipApi } from '../api/autoclip';
import { intervalApi } from '../api/intervals';
import { sliceApi } from '../api/slice';
import type { Episode } from '../types';
import { formatDateTime, formatDuration, formatFileSize, getStatusColor, getStatusLabel } from '../utils/format';

const { Title, Text } = Typography;

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
  const [sliceRunning, setSliceRunning] = useState(false);
  
  const autoclipTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (autoclipTimerRef.current) {
        window.clearInterval(autoclipTimerRef.current);
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

  // 页面加载 / 返回时，检查是否有正在运行的选点任务，自动恢复轮询
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
              fetchEpisode();
            }
          } catch {
            if (autoclipTimerRef.current) window.clearInterval(autoclipTimerRef.current);
            autoclipTimerRef.current = null;
            if (mountedRef.current) setAutoclipRunning(false);
          }
        }, 3000);
      } else if (p && (p.status === 'completed' || p.status === 'failed')) {
        // 任务已结束，显示最终状态
        setAutoclipProgress(p);
      }
    } catch {
      // 没有运行中的任务，忽略
    }
  };

  useEffect(() => {
    if (episodeId && episode) {
      resumeAutoclipPolling();
    }
  }, [episodeId, episode?.id]);

  const runAutoClip = async () => {
    setAutoclipRunning(true);
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
    }
  };

  const runDetect = async () => {
    setDetectRunning(true);
    try {
      const res = await intervalApi.detect(episodeId, detectMode, {});
      message.success(res.message);
      setTimeout(() => {
        if (mountedRef.current) {
          fetchEpisode();
          setDetectRunning(false);
        }
      }, 5000);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '启动检测失败');
      setDetectRunning(false);
    }
  };

  const runSlice = async () => {
    setSliceRunning(true);
    try {
      const res = await sliceApi.run(episodeId, sliceMode, {});
      message.success(res.message);
      setTimeout(() => {
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

  const actions: { title: string; node: React.ReactNode }[] = [
    {
      title: 'AI 智能选点',
      node: (
        <Button type="primary" icon={<ThunderboltOutlined />} loading={autoclipRunning} onClick={runAutoClip}>
          启动选点
        </Button>
      ),
    },
    {
      title: '通用区间检测',
      node: (
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
      ),
    },
    {
      title: '切片执行',
      node: (
        <Space>
          <Select value={sliceMode} onChange={setSliceMode} style={{ width: 120 }}
            options={[
              { value: 'fast', label: '快速' },
              { value: 'dedupe', label: '去重' },
              { value: 'scrub', label: '挖洞' },
            ]}
          />
          <Button icon={<ScissorOutlined />} loading={sliceRunning} onClick={runSlice}>开始切片</Button>
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

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={4}>
          <Descriptions.Item label="集数">{episode.episode_no ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="时长">{formatDuration(episode.duration)}</Descriptions.Item>
          <Descriptions.Item label="文件大小">{formatFileSize(episode.file_size)}</Descriptions.Item>
          <Descriptions.Item label="上传时间">{formatDateTime(episode.created_at)}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {actions.map((a) => (
          <Col xs={24} md={8} key={a.title}>
            <Card size="small" title={a.title}>{a.node}</Card>
          </Col>
        ))}
      </Row>

      {autoclipProgress && (
        <Card size="small" style={{ marginBottom: 16 }} title="选点进度">
          <Progress percent={autoclipProgress.progress} status={autoclipProgress.status === 'failed' ? 'exception' : 'active'} />
          <Text type="secondary">{autoclipProgress.message}</Text>
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
