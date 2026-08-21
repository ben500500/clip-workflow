import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card, Table, Tag, Button, Space, Typography, message, Modal, Select, InputNumber,
  Descriptions, Divider, Alert, Tooltip, Popconfirm, Row, Col, Empty, Collapse, Input, Badge,
} from 'antd';
import {
  ReloadOutlined, SafetyCertificateOutlined, LinkOutlined, SettingOutlined,
  ThunderboltOutlined, CheckCircleOutlined, SearchOutlined, FolderOpenOutlined,
  DeleteOutlined, DownloadOutlined, ClearOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { variantsApi, VariantGroup, VariantMatrixItem } from '../api/variants';
import { publishApi } from '../api/publish';
import type { VideoAccount } from '../types';

const { Text } = Typography;

// 变体状态 → 颜色/文案
const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待生成' },
  running: { color: 'processing', label: '生成中' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
  collision: { color: 'warning', label: '撞车' },
  skipped: { color: 'default', label: '跳过' },
};

const THRESHOLD_FIELDS: { key: 'phash' | 'audio' | 'seg' | 'combined'; label: string; hint: string }[] = [
  { key: 'phash', label: '画面 pHash', hint: '低于此值判定画面高度相似（默认 0.20）' },
  { key: 'audio', label: '音频声纹', hint: '低于此值判定音频撞车（默认 0.15）' },
  { key: 'seg', label: '时域序列', hint: '低于此值判定时域序列撞车（默认 0.30）' },
  { key: 'combined', label: '综合加权', hint: '加权综合距离（默认 0.15）' },
];

// 筛选维度
type FilterKey = 'all' | 'collision' | 'unbound';

const FILTER_OPTIONS: { value: FilterKey; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'collision', label: '有碰撞' },
  { value: 'unbound', label: '未绑定账号' },
];

const VariantMatrix: React.FC = () => {
  const [groups, setGroups] = useState<VariantGroup[]>([]);
  const [thresholds, setThresholds] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [videoAccounts, setVideoAccounts] = useState<VideoAccount[]>([]);
  // 浏览态：搜索 / 筛选 / 展开面板
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<FilterKey>('all');
  const [activeKeys, setActiveKeys] = useState<string[]>([]);
  // 绑定弹窗
  const [bindTarget, setBindTarget] = useState<VariantMatrixItem | null>(null);
  const [bindAccountId, setBindAccountId] = useState<string | undefined>();
  const [bindLoading, setBindLoading] = useState(false);
  // 阈值配置
  const [thresholdOpen, setThresholdOpen] = useState(false);
  const [thresholdForm, setThresholdForm] = useState<Record<string, number>>({});
  const [thresholdLoading, setThresholdLoading] = useState(false);

  const fetchMatrix = useCallback(async () => {
    setLoading(true);
    try {
      const data = await variantsApi.matrix();
      setGroups(data.variant_groups || []);
      setThresholds(data.thresholds || {});
    } catch (e) {
      message.error((e as Error).message || '加载变体矩阵失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchAccounts = useCallback(async () => {
    try {
      const accs = await publishApi.getVideoAccounts({});
      setVideoAccounts(Array.isArray(accs) ? accs : []);
    } catch {
      // 账号列表加载失败不阻塞矩阵
    }
  }, []);

  useEffect(() => {
    fetchMatrix();
    fetchAccounts();
  }, [fetchMatrix, fetchAccounts]);

  // ── 组统计与筛选排序 ──
  const enrichGroups = useCallback(
    (raw: VariantGroup[]) =>
      raw.map((g) => {
        let collisionCount = 0;
        let unboundCount = 0;
        for (const v of g.variants) {
          if (v.collision) collisionCount++;
          if (!v.account_id) unboundCount++;
        }
        return { ...g, collisionCount, unboundCount };
      }),
    []
  );

  // 应用搜索 + 筛选，并排序：碰撞多 → 未绑定多 → 时间倒序
  const visibleGroups = useMemo(() => {
    const kw = search.trim().toLowerCase();
    const filtered = enrichGroups(groups)
      .filter((g) => {
        if (kw && !(g.base_file_name || '').toLowerCase().includes(kw)) return false;
        if (filter === 'collision') return g.collisionCount > 0;
        if (filter === 'unbound') return g.unboundCount > 0;
        return true;
      })
      .sort((a, b) => {
        if (b.collisionCount !== a.collisionCount) return b.collisionCount - a.collisionCount;
        if (b.unboundCount !== a.unboundCount) return b.unboundCount - a.unboundCount;
        const ta = a.created_at ? dayjs(a.created_at).valueOf() : 0;
        const tb = b.created_at ? dayjs(b.created_at).valueOf() : 0;
        return tb - ta;
      });
    return filtered;
  }, [groups, search, filter, enrichGroups]);

  // 待处理（有碰撞）组默认展开；搜索结果变化时重置展开态
  const hasCollision = useMemo(
    () => visibleGroups.filter((g) => g.collisionCount > 0).map((g) => g.variant_group_id),
    [visibleGroups]
  );
  useEffect(() => {
    // 有碰撞的组自动展开，其余收起 —— 让运营第一眼看到要处理的
    setActiveKeys(hasCollision);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, filter]);

  const handleVerify = async (v: VariantMatrixItem) => {
    try {
      const result = await variantsApi.verify(v.id);
      if (result.safe) {
        message.success(`变体 ${v.variant_index} 复核通过，可安全发布`);
      } else {
        message.warning(`变体 ${v.variant_index} 复核未通过：${result.reason || '存在撞车风险'}`);
      }
    } catch (e) {
      message.error((e as Error).message || '复核失败');
    }
  };

  const openBind = (v: VariantMatrixItem) => {
    setBindTarget(v);
    setBindAccountId(v.account_id || undefined);
  };

  const handleBind = async () => {
    if (!bindTarget) return;
    setBindLoading(true);
    try {
      await variantsApi.bind(bindTarget.id, bindAccountId || null);
      message.success(`变体 ${bindTarget.variant_index} 账号绑定成功`);
      setBindTarget(null);
      fetchMatrix();
    } catch (e) {
      message.error((e as Error).message || '绑定失败');
    } finally {
      setBindLoading(false);
    }
  };

  const openThreshold = () => {
    setThresholdForm({ ...thresholds });
    setThresholdOpen(true);
  };

  const handleSaveThreshold = async () => {
    setThresholdLoading(true);
    try {
      const res = await variantsApi.updateThresholds(thresholdForm);
      setThresholds(res);
      message.success('撞车判定阈值已更新');
      setThresholdOpen(false);
    } catch (e) {
      message.error((e as Error).message || '保存阈值失败');
    } finally {
      setThresholdLoading(false);
    }
  };

  // #274 C：下载变体视频（presigned URL 强制下载）
  const handleDownload = async (v: VariantMatrixItem) => {
    try {
      const res = await variantsApi.downloadVariant(v.id);
      if (res.download_url) {
        window.open(res.download_url, '_blank');
      } else {
        message.warning('该变体没有可下载的文件');
      }
    } catch (e) {
      message.error((e as Error).message || '下载失败');
    }
  };

  // 整组一键打包下载（auth blob 触发，避免 window.open 带不上 auth header）
  const handleDownloadGroup = async (groupId: string) => {
    try {
      const blob = await variantsApi.downloadGroupZip(groupId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `variants_${groupId.slice(0, 8)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      message.success('整组变体已开始下载');
    } catch (e) {
      message.error((e as Error).message || '整组下载失败');
    }
  };

  // #274 B：删除单变体（DB + MinIO）
  const handleDeleteVariant = async (v: VariantMatrixItem) => {
    try {
      await variantsApi.removeVariant(v.id);
      message.success(`变体 ${v.variant_index === 1 ? '基准' : `变体 ${v.variant_index}`} 已删除`);
      fetchMatrix();
    } catch (e) {
      message.error((e as Error).message || '删除变体失败');
    }
  };

  // #274 B：删除整组（组内全部变体 + MinIO；基准切片输出保留）
  const handleDeleteGroup = async (g: VariantGroup) => {
    try {
      const res = await variantsApi.removeGroup(g.variant_group_id);
      message.success(`已删除整组 ${res.deleted} 个变体`);
      fetchMatrix();
    } catch (e) {
      message.error((e as Error).message || '删除整组失败');
    }
  };

  // #274 A4：清理存量卡住的 running 变体
  const handleCleanupStuck = async () => {
    setLoading(true);
    try {
      const res = await variantsApi.cleanupStuck(30);
      if (res.cleaned > 0) {
        message.success(`已清理 ${res.cleaned} 个卡住的生成任务`);
      } else {
        message.info('没有需要清理的卡住任务');
      }
      fetchMatrix();
    } catch (e) {
      message.error((e as Error).message || '清理失败');
    } finally {
      setLoading(false);
    }
  };

  const variantColumns: ColumnsType<VariantMatrixItem> = [
    {
      title: '变体', dataIndex: 'variant_index', width: 80,
      render: (v: number) => <Text strong>{v === 1 ? `基准 ${v}` : `变体 ${v}`}</Text>,
    },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (s: string) => {
        const meta = STATUS_META[s] || { color: 'default', label: s };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: '预览', dataIndex: 'preview_url', width: 170,
      render: (url: string | null | undefined) =>
        url ? (
          <video src={url} muted preload="metadata" controls
                 style={{ height: 120, borderRadius: 6, background: '#000' }} />
        ) : <Text type="secondary">-</Text>,
    },
    {
      title: '画面距离', dataIndex: 'phash_distance', width: 100,
      render: (v: number | null) => <DistanceCell v={v} threshold={thresholds.phash} label="phash" />,
    },
    {
      title: '音频距离', dataIndex: 'audio_distance', width: 100,
      render: (v: number | null) => <DistanceCell v={v} threshold={thresholds.audio} label="audio" />,
    },
    {
      title: '时域距离', dataIndex: 'seg_distance', width: 100,
      render: (v: number | null) => <DistanceCell v={v} threshold={thresholds.seg} label="seg" />,
    },
    {
      title: '结构差异', dataIndex: 'structural_diff', width: 130,
      render: (sd: Record<string, unknown> | null) => {
        if (!sd) return <Text type="secondary">-</Text>;
        const parts: string[] = [];
        if (sd.segment) parts.push('多段');
        if (sd.reorder) parts.push('重排');
        if (!sd.segment && !sd.reorder) parts.push('整段');
        return <Text type="secondary">{parts.join('+')}</Text>;
      },
    },
    {
      title: '撞车', dataIndex: 'collision', width: 110,
      render: (c: boolean, r) =>
        c ? (
          <Tooltip title={r.collision_reason || '存在撞车风险'}>
            <Tag color="red">撞车</Tag>
          </Tooltip>
        ) : (
          <Tag color="green">正常</Tag>
        ),
    },
    {
      title: '绑定账号', dataIndex: 'account_id', width: 160,
      render: (aid: string | null, r) => {
        if (!aid) return <Text type="secondary">未绑定</Text>;
        const acct = videoAccounts.find((a) => a.id === aid);
        return <Tag color="blue">{acct?.account_name || String(aid).slice(0, 8)}</Tag>;
      },
    },
    {
      title: '操作', key: 'action', width: 220, fixed: 'right',
      render: (_: unknown, r) => (
        <Space size={4}>
          <Tooltip title="发布前指纹复核">
            <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => handleVerify(r)}>
              复核
            </Button>
          </Tooltip>
          <Tooltip title="绑定视频号账号（一账号一变体）">
            <Button size="small" icon={<LinkOutlined />} onClick={() => openBind(r)}>
              绑定
            </Button>
          </Tooltip>
          <Tooltip title="下载变体视频">
            <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(r)} />
          </Tooltip>
          <Popconfirm
            title="确认删除该变体？"
            description="将同时删除 MinIO 变体文件，不可恢复。"
            okText="删除"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDeleteVariant(r)}
          >
            <Tooltip title="删除变体（DB + MinIO）">
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 折叠面板项
  const collapseItems = useMemo(
    () =>
      visibleGroups.map((g) => ({
        key: g.variant_group_id,
        label: (
          <Space size={8} wrap>
            <FolderOpenOutlined />
            <Text strong>变体组 {String(g.variant_group_id).slice(0, 8)}</Text>
            <Text type="secondary">{g.base_file_name || '—'}</Text>
            {g.collisionCount > 0 && <Badge count={g.collisionCount} color="red" title="碰撞数" />}
            {g.unboundCount > 0 && <Badge count={g.unboundCount} color="gold" title="未绑定账号数" />}
            <Text type="secondary" style={{ fontSize: 12 }}>
              {g.created_at ? dayjs(g.created_at).format('MM-DD HH:mm') : ''}
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>共 {g.variants.length} 变体</Text>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={(e) => { e.stopPropagation(); handleDownloadGroup(g.variant_group_id); }}
            >
              一键下载全部
            </Button>
            <Popconfirm
              title="确认删除整组变体？"
              description="将删除组内全部变体（DB + MinIO），基准切片输出保留。不可恢复。"
              okText="删除"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleDeleteGroup(g)}
            >
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={(e) => e.stopPropagation()}
              >
                删除整组
              </Button>
            </Popconfirm>
          </Space>
        ),
        children: (
          <Table
            rowKey="id"
            columns={variantColumns}
            dataSource={g.variants}
            loading={loading}
            size="small"
            pagination={false}
            scroll={{ x: 1300 }}
          />
        ),
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleGroups, loading, videoAccounts, thresholds]
  );

  return (
    <Card
      title={<Space><ThunderboltOutlined />变体矩阵看板（多视频号素材去重）</Space>}
      extra={
        <Space>
          <Tooltip title="清理存量卡住的生成任务（running 超时 30 分钟 → failed）">
            <Button size="small" icon={<ClearOutlined />} onClick={handleCleanupStuck}>清理卡住</Button>
          </Tooltip>
          <Button size="small" icon={<SettingOutlined />} onClick={openThreshold}>撞车阈值</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={fetchMatrix}>刷新</Button>
        </Space>
      }
      style={{ margin: 16 }}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="多视频号素材去重：一套切片派生 N 套结构性差异变体，各变体在画面/音频/时域三路指纹上互相拉开距离，供不同视频号分别上传，避免同素材原样发多号撞车。变体组默认收起，有碰撞需处理的组自动展开并置顶。"
      />

      {/* 浏览工具条：搜索 + 筛选 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: '#bbb' }} />}
          placeholder="按基准文件名搜索变体组"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 260 }}
        />
        <Select<FilterKey>
          value={filter}
          onChange={setFilter}
          options={FILTER_OPTIONS}
          style={{ width: 140 }}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {visibleGroups.length} 组 · {visibleGroups.reduce((s, g) => s + g.variants.length, 0)} 变体
          {filter !== 'all' || search ? '（已筛选）' : ''}
        </Text>
      </Space>

      {visibleGroups.length === 0 && !loading ? (
        <Empty description="没有匹配的变体组。在去重模式下配置「多版本数 > 1」切片后，将在此展示生成的素材变体。" />
      ) : (
        <Collapse
          activeKey={activeKeys}
          onChange={(keys) => setActiveKeys(keys as string[])}
          expandIconPosition="start"
          items={collapseItems}
        />
      )}

      {/* 账号绑定弹窗 */}
      <Modal
        title={`绑定账号 - ${bindTarget ? (bindTarget.variant_index === 1 ? '基准' : `变体 ${bindTarget.variant_index}`) : ''}`}
        open={!!bindTarget}
        onCancel={() => setBindTarget(null)}
        onOk={handleBind}
        confirmLoading={bindLoading}
        okText="绑定"
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="一个视频号账号只能绑定一个变体，防止同素材原样发多号被平台判定搬运。"
        />
        <Select
          style={{ width: '100%' }}
          placeholder="选择视频号账号"
          value={bindAccountId}
          onChange={setBindAccountId}
          allowClear
          options={videoAccounts.map((a) => ({
            value: a.id,
            label: `${a.account_name}（${a.platform}）`,
          }))}
        />
      </Modal>

      {/* 撞车阈值配置弹窗 */}
      <Modal
        title="撞车判定阈值（运营可调）"
        open={thresholdOpen}
        onCancel={() => setThresholdOpen(false)}
        onOk={handleSaveThreshold}
        confirmLoading={thresholdLoading}
        okText="保存"
      >
        <Descriptions column={1} size="small" style={{ marginBottom: 12 }}>
          {THRESHOLD_FIELDS.map((f) => (
            <Descriptions.Item key={f.key} label={f.label}>
              <Space>
                <InputNumber
                  min={0}
                  max={1}
                  step={0.01}
                  value={thresholdForm[f.key] ?? thresholds[f.key]}
                  onChange={(v) => setThresholdForm((p) => ({ ...p, [f.key]: v ?? 0 }))}
                  style={{ width: 100 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>{f.hint}</Text>
              </Space>
            </Descriptions.Item>
          ))}
        </Descriptions>
        <Divider />
        <Text type="secondary" style={{ fontSize: 12 }}>
          距离值越低越相似；低于阈值判定为撞车。调低阈值更宽松（更易通过），调高阈值更严格。
        </Text>
      </Modal>
    </Card>
  );
};

const DistanceCell: React.FC<{ v: number | null; threshold?: number; label: string }> = ({ v, threshold, label }) => {
  if (v === null || v === undefined) return <Text type="secondary">-</Text>;
  const th = threshold ?? 0.2;
  const safe = v > th;
  return (
    <Tooltip title={`${label} 距离 ${v.toFixed(3)}，阈值 ${th}`}>
      <Text style={{ color: safe ? '#389e0d' : '#cf1322' }}>
        {v.toFixed(3)}
        {safe ? <CheckCircleOutlined style={{ marginLeft: 4 }} /> : null}
      </Text>
    </Tooltip>
  );
};

export default VariantMatrix;
