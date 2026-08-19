import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Tabs, Table, Tag, Button, Space, Typography, message, InputNumber, Select,
  Alert, Empty, Tooltip, Input, Modal,
} from 'antd';
import {
  ThunderboltOutlined, UploadOutlined, FileAddOutlined, ReloadOutlined,
  PlayCircleOutlined, DeleteOutlined, FolderOutlined, VideoCameraOutlined, SettingOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import Dragger from 'antd/es/upload/Dragger';
import DedupeManualConfig, { type DedupeManualConfigValue } from '../components/DedupeManualConfig';
import { variantsApi, SliceOutputListItem, SliceOutputProject } from '../api/variants';
import { dedupeApi, DedupeUploadedFile } from '../api/dedupe';
import { batchSliceApi } from '../api/batchSlice';
import { useNavigate } from 'react-router-dom';
import { useDedupePresets } from '../hooks/useDedupePresets';

const { Text } = Typography;

const VARIANT_COUNT_DEFAULT = 3;

/**
 * 「去重处理」独立入口：
 *  - 输入：批量文件拖入（上传→batch-slice/run 复用切片链路）或从已切片任务多选 SliceOutput
 *  - 配置：复用 DedupeManualConfig（preset + 全量 manual）+ 变体数量（默认 3）
 *  - 产出：走 variants/generate-batch 批量生成变体，出现在变体矩阵 VariantMatrix
 */
const DedupeProcessing: React.FC = () => {
  const navigate = useNavigate();
  // 去重配置单一来源：档位下拉统一来自共享 hook（接口失败回退硬编码默认）
  const { presetOptions: DEDUPE_PRESET_OPTIONS } = useDedupePresets();

  // ── 去重配置（两个输入模式共用）──
  const [dedupePreset, setDedupePreset] = useState<string>('std_crop_desat');
  const [dedupeManual, setDedupeManual] = useState<DedupeManualConfigValue>({});
  const [variantCount, setVariantCount] = useState<number>(VARIANT_COUNT_DEFAULT);

  // ── Tab1：从已切片任务多选 SliceOutput ──
  const [groups, setGroups] = useState<SliceOutputProject[]>([]);
  const [outputsLoading, setOutputsLoading] = useState(false);
  const [selectedRows, setSelectedRows] = useState<SliceOutputListItem[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState('');
  const pageSize = 20;
  // 分组表格折叠控制：默认全部折叠（用户手动展开项目/剧集查看输出）
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([]);

  // ── Tab2：批量文件拖入 ──
  const [uploadedFiles, setUploadedFiles] = useState<DedupeUploadedFile[]>([]);
  const [dramaName, setDramaName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [generating, setGenerating] = useState(false);

  // ── 去重配置弹窗 ──
  const [configOpen, setConfigOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('outputs');

  const fetchOutputs = useCallback(async (p: number = page, kw: string = keyword) => {
    setOutputsLoading(true);
    try {
      const data = await variantsApi.listSliceOutputs({ page: p, page_size: pageSize, keyword: kw || undefined });
      setGroups(data.groups || []);
      setTotal(data.total || 0);
      // 默认不展开分组（用户手动展开项目/剧集查看输出）
      setExpandedKeys([]);
    } catch (e) {
      message.error((e as Error).message || '加载已切片任务失败');
    } finally {
      setOutputsLoading(false);
    }
  }, [page, keyword]);

  useEffect(() => {
    fetchOutputs();
  }, []);

  // 构造去重配置（与 SliceTasks.buildDedupeConfig 对齐：preset 基础档位 + manual 手动覆盖）
  const buildDedupeConfig = (preset: string, manual: DedupeManualConfigValue) => {
    const m: Record<string, unknown> = {};
    if (manual.crop !== undefined) m.crop = manual.crop;
    if (manual.hflip !== undefined) m.hflip = manual.hflip;
    if (manual.speed !== undefined) m.speed = manual.speed;
    if (manual.saturation !== undefined) m.saturation = manual.saturation;
    if (manual.gamma !== undefined) m.gamma = manual.gamma;
    if (manual.contrast !== undefined) m.contrast = manual.contrast;
    if (manual.brightness !== undefined) m.brightness = manual.brightness;
    if (manual.noise !== undefined) m.noise = manual.noise;
    if (manual.sharpen !== undefined) m.sharpen = manual.sharpen;
    if (manual.vignette) m.vignette = manual.vignette;
    if (manual.roll_band !== undefined) m.roll_band = manual.roll_band;
    if (manual.jitter !== undefined) m.jitter = manual.jitter;
    if (manual.watermark?.enabled) {
      m.watermark = {
        text: manual.watermark.text || 'Clip',
        opacity: manual.watermark.opacity ?? 0.25,
        position: manual.watermark.position || 'bottom-right',
        drift: !!manual.watermark.drift,
      };
    }
    if (manual.sparkle?.enabled) {
      m.sparkle = { enabled: true, count: manual.sparkle.count ?? 3, size: manual.sparkle.size ?? 3, opacity: manual.sparkle.opacity ?? 10 };
    }
    if (manual.face_watermark?.enabled) {
      m.face_watermark = { enabled: true, text: manual.face_watermark.text || 'W', opacity: manual.face_watermark.opacity ?? 0.08, font_size: manual.face_watermark.font_size ?? 24 };
    }
    return Object.keys(m).length > 0 ? { preset, manual: m } : { preset };
  };

  // ── Tab1 提交：对选中的 SliceOutput 批量生成变体 ──
  const handleGenerateSelected = async () => {
    if (selectedRows.length === 0) {
      message.warning('请先选择至少一个已切片输出');
      return;
    }
    setGenerating(true);
    try {
      const dedupe_config = buildDedupeConfig(dedupePreset, dedupeManual);
      const res = await variantsApi.generateBatch({
        output_ids: selectedRows.map((r) => r.id),
        count: variantCount,
        dedupe_config,
      });
      message.success(`已投递 ${res.total} 个变体生成任务（每个 ${res.count} 套），请在「变体矩阵」查看产出`);
      setSelectedRows([]);
    } catch (e) {
      message.error((e as Error).message || '批量生成变体失败');
    } finally {
      setGenerating(false);
    }
  };

  // ── Tab2：拖入文件逐个上传 ──
  const handleUpload = async (file: File) => {
    const uid = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    setUploadedFiles((prev) => [...prev, { uid, file_name: file.name, file_size: file.size, path: '', status: 'uploading' }]);
    try {
      const res = await dedupeApi.upload(file);
      setUploadedFiles((prev) => prev.map((f) =>
        f.uid === uid ? { ...f, status: 'done', path: res.path, file_size: res.file_size } : f,
      ));
    } catch (e) {
      setUploadedFiles((prev) => prev.map((f) =>
        f.uid === uid ? { ...f, status: 'error', error: (e as Error).message } : f,
      ));
      message.error(`${file.name} 上传失败：${(e as Error).message || '未知错误'}`);
    }
    return false;
  };

  const removeUploaded = (uid: string) => {
    setUploadedFiles((prev) => prev.filter((f) => f.uid !== uid));
  };

  // ── Tab2 提交：复用 batch-slice/run（上传→切片）链路，切片自动派生变体 ──
  const handleRunBatch = async () => {
    const ready = uploadedFiles.filter((f) => f.status === 'done' && f.path);
    if (ready.length === 0) {
      message.warning('请先拖入并上传至少一个视频文件');
      return;
    }
    setSubmitting(true);
    try {
      const name = (dramaName && dramaName.trim()) || `去重处理-${dayjs().format('MMDD-HHmmss')}`;
      const resp = await batchSliceApi.run({
        drama: name,
        episodes: ready.map((f) => ({ title: f.file_name, path: f.path })),
        slice_config: {
          // 去重模式整片转换：不依赖 AI 选点，直接对整段源视频应用去重配置
          mode: 'dedupe',
          no_cut: true,
          dedupe_config: buildDedupeConfig(dedupePreset, dedupeManual),
          // 复用现有切片链路：>1 时切片后自动派生 N 个去重变体
          variant_count: variantCount > 1 ? variantCount : undefined,
        },
        auto_delete_source: false,
      });
      message.success(`已创建批量切片批次 ${resp.batch_id}（${resp.total} 个视频），正在去重切片并派生变体，可在「批量切片」或「变体矩阵」查看`);
      setUploadedFiles([]);
      setDramaName('');
    } catch (e) {
      message.error((e as Error).message || '提交批量切片失败');
    } finally {
      setSubmitting(false);
    }
  };

  // 把分组结构展开成树形行：项目行 → 剧集行 → 输出行（children 嵌套，支持折叠）
  type GroupRow = {
    key: string;
    type: 'project' | 'episode' | 'output';
    title: string;
    meta?: string;
    item?: SliceOutputListItem;
    children?: GroupRow[];
  };
  const buildTreeData = (): GroupRow[] =>
    (groups || []).map((g) => ({
      key: `p_${g.project_id || 'none'}`,
      type: 'project' as const,
      title: g.project_name,
      children: (g.episodes || []).map((e) => ({
        key: `e_${e.episode_id || g.project_id || 'none'}_${e.episode_title}`,
        type: 'episode' as const,
        title: e.episode_title,
        meta: e.drama_name || undefined,
        children: (e.outputs || []).map((o) => ({
          key: o.id,
          type: 'output' as const,
          title: o.file_name || '—',
          item: o,
        })),
      })),
    }));

  const outputColumns: ColumnsType<GroupRow> = [
    {
      title: '项目 / 剧集 / 文件名',
      key: 'name',
      render: (_: unknown, row: GroupRow) => {
        if (row.type === 'project') {
          return <Space><FolderOutlined />{row.title}</Space>;
        }
        if (row.type === 'episode') {
          return (
            <Space style={{ paddingLeft: 12 }}>
              <VideoCameraOutlined />{row.title}
              {row.meta ? <Tag>{row.meta}</Tag> : null}
            </Space>
          );
        }
        return <span style={{ paddingLeft: 24 }}>{row.title}</span>;
      },
    },
    { title: '分辨率', dataIndex: 'resolution', width: 110, render: (_: unknown, row: GroupRow) => (row.type === 'output' ? (row.item?.resolution || '—') : '') },
    { title: '时长', dataIndex: 'duration', width: 90, render: (_: unknown, row: GroupRow) => (row.type === 'output' && row.item?.duration != null ? `${row.item.duration.toFixed(1)}s` : '') },
    {
      title: '变体组', dataIndex: 'variant_group_id', width: 110,
      render: (_: unknown, row: GroupRow) => (row.type === 'output' ? (row.item?.variant_group_id ? <Tag color="blue">已生成</Tag> : <Tag>未去重</Tag>) : ''),
    },
    { title: '生成时间', dataIndex: 'created_at', width: 150, render: (_: unknown, row: GroupRow) => (row.type === 'output' && row.item?.created_at ? dayjs(row.item.created_at).format('MM-DD HH:mm') : '') },
  ];

  return (
    <Card
      title={<Space><ThunderboltOutlined />去重处理（多视频号素材去重）</Space>}
      style={{ margin: 16 }}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="输入（批量文件拖入 或 从已切片任务多选）→ 配置去重手段 + 变体数量 → 复用现有切片/变体链路产出变体，出现在「变体矩阵」。"
      />

      {/* 顶部操作栏：所有操作按钮置顶 */}
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <Space wrap>
          <Button icon={<SettingOutlined />} onClick={() => setConfigOpen(true)}>去重配置</Button>
          <Button icon={<ReloadOutlined />} onClick={() => fetchOutputs()}>刷新</Button>
          <Button icon={<ThunderboltOutlined />} onClick={() => navigate('/variant-matrix')}>查看变体矩阵</Button>
        </Space>
        <Space wrap>
          {activeTab === 'outputs' ? (
            <Button type="primary" icon={<PlayCircleOutlined />} loading={generating} onClick={handleGenerateSelected}>
              提交生成
            </Button>
          ) : (
            <>
              <Input
                placeholder="批次名称（留空自动生成）" value={dramaName}
                onChange={(e) => setDramaName(e.target.value)} style={{ width: 240 }}
              />
              <Button type="primary" icon={<UploadOutlined />} loading={submitting} onClick={handleRunBatch}>
                上传去重
              </Button>
            </>
          )}
        </Space>
      </div>

      {/* 下方空间全部留给列表 */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'outputs',
            label: '从已切片任务选择（SliceOutput 多选）',
            children: (
              <div>
                <Space style={{ marginBottom: 12 }}>
                  <Input.Search
                    placeholder="按项目 / 剧集 / 文件名筛选" allowClear style={{ width: 260 }}
                    onSearch={(v) => { setKeyword(v); fetchOutputs(1, v); }}
                  />
                  <Text type="secondary">已选 {selectedRows.length} 个输出</Text>
                </Space>
                <Table
                  rowKey="key" columns={outputColumns} dataSource={buildTreeData()} loading={outputsLoading} size="small"
                  expandable={{ expandedRowKeys: expandedKeys, onExpandedRowsChange: (keys) => setExpandedKeys(keys as React.Key[]) }}
                  rowSelection={{
                    selectedRowKeys: selectedRows.map((r) => r.id),
                    getCheckboxProps: (row: GroupRow) => ({ disabled: row.type !== 'output' }),
                    onChange: (_keys, rows) => setSelectedRows((rows as GroupRow[]).filter((r) => r.type === 'output' && r.item).map((r) => r.item as SliceOutputListItem)),
                  }}
                  pagination={{
                    current: page, pageSize, total, showSizeChanger: false,
                    onChange: (p) => { setPage(p); fetchOutputs(p); },
                  }}
                />
                {total === 0 && !outputsLoading && (
                  <Empty style={{ marginTop: 24 }} description="暂无已切片输出。可拖入文件去重，或先去「批量切片」产出切片。" />
                )}
              </div>
            ),
          },
          {
            key: 'upload',
            label: '批量文件拖入（上传→切片）',
            children: (
              <div>
                <Dragger multiple accept="video/*" showUploadList={false}
                  beforeUpload={(file) => handleUpload(file as unknown as File)} style={{ marginBottom: 12 }}>
                  <p className="ant-upload-drag-icon"><FileAddOutlined /></p>
                  <p className="ant-upload-text">点击或拖拽视频文件到此处（可多选）</p>
                  <p className="ant-upload-hint">上传后复用 batch-slice/run 切片链路，整片应用去重配置并自动派生变体。</p>
                </Dragger>
                {uploadedFiles.length > 0 && (
                  <Table
                    rowKey="uid" size="small" pagination={false} dataSource={uploadedFiles} style={{ marginBottom: 12 }}
                    columns={[
                      { title: '文件名', dataIndex: 'file_name', ellipsis: true },
                      { title: '大小', dataIndex: 'file_size', width: 120, render: (v: number) => formatSize(v) },
                      {
                        title: '状态', dataIndex: 'status', width: 110,
                        render: (s: string, r) =>
                          s === 'uploading' ? <Tag color="processing">上传中</Tag>
                            : s === 'done' ? <Tag color="success">就绪</Tag>
                              : <Tooltip title={r.error}><Tag color="error">失败</Tag></Tooltip>,
                      },
                      {
                        title: '操作', key: 'action', width: 70,
                        render: (_: unknown, r) => (
                          <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeUploaded(r.uid)} />
                        ),
                      },
                    ]}
                  />
                )}
              </div>
            ),
          },
        ]}
      />

      {/* 去重配置弹窗：档位 + 变体数 + 手动配置（复用 DedupeManualConfig 动态渲染） */}
      <Modal
        title="去重配置（档位 + 变体数量 + 手动手段）"
        open={configOpen}
        onOk={() => setConfigOpen(false)}
        onCancel={() => setConfigOpen(false)}
        width={560}
        footer={<Button type="primary" onClick={() => setConfigOpen(false)}>确定</Button>}
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Text>去重档位：</Text>
          <Select value={dedupePreset} onChange={setDedupePreset} options={DEDUPE_PRESET_OPTIONS} style={{ width: 220 }} />
          <Text>变体数量：</Text>
          <InputNumber min={1} max={20} value={variantCount} onChange={(v) => setVariantCount(v ?? 1)} style={{ width: 100 }} />
        </Space>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>每个素材派生 N 套去重变体（默认 3）</Text>
        <DedupeManualConfig value={dedupeManual} onChange={setDedupeManual} preset={dedupePreset} />
      </Modal>
    </Card>
  );
};

// 复用 SliceTasks/BatchSlice 的展示辅助：字节数格式化
const formatSize = (n: number): string => {
  if (!n) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
};

export default DedupeProcessing;
