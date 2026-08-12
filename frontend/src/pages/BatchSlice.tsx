import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Form, Input, Button, InputNumber, Select, Switch, Space, Divider,
  Table, Tag, Progress, message, Alert, Typography, Modal, List, Spin, Tooltip,
} from 'antd';
import {
  PlayCircleOutlined, UploadOutlined, ReloadOutlined, StopOutlined,
  DownloadOutlined, InboxOutlined,
} from '@ant-design/icons';
import Dragger from 'antd/es/upload/Dragger';
import { batchSliceApi, BatchSlice, BatchSliceItem, BatchSliceOutputItem } from '../api/batchSlice';

const { Text, Title } = Typography;

// ── 一键切片配置（复用剧集详情页的常用配置项，整批统一生效）──
// AI 智能选点配置
interface AutoClipConfig {
  enabled: boolean;
  max_clips: number;
  min_score_threshold: number;
  min_duration: number;
  max_duration: number;
  frame_analysis: boolean;
}
// 通用区间检测配置
interface IntervalConfig {
  enabled: boolean;
  mode: 'credits' | 'static' | 'watermark';
}

interface SliceConfigState {
  autoclip: AutoClipConfig;
  interval: IntervalConfig;
  vert2horiz_enabled: boolean;
  vert2horiz_mode: 'fixed' | 'dynamic';
  vert2horiz_ratio: number;
  vert2horiz_output_size: string;
  subtitle_enabled: boolean;
  subtitle_font_ratio: number;
  subtitle_spacing: number;
  subtitle_style: 'default' | 'custom';
  subtitle_color: string;
  subtitle_border_color: string;
  text_overlay_enabled: boolean;
  text_overlays: { text: string; position: string; font_size: number; color: string; border_color?: string; vertical?: boolean }[];
  watermark_enabled: boolean;
  watermark_text: string;
  watermark_font_size: number;
  watermark_opacity: number;
  watermark_position: string;
}

const DEFAULT_SLICE_CONFIG: SliceConfigState = {
  autoclip: {
    enabled: true,
    max_clips: 30,
    min_score_threshold: 60,
    min_duration: 30,
    max_duration: 180,
    frame_analysis: true,
  },
  interval: {
    enabled: true,
    mode: 'credits',
  },
  vert2horiz_enabled: true,
  vert2horiz_mode: 'dynamic',
  vert2horiz_ratio: 0.5625,
  vert2horiz_output_size: '1280x720',
  subtitle_enabled: true,
  subtitle_font_ratio: 0.30,
  subtitle_spacing: 0,
  subtitle_style: 'custom',
  subtitle_color: '#EDD736',
  subtitle_border_color: '#000000',
  text_overlay_enabled: true,
  text_overlays: [
    { text: '热门短剧', position: 'top-right', font_size: 40, color: '#EDD736', border_color: '#000000' },
    { text: '免费热门短剧', position: 'bottom-left', font_size: 36, color: '#FFFFFF', border_color: '#000000' },
    { text: '本故事纯属虚构', position: 'left', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: true },
  ],
  watermark_enabled: false,
  watermark_text: '',
  watermark_font_size: 28,
  watermark_opacity: 0.5,
  watermark_position: 'bottom',
};

const POSITIONS = ['top-left', 'top-center', 'top-right', 'left', 'bottom-left', 'bottom-center', 'bottom-right'];

// 阶段中文名
const PHASE_LABELS: Record<string, string> = {
  upload: '上传源视频',
  autoclip: 'AI 选点',
  review: '自动审核',
  interval: '区间检测',
  slice: '一键切片',
  source_delete: '删除源视频',
};

const STATUS_COLOR: Record<string, string> = {
  completed: 'green',
  failed: 'red',
  pending: 'default',
  uploading: 'blue',
  autoclip: 'blue',
  reviewing: 'blue',
  detecting: 'blue',
  slicing: 'processing',
  deleting: 'processing',
  cancelled: 'orange',
};

const STATUS_TEXT: Record<string, string> = {
  completed: '已完成',
  failed: '失败',
  pending: '待处理',
  uploading: '上传中',
  autoclip: '选点中',
  reviewing: '审核中',
  detecting: '检测中',
  slicing: '切片中',
  deleting: '删除中',
  cancelled: '已取消',
};

const BatchSlicePage: React.FC = () => {
  const [form] = Form.useForm();
  const [sliceConfig, setSliceConfig] = useState<SliceConfigState>({ ...DEFAULT_SLICE_CONFIG, text_overlays: DEFAULT_SLICE_CONFIG.text_overlays.map((t) => ({ ...t })) });
  const [jsonText, setJsonText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [batches, setBatches] = useState<BatchSlice[]>([]);
  const [batchListLoading, setBatchListLoading] = useState(false);

  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [selectedBatch, setSelectedBatch] = useState<BatchSlice | null>(null);
  const [items, setItems] = useState<BatchSliceItem[]>([]);
  const [outputs, setOutputs] = useState<BatchSliceOutputItem[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [outputModalOpen, setOutputModalOpen] = useState(false);

  const fetchBatches = useCallback(async () => {
    setBatchListLoading(true);
    try {
      const data = await batchSliceApi.list();
      setBatches(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '获取批次列表失败');
    } finally {
      setBatchListLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBatches();
  }, [fetchBatches]);

  const loadBatchDetail = useCallback(async (batchId: string) => {
    setDetailLoading(true);
    try {
      const [batch, itemList] = await Promise.all([
        batchSliceApi.getById(batchId),
        batchSliceApi.getItems(batchId),
      ]);
      setSelectedBatchId(batchId);
      setSelectedBatch(batch);
      setItems(itemList);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载批次详情失败');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // 轮询详情
  useEffect(() => {
    if (!selectedBatchId) return;
    const timer = window.setInterval(() => {
      loadBatchDetail(selectedBatchId);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [selectedBatchId, loadBatchDetail]);

  const handleFileUpload = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || '');
      setJsonText(text);
      setJsonError(null);
      try {
        const parsed = JSON.parse(text);
        if (!parsed.drama || !Array.isArray(parsed.episodes)) {
          setJsonError('JSON 需包含 drama（剧名）与 episodes（剧集数组）字段');
        }
      } catch {
        setJsonError('JSON 解析失败，请检查格式');
      }
    };
    reader.readAsText(file);
    return false;
  };

  const buildPayload = () => {
    let parsed: { drama?: string; episodes?: { title?: string; path: string }[] };
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      throw new Error('JSON 解析失败，请检查格式');
    }
    if (!parsed.drama || !parsed.drama.trim()) throw new Error('缺少剧名 drama');
    if (!Array.isArray(parsed.episodes) || parsed.episodes.length === 0) {
      throw new Error('缺少剧集列表 episodes');
    }
    for (const ep of parsed.episodes) {
      if (!ep.path) throw new Error('剧集中存在缺少 path 的项');
    }
    return {
      drama: parsed.drama.trim(),
      episodes: parsed.episodes,
      slice_config: {
        mode: 'fast',
        ...sliceConfig,
        // AI 智能选点：配置并入 autoclip_config / autoclip_enabled
        autoclip_enabled: sliceConfig.autoclip.enabled,
        autoclip_config: {
          max_clips: sliceConfig.autoclip.max_clips,
          min_score_threshold: sliceConfig.autoclip.min_score_threshold,
          min_duration: sliceConfig.autoclip.min_duration,
          max_duration: sliceConfig.autoclip.max_duration,
          frame_analysis: sliceConfig.autoclip.frame_analysis,
        },
        // 通用区间检测：配置并入 interval_config / interval_enabled
        interval_enabled: sliceConfig.interval.enabled,
        interval_config: {
          mode: sliceConfig.interval.mode,
        },
        // text_overlays 仅开启时透传
        text_overlays: sliceConfig.text_overlay_enabled ? sliceConfig.text_overlays : [],
      },
    };
  };

  const handleRun = async () => {
    setJsonError(null);
    let payload: ReturnType<typeof buildPayload>;
    try {
      payload = buildPayload();
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : '参数校验失败');
      return;
    }
    setCreating(true);
    try {
      const resp = await batchSliceApi.run(payload);
      message.success(resp.message);
      setJsonText('');
      form.resetFields();
      fetchBatches();
      if (resp.batch_id) {
        await loadBatchDetail(resp.batch_id);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建批次失败');
    } finally {
      setCreating(false);
    }
  };

  const handleRetry = async () => {
    if (!selectedBatchId) return;
    Modal.confirm({
      title: '重试失败项',
      content: '确定重试该批次中失败的剧集吗？（已完成项将跳过）',
      okText: '重试',
      cancelText: '取消',
      onOk: async () => {
        try {
          const resp = await batchSliceApi.retry(selectedBatchId);
          message.success(resp.message);
          loadBatchDetail(selectedBatchId);
        } catch (err) {
          message.error(err instanceof Error ? err.message : '重试失败');
        }
      },
    });
  };

  const handleCancel = async () => {
    if (!selectedBatchId) return;
    Modal.confirm({
      title: '取消批次',
      content: '确定取消该批次吗？（未完成的剧集将标记为已取消）',
      okText: '取消批次',
      cancelText: '返回',
      onOk: async () => {
        try {
          const resp = await batchSliceApi.cancel(selectedBatchId);
          message.success(resp.message);
          loadBatchDetail(selectedBatchId);
        } catch (err) {
          message.error(err instanceof Error ? err.message : '取消失败');
        }
      },
    });
  };

  const showOutputs = async () => {
    if (!selectedBatchId) return;
    setOutputModalOpen(true);
    try {
      const data = await batchSliceApi.getOutputs(selectedBatchId);
      setOutputs(data.items);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '获取输出列表失败');
    }
  };

  const renderOutputModal = () => {
    const allOutputs: { seq: number; title: string | null; file: Record<string, unknown> }[] = [];
    outputs.forEach((item) => {
      const out = item.output;
      if (out && 'outputs' in out && Array.isArray((out as any).outputs)) {
        (out as any).outputs.forEach((f: Record<string, unknown>) => allOutputs.push({ seq: item.seq, title: item.title, file: f }));
      } else if (out) {
        allOutputs.push({ seq: item.seq, title: item.title, file: out });
      }
    });
    return (
      <Modal
        title={`输出列表（共 ${allOutputs.length} 个成品）`}
        open={outputModalOpen}
        onCancel={() => setOutputModalOpen(false)}
        footer={null}
        width={760}
      >
        <List
          dataSource={allOutputs}
          renderItem={(item) => (
            <List.Item
              actions={[
                <a key="dl" href={(item.file as any).presigned_url || '#'} target="_blank" rel="noreferrer">
                  <DownloadOutlined /> 下载
                </a>,
              ]}
            >
              <List.Item.Meta
                title={`第 ${item.seq} 集 · ${(item.file as any).file_name || ''}`}
                description={
                  <Space size={12}>
                    <Text type="secondary">{(item.file as any).duration ? `${(item.file as any).duration}s` : ''}</Text>
                    <Text type="secondary">{(item.file as any).resolution || ''}</Text>
                    <Text type="secondary">{formatSize((item.file as any).file_size)}</Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      </Modal>
    );
  };

  const formatSize = (size?: number | null) => {
    if (!size) return '';
    if (size < 1024) return `${size}B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`;
    return `${(size / 1024 / 1024).toFixed(1)}MB`;
  };

  const itemColumns = [
    { title: '序号', dataIndex: 'seq', width: 60 },
    {
      title: '剧集',
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '阶段',
      dataIndex: 'phase',
      width: 110,
      render: (v: string | null) => (v ? (PHASE_LABELS[v] || v) : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_TEXT[v] || v}</Tag>,
    },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 120,
      render: (v: number, r: BatchSliceItem) => (
        <Progress percent={Math.round(v)} size="small" status={r.status === 'failed' ? 'exception' : undefined} />
      ),
    },
    { title: '成品数', dataIndex: 'output_count', width: 80 },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      ellipsis: true,
      render: (v: string | null) => (v ? <Text type="danger">{v}</Text> : '-'),
    },
  ];

  const batchColumns = [
    {
      title: '批次',
      dataIndex: 'name',
      ellipsis: true,
      render: (v: string | null, r: BatchSlice) => <a onClick={() => loadBatchDetail(r.id)}>{v || r.id}</a>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_TEXT[v] || v}</Tag>,
    },
    { title: '总数', dataIndex: 'total', width: 60 },
    { title: '完成', dataIndex: 'done', width: 60 },
    { title: '失败', dataIndex: 'failed', width: 60 },
    { title: '成品数', dataIndex: 'output_count', width: 80 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => new Date(v).toLocaleString(),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>批量切片工作流</Title>
      <Alert
        type="info"
        showIcon
        message="上传包含剧名与剧集地址的 JSON，系统按剧名查找/创建项目，并按列表顺序逐集完成「AI 选点 → 自动审核 → 一键切片 → 删除源视频」，最后汇总输出列表。"
        style={{ marginBottom: 16 }}
      />

      <Card title="① 上传列表（JSON）" style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical">
          <Form.Item label="JSON 内容（示例）" required>
            <Input.TextArea
              rows={6}
              value={jsonText}
              onChange={(e) => {
                setJsonText(e.target.value);
                setJsonError(null);
              }}
              placeholder={'{\n  "drama": "短剧A",\n  "episodes": [\n    { "title": "第1集", "path": "/mnt/nas/shortdrama/ep01.mp4" },\n    { "title": "第2集", "path": "/mnt/nas/shortdrama/ep02.mp4" }\n  ]\n}'}
            />
            <div style={{ marginTop: 8 }}>
              <Dragger
                accept=".json,.txt"
                beforeUpload={(file) => {
                  handleFileUpload(file as unknown as File);
                  return false;
                }}
                showUploadList={false}
                style={{ padding: 8 }}
              >
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p className="ant-upload-text">点击或拖拽 JSON 文件到此处</p>
              </Dragger>
            </div>
            {jsonError && <Text type="danger">{jsonError}</Text>}
          </Form.Item>
        </Form>
      </Card>

      <Card title="② 一键切片配置选项" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Divider orientation="left" style={{ margin: '8px 0' }}>AI 智能选点</Divider>
          <Space size="large" wrap>
            <Text>启用 AI 选点：</Text>
            <Switch
              checked={sliceConfig.autoclip.enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, enabled: v } })}
            />
            {sliceConfig.autoclip.enabled && (
              <>
                <Text>候选数</Text>
                <InputNumber
                  value={sliceConfig.autoclip.max_clips}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, max_clips: v ?? 30 } })}
                  min={1}
                  max={200}
                />
                <Text>最低评分</Text>
                <InputNumber
                  value={sliceConfig.autoclip.min_score_threshold}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, min_score_threshold: v ?? 60 } })}
                  min={0}
                  max={100}
                />
                <Text>最短时长(s)</Text>
                <InputNumber
                  value={sliceConfig.autoclip.min_duration}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, min_duration: v ?? 0 } })}
                  min={0}
                />
                <Text>最长时长(s)</Text>
                <InputNumber
                  value={sliceConfig.autoclip.max_duration}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, max_duration: v ?? 0 } })}
                  min={0}
                />
                <Text>画面理解</Text>
                <Switch
                  checked={sliceConfig.autoclip.frame_analysis}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, autoclip: { ...sliceConfig.autoclip, frame_analysis: v } })}
                />
              </>
            )}
          </Space>

          <Divider orientation="left" style={{ margin: '8px 0' }}>通用区间检测</Divider>
          <Space size="large" wrap>
            <Text>启用区间检测：</Text>
            <Switch
              checked={sliceConfig.interval.enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, interval: { ...sliceConfig.interval, enabled: v } })}
            />
            {sliceConfig.interval.enabled && (
              <>
                <Text>检测模式</Text>
                <Select
                  value={sliceConfig.interval.mode}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, interval: { ...sliceConfig.interval, mode: v } })}
                  style={{ width: 120 }}
                  options={[
                    { value: 'credits', label: '片尾字幕' },
                    { value: 'static', label: '静止画面' },
                    { value: 'watermark', label: '水印' },
                  ]}
                />
                <Tooltip title="区间检测会在切片前自动检测片尾/静止/水印区间，用于辅助切片流程">
                  <Tag color="blue">切片前自动检测</Tag>
                </Tooltip>
              </>
            )}
          </Space>

          <Divider orientation="left" style={{ margin: '8px 0' }}>切片增强配置</Divider>
          <Space size="large">
            <Text>竖屏转横屏：</Text>
            <Switch
              checked={sliceConfig.vert2horiz_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_enabled: v })}
            />
            {sliceConfig.vert2horiz_enabled && (
              <>
                <Select
                  value={sliceConfig.vert2horiz_mode}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_mode: v })}
                  style={{ width: 120 }}
                  options={[
                    { value: 'fixed', label: '固定裁切' },
                    { value: 'dynamic', label: '动态人脸' },
                  ]}
                />
                <Text>输出</Text>
                <Select
                  value={sliceConfig.vert2horiz_output_size}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, vert2horiz_output_size: v })}
                  style={{ width: 110 }}
                  options={['1280x720', '1920x1080'].map((s) => ({ value: s, label: s }))}
                />
              </>
            )}
          </Space>

          <Space size="large">
            <Text>ASR 字幕烧录：</Text>
            <Switch
              checked={sliceConfig.subtitle_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_enabled: v })}
            />
            {sliceConfig.subtitle_enabled && (
              <>
                <Text>字号</Text>
                <InputNumber
                  value={sliceConfig.subtitle_font_ratio}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_font_ratio: v ?? 0.30 })}
                  step={0.05}
                  min={0.1}
                  max={0.6}
                />
                <Text>间距</Text>
                <InputNumber
                  value={sliceConfig.subtitle_spacing}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_spacing: v ?? 0 })}
                  step={1}
                  min={-5}
                  max={20}
                  style={{ width: 70 }}
                />
                <Select
                  value={sliceConfig.subtitle_style}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, subtitle_style: v })}
                  style={{ width: 110 }}
                  options={[
                    { value: 'default', label: '默认' },
                    { value: 'custom', label: '自定义' },
                  ]}
                />
                {sliceConfig.subtitle_style === 'custom' && (
                  <>
                    <Input
                      value={sliceConfig.subtitle_color}
                      onChange={(e) => setSliceConfig({ ...sliceConfig, subtitle_color: e.target.value })}
                      style={{ width: 90 }}
                      placeholder="字体色"
                    />
                    <Input
                      value={sliceConfig.subtitle_border_color}
                      onChange={(e) => setSliceConfig({ ...sliceConfig, subtitle_border_color: e.target.value })}
                      style={{ width: 90 }}
                      placeholder="边框色"
                    />
                  </>
                )}
              </>
            )}
          </Space>

          <Space size="large">
            <Text>固定文字角标：</Text>
            <Switch
              checked={sliceConfig.text_overlay_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, text_overlay_enabled: v })}
            />
            {sliceConfig.text_overlay_enabled && (
              <Tooltip title="使用当前默认的两条固定文字（顶部右上 + 左下角）">
                <Tag>已启用 2 条文字</Tag>
              </Tooltip>
            )}
          </Space>

          <Space size="large">
            <Text>文字水印：</Text>
            <Switch
              checked={sliceConfig.watermark_enabled}
              onChange={(v) => setSliceConfig({ ...sliceConfig, watermark_enabled: v })}
            />
            {sliceConfig.watermark_enabled && (
              <>
                <Input
                  value={sliceConfig.watermark_text}
                  onChange={(e) => setSliceConfig({ ...sliceConfig, watermark_text: e.target.value })}
                  placeholder="水印文字（支持 {title}/{date}）"
                  style={{ width: 200 }}
                />
                <Select
                  value={sliceConfig.watermark_position}
                  onChange={(v) => setSliceConfig({ ...sliceConfig, watermark_position: v })}
                  style={{ width: 90 }}
                  options={[
                    { value: 'bottom', label: '底部' },
                    { value: 'top', label: '顶部' },
                  ]}
                />
              </>
            )}
          </Space>
        </Space>

        <Divider />
        <Space>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={creating}
            onClick={handleRun}
          >
            创建批次并开始处理
          </Button>
          <Button
            icon={<UploadOutlined />}
            onClick={() => setSliceConfig({ ...DEFAULT_SLICE_CONFIG, text_overlays: DEFAULT_SLICE_CONFIG.text_overlays.map((t) => ({ ...t })) })}
          >
            恢复默认配置
          </Button>
        </Space>
      </Card>

      <Card title="③ 执行结果" style={{ marginBottom: 16 }}>
        <Space style={{ marginBottom: 16 }}>
          <Button onClick={fetchBatches} icon={<ReloadOutlined />}>刷新批次列表</Button>
          {selectedBatch && (
            <>
              <Tag color={STATUS_COLOR[selectedBatch.status] || 'default'}>
                {STATUS_TEXT[selectedBatch.status] || selectedBatch.status}
              </Tag>
              <Text>完成 {selectedBatch.done}/{selectedBatch.total} · 失败 {selectedBatch.failed} · 成品 {selectedBatch.output_count}</Text>
              {selectedBatch.status === 'partial_failed' && (
                <Button onClick={handleRetry} size="small">重试失败项</Button>
              )}
              {['running', 'pending'].includes(selectedBatch.status) && (
                <Button onClick={handleCancel} danger size="small" icon={<StopOutlined />}>取消批次</Button>
              )}
              <Button onClick={showOutputs} size="small" icon={<DownloadOutlined />}>输出列表</Button>
            </>
          )}
        </Space>
        <Spin spinning={batchListLoading}>
          <Table
            rowKey="id"
            size="small"
            dataSource={batches}
            columns={batchColumns}
            pagination={false}
          />
        </Spin>
        {selectedBatchId && (
          <Divider orientation="left">批次明细</Divider>
        )}
        <Spin spinning={detailLoading}>
          {items.length > 0 && (
            <Table
              rowKey="id"
              size="small"
              dataSource={items}
              columns={itemColumns}
              pagination={false}
            />
          )}
        </Spin>
      </Card>

      {renderOutputModal()}
    </div>
  );
};

export default BatchSlicePage;
