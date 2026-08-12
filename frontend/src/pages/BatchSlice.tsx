import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Card, Form, Input, Button, message, Table, Tag, Space, Switch,
  Select, InputNumber, Radio, Alert, Divider, Typography, Progress, Popconfirm,
} from 'antd';
import { PlayCircleOutlined, ReloadOutlined, DownloadOutlined } from '@ant-design/icons';
import { batchSliceApi, BatchSlice, BatchSliceItem, BatchOutputs } from '../api/batchSlice';

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待处理' },
  uploading: { color: 'processing', text: '上传源视频' },
  autoclip: { color: 'processing', text: 'AI 选点' },
  review: { color: 'processing', text: '自动审核' },
  slicing: { color: 'processing', text: '切片中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
  skipped: { color: 'warning', text: '已跳过' },
};

const BatchSlicePage: React.FC = () => {
  const [form] = Form.useForm();
  const vert2horizEnabledWatch = Form.useWatch('vert2horiz_enabled', form);
  const subtitleEnabledWatch = Form.useWatch('subtitle_enabled', form);
  const watermarkEnabledWatch = Form.useWatch('watermark_enabled', form);
  const [submitting, setSubmitting] = useState(false);
  const [currentBatch, setCurrentBatch] = useState<BatchSlice | null>(null);
  const [items, setItems] = useState<BatchSliceItem[]>([]);
  const [outputs, setOutputs] = useState<BatchOutputs | null>(null);
  const [loadingItems, setLoadingItems] = useState(false);
  const [showOutputs, setShowOutputs] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 轮询批次进度
  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollBatch = useCallback((batchId: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const b = await batchSliceApi.get(batchId);
        setCurrentBatch(b);
        const its = await batchSliceApi.items(batchId);
        setItems(its);
        if (['completed', 'partial_failed', 'failed'].includes(b.status)) {
          stopPolling();
          const outs = await batchSliceApi.outputs(batchId);
          setOutputs(outs);
          message.info(`批次处理结束（${b.status}）`);
        }
      } catch {
        stopPolling();
      }
    }, 4000);
  }, [stopPolling]);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  const loadBatch = async (batchId: string) => {
    setLoadingItems(true);
    try {
      const b = await batchSliceApi.get(batchId);
      setCurrentBatch(b);
      const its = await batchSliceApi.items(batchId);
      setItems(its);
      if (['completed', 'partial_failed', 'failed'].includes(b.status)) {
        const outs = await batchSliceApi.outputs(batchId);
        setOutputs(outs);
      }
      if (!['completed', 'partial_failed', 'failed'].includes(b.status)) {
        pollBatch(batchId);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载批次失败');
    } finally {
      setLoadingItems(false);
    }
  };

  // 解析剧集列表（支持 JSON 或每行一地址格式）
  const parseEpisodes = (raw: string): { title?: string; path: string }[] => {
    const trimmed = raw.trim();
    if (!trimmed) return [];
    // 尝试 JSON 解析
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return parsed.map((e: unknown) => {
          if (typeof e === 'string') return { path: e };
          const obj = e as { title?: string; path?: string; source_path?: string };
          return { title: obj.title, path: obj.path || obj.source_path || '' };
        }).filter((e: { path: string }) => e.path);
      }
      if (parsed.episodes && Array.isArray(parsed.episodes)) {
        return parsed.episodes.map((e: { title?: string; path?: string }) =>
          ({ title: e.title, path: e.path || '' })
        ).filter((e: { path: string }) => e.path);
      }
    } catch {
      // 非 JSON：按行解析（每行一地址，支持 "标题,路径" 或纯路径）
    }
    return raw.split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const parts = line.split(',').map((s) => s.trim());
        if (parts.length >= 2) {
          return { title: parts[0], path: parts.slice(1).join(',') };
        }
        return { path: line };
      });
  };

  const handleRun = async () => {
    const values = await form.validateFields();
    const drama = (values.drama || '').trim();
    const episodes = parseEpisodes(values.episodesRaw || '');
    if (!drama) {
      message.error('请输入剧名');
      return;
    }
    if (episodes.length === 0) {
      message.error('请填写至少一个剧集地址');
      return;
    }
    setSubmitting(true);
    try {
      const sliceConfig: Record<string, unknown> = {
        mode: values.mode || 'fast',
      };
      if (values.vert2horiz_enabled) {
        sliceConfig.vert2horiz_enabled = true;
        sliceConfig.vert2horiz_mode = values.vert2horiz_mode || 'fixed';
        sliceConfig.vert2horiz_output_size = values.vert2horiz_output_size || '1280x720';
      }
      if (values.subtitle_enabled) {
        sliceConfig.subtitle_enabled = true;
        sliceConfig.subtitle_font_ratio = values.subtitle_font_ratio;
        sliceConfig.subtitle_style = values.subtitle_style || 'default';
        if (values.subtitle_style === 'custom') {
          sliceConfig.subtitle_color = values.subtitle_color || '#EDD736';
          sliceConfig.subtitle_border_color = values.subtitle_border_color || '#000000';
        }
      }
      if (values.watermark_enabled) {
        sliceConfig.watermark_enabled = true;
        sliceConfig.watermark_text = values.watermark_text;
        sliceConfig.watermark_position = values.watermark_position || 'bottom';
      }
      if (values.text_overlays) {
        const tos = values.text_overlays
          .split('\n')
          .map((line: string) => line.trim())
          .filter(Boolean)
          .map((line: string) => {
            const parts = line.split('|').map((s) => s.trim());
            return parts.length >= 2
              ? { text: parts[0], position: parts[1] }
              : { text: line, position: 'bottom-left' };
          });
        if (tos.length > 0) sliceConfig.text_overlays = tos;
      }

      const res = await batchSliceApi.run({
        drama,
        episodes,
        slice_config: sliceConfig,
        delete_source: values.delete_source !== false,
      });
      message.success(`批次已创建：${res.drama_name}（共 ${res.total} 集）`);
      form.setFieldValue('batch_id', res.id);
      setCurrentBatch(res);
      setItems([]);
      setOutputs(null);
      setShowOutputs(false);
      loadBatch(res.id);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建批次失败');
    } finally {
      setSubmitting(false);
    }
  };

  const itemColumns = [
    { title: '#', dataIndex: 'seq', width: 50 },
    { title: '剧集', dataIndex: 'title', render: (t?: string, r?: BatchSliceItem) => t || `剧集_${r?.seq}` },
    { title: '源地址', dataIndex: 'source_path', ellipsis: true },
    {
      title: '状态', dataIndex: 'status',
      render: (s: string, r: BatchSliceItem) => {
        const st = STATUS_MAP[s] || { color: 'default', text: s };
        return (
          <Space direction="vertical" size={2}>
            <Tag color={st.color}>{st.text}</Tag>
            {r.message && <Text type="secondary" style={{ fontSize: 12 }}>{r.message}</Text>}
          </Space>
        );
      },
    },
    {
      title: '进度', dataIndex: 'progress',
      render: (p: number, r: BatchSliceItem) =>
        ['completed'].includes(r.status)
          ? <Text type="success">已完成</Text>
          : r.status === 'failed'
            ? <Text type="danger">{r.error_message || '失败'}</Text>
            : <Progress percent={Math.round(p || 0)} size="small" style={{ width: 120 }} />,
    },
    { title: '成品数', dataIndex: 'output_count', width: 80 },
  ];

  const outputColumns = [
    { title: '#', dataIndex: 'seq', width: 50 },
    { title: '剧集', dataIndex: 'title', render: (t?: string, r?: { seq?: number }) => t || `剧集_${r?.seq}` },
    {
      title: '成品', dataIndex: 'outputs',
      render: (outs: { file_name?: string; presigned_url?: string }[]) =>
        outs && outs.length > 0 ? (
          <Space direction="vertical" size={2}>
            {outs.map((o, i) => (
              <Space key={i} size={4}>
                <Text style={{ fontSize: 12 }}>{o.file_name || `clip_${i + 1}.mp4`}</Text>
                {o.presigned_url && (
                  <a href={o.presigned_url} target="_blank" rel="noreferrer" download>
                    <DownloadOutlined /> 下载
                  </a>
                )}
              </Space>
            ))}
          </Space>
        ) : <Text type="secondary">无</Text>,
    },
    { title: '状态', dataIndex: 'status', render: (s: string) => (
      <Tag color={STATUS_MAP[s]?.color || 'default'}>{STATUS_MAP[s]?.text || s}</Tag>
    ) },
  ];

  const batchStatusTag = currentBatch ? (
    <Tag color={STATUS_MAP[currentBatch.status]?.color || 'default'}>
      {STATUS_MAP[currentBatch.status]?.text || currentBatch.status}
    </Tag>
  ) : null;

  return (
    <div style={{ padding: 24, maxWidth: 1200 }}>
      <Title level={4}>批量切片（三期）</Title>
      <Paragraph type="secondary">
        按剧名创建项目，逐集顺序执行「AI 选点 → 自动审核 → 一键切片 → 删除源视频」，最终汇总输出列表。
      </Paragraph>

      <Card title="① 上传剧集清单" style={{ marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            drama: '',
            episodesRaw: '',
            mode: 'fast',
            delete_source: true,
          }}
        >
          <Form.Item name="drama" label="剧名（将按此创建/查找项目）" rules={[{ required: true, message: '请输入剧名' }]}>
            <Input placeholder="如：赘婿之龙傲天" />
          </Form.Item>
          <Form.Item
            name="episodesRaw"
            label="剧集地址列表"
            rules={[{ required: true, message: '请填写剧集地址' }]}
            extra={'每行一个地址；支持「标题,路径」或纯路径；也支持 JSON：{"episodes":[{"title":"..","path":".."}]}'}
          >
            <TextArea
              rows={6}
              placeholder={[
                '第01集,/mnt/nas/shortdrama/ep01.mp4',
                '第02集,/mnt/nas/shortdrama/ep02.mp4',
              ].join('\n')}
            />
          </Form.Item>

          <Divider orientation="left">一键切片配置（整批统一生效）</Divider>
          <Space size="large" wrap>
            <Form.Item name="mode" label="切片模式">
              <Select style={{ width: 160 }} options={[{ value: 'fast', label: '快速' }, { value: 'high', label: '高清' }]} />
            </Form.Item>
            <Form.Item name="delete_source" label="处理完删除源视频" valuePropName="checked">
              <Switch checkedChildren="删除" unCheckedChildren="保留" />
            </Form.Item>
          </Space>

          <Space size="large" wrap>
            <Form.Item name="vert2horiz_enabled" label="竖屏转横屏" valuePropName="checked">
              <Switch />
            </Form.Item>
            {vert2horizEnabledWatch === true && (
              <Form.Item name="vert2horiz_mode" label="转横屏模式">
                <Select style={{ width: 140 }} options={[{ value: 'fixed', label: '固定裁切' }, { value: 'dynamic', label: '动态跟踪' }]} />
              </Form.Item>
            )}
            <Form.Item name="subtitle_enabled" label="ASR 字幕烧录" valuePropName="checked">
              <Switch />
            </Form.Item>
            {subtitleEnabledWatch === true && (
              <Form.Item name="subtitle_style" label="字幕样式">
                <Select style={{ width: 140 }} options={[{ value: 'default', label: '默认' }, { value: 'custom', label: '自定义' }]} />
              </Form.Item>
            )}
            <Form.Item name="watermark_enabled" label="文字水印" valuePropName="checked">
              <Switch />
            </Form.Item>
            {watermarkEnabledWatch === true && (
              <Form.Item name="watermark_position" label="水印位置">
                <Select style={{ width: 120 }} options={[{ value: 'bottom', label: '底部' }, { value: 'top', label: '顶部' }]} />
              </Form.Item>
            )}
          </Space>

          <Form.Item name="text_overlays" label="固定文字角标（可选，每行「文字|位置」）" style={{ marginTop: 8 }}>
            <TextArea
              rows={2}
              placeholder={'热门短剧|top-right\n免费热门短剧|bottom-left'}
            />
          </Form.Item>

          <Button type="primary" icon={<PlayCircleOutlined />} loading={submitting} onClick={handleRun}>
            开始批量切片
          </Button>
        </Form>
      </Card>

      {currentBatch && (
        <Card
          title={
            <Space>
              <span>批次：{currentBatch.drama_name}</span>
              {batchStatusTag}
              <Text type="secondary">({currentBatch.done}/{currentBatch.total})</Text>
            </Space>
          }
          extra={
            <Space>
              <Button size="small" icon={<ReloadOutlined />} onClick={() => loadBatch(currentBatch.id)}>刷新</Button>
              <Button size="small" type="primary" onClick={() => setShowOutputs((v) => !v)}>
                {showOutputs ? '查看进度' : '查看输出列表'}
              </Button>
            </Space>
          }
          style={{ marginBottom: 16 }}
        >
          {!showOutputs ? (
            <Table
              rowKey="id"
              loading={loadingItems}
              dataSource={items}
              columns={itemColumns}
              pagination={false}
              size="small"
            />
          ) : (
            <Table
              rowKey={(r) => r.episode_id || r.seq?.toString() || ''}
              dataSource={outputs?.items || []}
              columns={outputColumns}
              pagination={false}
              size="small"
            />
          )}
        </Card>
      )}
    </div>
  );
};

export default BatchSlicePage;
