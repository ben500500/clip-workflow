/**
 * 后台任务回看页（11-06 承诺审计④的落地）。
 *
 * 此前任务明细的唯一出口是顶部横幅（AssetJobBanner，only_open=true，任务一收敛就消失），
 * 「原因见后台任务列表」指向的页面根本不存在。这一页就是那个被承诺的页面：
 * 终态任务可回看、逐条结果（job.result.results 的 note/error）可展开、
 * 抽帧任务（系统自排、默认不列）可勾出来看——抽帧失败曾是最深的静默失败。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Card, Checkbox, Drawer, Select, Space, Table, Tag, Tooltip, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import type { AssetJobInfo, AssetJobKind, AssetJobStatus } from '../../api/assets';
import { assetApi } from '../../api/assets';

const { Text } = Typography;

const STATUS_COLOR: Record<AssetJobStatus, string> = {
  queued: 'default',
  running: 'processing',
  succeeded: 'success',
  failed: 'error',
  interrupted: 'warning',
};

const KIND_OPTIONS: Array<{ value: AssetJobKind; label: string }> = [
  { value: 'summary_generate', label: '出钩子文案' },
  { value: 'produce', label: '生成生产单' },
  { value: 'dispatch', label: '投板' },
  { value: 'download', label: '下载原片' },
  { value: 'frames', label: '抽帧' },
  { value: 'prompt_preview', label: '备豆包提示词' },
];

const STATUS_OPTIONS: Array<{ value: AssetJobStatus; label: string }> = [
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '在跑' },
  { value: 'succeeded', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'interrupted', label: '被打断' },
];

interface ResultRow {
  code?: string;
  id?: string;
  result?: string;
  error?: string;
  note?: string;
  reason?: string;
  frames?: number;
  created?: number;
  kept?: number;
}

const summarize = (job: AssetJobInfo): string => {
  if (job.error) return job.error;
  const rows = ((job.result as { results?: ResultRow[] } | null)?.results ?? []) as ResultRow[];
  if (!rows.length) return '';
  const bad = rows.filter((r) => r.error || (r.result && r.result !== 'extracted' && r.note) || r.reason);
  if (bad.length) return `${bad.length} 条要留意：${bad[0].code ?? ''}${bad[0].error ?? bad[0].note ?? bad[0].reason ?? ''}`.slice(0, 80);
  return '';
};

const fmtTime = (iso: string | null): string => (iso ? iso.slice(5, 16).replace('T', ' ') : '—');

const AssetJobsPanel: React.FC = () => {
  const [items, setItems] = useState<AssetJobInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [kind, setKind] = useState<AssetJobKind | undefined>();
  const [status, setStatus] = useState<AssetJobStatus | undefined>();
  const [includeFrames, setIncludeFrames] = useState(false);
  const [detail, setDetail] = useState<AssetJobInfo | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await assetApi.listAssetJobs({
        kind,
        status,
        include_frames: includeFrames,
        limit: 50,
      });
      setItems(res.items || []);
    } catch (e) {
      message.error((e as Error).message || '拉任务列表失败');
    } finally {
      setLoading(false);
    }
  }, [kind, status, includeFrames]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  // 还有在跑/排队的就 8 秒自刷，全部终态就停（和横幅同一口径）
  const hasOpen = useMemo(() => items.some((j) => j.status === 'queued' || j.status === 'running'), [items]);
  useEffect(() => {
    if (!hasOpen) return;
    const t = setInterval(fetchList, 8000);
    return () => clearInterval(t);
  }, [hasOpen, fetchList]);

  const resultRows: ResultRow[] = useMemo(() => {
    if (!detail) return [];
    return ((detail.result as { results?: ResultRow[] } | null)?.results ?? []) as ResultRow[];
  }, [detail]);

  const columns: ColumnsType<AssetJobInfo> = [
    {
      title: '任务号',
      dataIndex: 'id',
      width: 110,
      render: (v: string) => <Text code copyable={{ text: v }}>{v.slice(0, 8)}</Text>,
    },
    { title: '类型', dataIndex: 'kind_label', width: 110 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: AssetJobStatus, row: AssetJobInfo) => <Tag color={STATUS_COLOR[v] || 'default'}>{row.status_label || v}</Tag>,
    },
    {
      title: '进度',
      key: 'progress',
      width: 130,
      render: (_, row: AssetJobInfo) => {
        if (row.status === 'succeeded') return `共 ${row.planned_units ?? '—'} 条`;
        const p = row.progress;
        if (!p || (p.done ?? -1) < 0) return `${row.planned_units ?? '—'} 条`;
        return `${p.done}/${p.total ?? row.planned_units ?? '?'}`;
      },
    },
    {
      title: '摘要',
      key: 'summary',
      render: (_, row: AssetJobInfo) => {
        const s = summarize(row);
        return s ? (
          <Tooltip title={s}>
            <Text type={row.status === 'failed' ? 'danger' : 'warning'} style={{ fontSize: 12 }}>
              {s}
            </Text>
          </Tooltip>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>—</Text>
        );
      },
    },
    { title: '开始', dataIndex: 'started_at', width: 110, render: fmtTime },
    { title: '结束', dataIndex: 'finished_at', width: 110, render: fmtTime },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, row: AssetJobInfo) => (
        <a onClick={() => setDetail(row)}>{resultRowsVisible(row) ? '明细' : '详情'}</a>
      ),
    },
  ];

  function resultRowsVisible(row: AssetJobInfo): boolean {
    const rows = ((row.result as { results?: ResultRow[] } | null)?.results ?? []) as ResultRow[];
    return rows.length > 0;
  }

  return (
    <Card
      size="small"
      title="后台任务"
      extra={
        <Space wrap>
          <Select
            style={{ width: 140 }}
            placeholder="类型"
            allowClear
            value={kind}
            onChange={setKind}
            options={KIND_OPTIONS}
          />
          <Select
            style={{ width: 110 }}
            placeholder="状态"
            allowClear
            value={status}
            onChange={setStatus}
            options={STATUS_OPTIONS}
          />
          <Checkbox checked={includeFrames} onChange={(e) => setIncludeFrames(e.target.checked)}>
            含系统自排的抽帧任务
          </Checkbox>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={fetchList}>
            刷新
          </Button>
        </Space>
      }
    >
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          顶部横幅只挂着「还在跑」的；任务一收敛就从横幅消失——要回看终态、看逐条成败，都在这一页。
          {hasOpen && '（有在跑的任务，8 秒自刷）'}
        </Text>
      </div>
      <Table
        size="small"
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{ pageSize: 15, hideOnSinglePage: true, showSizeChanger: false }}
      />
      <Drawer
        title={detail ? `任务 ${detail.id.slice(0, 8)} · ${detail.kind_label}` : ''}
        width={640}
        open={!!detail}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Space size={8} wrap>
              <Tag color={STATUS_COLOR[detail.status] || 'default'}>{detail.status_label || detail.status}</Tag>
              {detail.batch_id && <Text type="secondary">批次 {detail.batch_id.slice(0, 8)}</Text>}
              <Text type="secondary">{fmtTime(detail.started_at)} → {fmtTime(detail.finished_at)}</Text>
            </Space>
            {detail.error && (
              <Card size="small" title="失败原因">
                <Text type="danger">{detail.error}</Text>
              </Card>
            )}
            {resultRows.length > 0 && (
              <Card size="small" title={`逐条结果（${resultRows.length} 条）`}>
                <Table
                  size="small"
                  rowKey={(r, i) => `${r.id ?? r.code ?? i}`}
                  dataSource={resultRows}
                  pagination={resultRows.length > 12 ? { pageSize: 12 } : false}
                  columns={[
                    { title: '对象', dataIndex: 'code', width: 130, render: (v) => v ?? '—' },
                    {
                      title: '结果',
                      key: 'r',
                      width: 90,
                      render: (_, r: ResultRow) => {
                        const label = r.result ?? (r.error ? '失败' : r.created != null ? `新建 ${r.created}` : '—');
                        const color =
                          label === 'extracted' || label === '成功'
                            ? 'success'
                            : label === '失败'
                              ? 'error'
                              : label === 'skipped'
                                ? 'warning'
                                : 'default';
                        return <Tag color={color}>{label}</Tag>;
                      },
                    },
                    {
                      title: '原因／说明',
                      key: 'why',
                      render: (_, r: ResultRow) => (
                        <Text style={{ fontSize: 12 }}>{r.error ?? r.note ?? r.reason ?? '—'}</Text>
                      ),
                    },
                  ]}
                />
              </Card>
            )}
            {!detail.error && !resultRows.length && (
              <Text type="secondary">这条任务没有逐条明细（整份回执只有汇总）。</Text>
            )}
          </Space>
        )}
      </Drawer>
    </Card>
  );
};

export default AssetJobsPanel;
