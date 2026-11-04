import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Checkbox, Col, Input, Modal, Radio, Row, Select, Space, Statistic, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import { CopyOutlined, DownloadOutlined, ExportOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  DISPATCH_REPORT_STATUSES, PRODUCTION_STATE_LABELS, assetApi,
} from '../../api/assets';
import type {
  AssetDispatchCounts, AssetExportJson, AssetExportPayload, AssetExportTxt, AssetProduction, DispatchReportStatus, ProductionState,
} from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { MonoText, ProductionStateTag } from './AssetBits';

const { Text, Paragraph } = Typography;

interface Props {
  /** 投放结果登记与投产同侧：operator + admin */
  canWriteBack: boolean;
  /** 「带违禁词强行导出」只有 admin 能做（后端同一道闸，前端只决定按钮给不给） */
  isAdmin: boolean;
  batchId?: string;
  /** 后台投产任务收敛后自增（D-1）：生产单是后端建行的，只能重新拉才看得到 */
  reloadToken?: number;
}

const rate = (v: number | null | undefined) =>
  v === null || v === undefined ? '—（还没有终态样本）' : `${Math.round(v * 100)}%`;

/**
 * 生产单面板：台账 + 投递计数 + 导出 + 人工回写投递态。
 *
 * 两个计数口径不能混（这是最容易看错的地方）：
 *  - `dispatch.by_status` 跟 batch_id/asset_id 走、**不跟 status= 走**：
 *    筛「失败」时如果 by_status 跟着筛，就变成「failed: 12」自己报自己，成功几条这个关键数消失了；
 *  - `dispatch.today.board_rows` = Σ board_total＝号池今天真吃进去的条数（软提示线比它，不是行数）；
 *    `board_capacity.already_today` 含未投单，两者不等价，别互相换算。
 * P0 没有自动投递：导出 payload → 人在企微后台建任务 → 回来把 queued/running/success/failed 填上。
 */
const AssetProductionPanel: React.FC<Props> = ({ canWriteBack, isAdmin, batchId, reloadToken }) => {
  const [items, setItems] = useState<AssetProduction[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [loading, setLoading] = useState(false);
  const [dispatch, setDispatch] = useState<AssetDispatchCounts | null>(null);

  const [status, setStatus] = useState<string | undefined>();
  const [batchFilter, setBatchFilter] = useState<string | undefined>(batchId);
  const [assetFilter, setAssetFilter] = useState<string | undefined>();

  const [selected, setSelected] = useState<AssetProduction[]>([]);
  const [writeOpen, setWriteOpen] = useState(false);
  const [writeStatus, setWriteStatus] = useState<DispatchReportStatus>('queued');
  const [writeError, setWriteError] = useState('');
  const [writeTid, setWriteTid] = useState('');
  const [busy, setBusy] = useState(false);

  const [exportOpen, setExportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<'json' | 'txt' | 'payload'>('txt');
  const [exportAccounts, setExportAccounts] = useState(1);
  const [exportOnlySelected, setExportOnlySelected] = useState(false);
  const [exportData, setExportData] = useState<AssetExportTxt | AssetExportPayload | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  // R-4：导出会按**当前**违禁词表重扫正文，命中的单子会被挡下。放行只有 admin，且必须写一句理由。
  const [exportForceRisk, setExportForceRisk] = useState(false);
  const [exportForceReason, setExportForceReason] = useState('');

  const ids = useMemo(() => selected.map((s) => s.id), [selected]);

  const fetchList = useCallback(
    async (p: number = page, ps: number = pageSize) => {
      setLoading(true);
      try {
        const res = await assetApi.listProductions({
          page: p,
          page_size: ps,
          status,
          batch_id: batchFilter,
          asset_id: assetFilter,
        });
        setItems(res.items || []);
        setTotal(res.total || 0);
        setPage(res.page || p);
        setDispatch(res.dispatch || null);
      } catch (e) {
        message.error((e as Error).message || '加载生产单失败');
      } finally {
        setLoading(false);
      }
    },
    [status, batchFilter, assetFilter, page, pageSize],
  );

  useEffect(() => {
    fetchList(1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, batchFilter, assetFilter]);

  // 后台投产任务跑完（D-1）：生产单行是后端建的，只能重新拉
  useEffect(() => {
    if (!reloadToken) return;
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  const submitWriteBack = async () => {
    if (!ids.length) return;
    if (writeStatus === 'failed' && !writeError.trim()) {
      message.warning('判失败必须写成因（板上失败行没有原因字段，这是我们的判读）');
      return;
    }
    if (writeTid && ids.length > 1) {
      message.warning('board_tid 是逐条钉的回读主键，多条时只能单选后逐条填');
      return;
    }
    setBusy(true);
    try {
      const res = await assetApi.updateProductionStatus({
        ids,
        status: writeStatus,
        error: writeError || undefined,
        board_tid: writeTid || undefined,
      });
      setDispatch(res.dispatch);
      Modal.info({
        title: res.message,
        width: 620,
        content: (
          <Space direction="vertical" style={{ width: '100%' }}>
            {!!res.unchanged?.length && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                同态幂等跳过 {res.unchanged.length} 条（已经报过这个态）
              </Text>
            )}
            {!!res.blocked?.length && (
              <Alert
                type="error"
                showIcon
                message={`${res.blocked.length} 条被迁移规则挡下`}
                description={
                  <Space direction="vertical" size={2}>
                    {res.blocked.slice(0, 8).map((b) => (
                      <Text key={b.id} style={{ fontSize: 12 }}>
                        {b.hook_code || b.id.slice(0, 8)}：{b.from} → {b.to}｜{b.reason}
                      </Text>
                    ))}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      允许的迁移：待投放→任意；已投→出片中/成功/失败；出片中→成功/失败；失败→重投或改判成功；成功→只允许改判失败（成片回收后发现不可用，必须写成因）。
                    </Text>
                  </Space>
                }
              />
            )}
          </Space>
        ),
      });
      setWriteOpen(false);
      setSelected([]);
      fetchList(page, pageSize);
    } catch (e) {
      message.error((e as Error).message || '回写失败');
    } finally {
      setBusy(false);
    }
  };

  const doExport = async (forceRisk = false) => {
    if (forceRisk && !exportForceReason.trim()) {
      message.warning('强行导出要写一句为什么（这句话会进审计，事后对账全靠它）');
      return;
    }
    setExportBusy(true);
    try {
      const res = await assetApi.exportProductions({
        batch_id: exportOnlySelected || !batchFilter ? undefined : batchFilter,
        asset_id: assetFilter,
        ids: exportOnlySelected && ids.length ? ids.join(',') : undefined,
        accounts: exportAccounts,
        format: exportFormat,
        force_risk: forceRisk || undefined,
        force_reason: forceRisk ? exportForceReason.trim() : undefined,
      });
      if (res.format === 'json') {
        setExportData(null);
        message.info('json 这种只给清单、不给正文：要粘进豆包的文本选 txt，要往企微后台建任务的参数选「板面七键」');
      } else {
        setExportData(res as AssetExportTxt | AssetExportPayload);
      }
    } catch (e) {
      message.error((e as Error).message || '导出失败');
    } finally {
      setExportBusy(false);
    }
  };

  const copyText = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    message.success(`${label}已复制到剪贴板`);
  };

  const download = (name: string, text: string) => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: ColumnsType<AssetProduction> = [
    {
      title: '钩子号',
      dataIndex: 'hook_code',
      width: 96,
      render: (v: string | null) => (v ? <MonoText>{v}</MonoText> : <Tag color="orange">缺号</Tag>),
    },
    { title: '#', dataIndex: 'seq', width: 46 },
    {
      title: '板上 name / 素材',
      key: 'name',
      ellipsis: true,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text>{r.board_name || '（无推荐标题）'}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.asset_id.slice(0, 8)}｜变体：{r.variant_basis || '-'}
          </Text>
        </Space>
      ),
    },
    {
      title: '板面',
      key: 'board',
      width: 150,
      render: (_, r) => (
        <Tooltip title={`tag ${r.board_tag || '-'}｜date ${r.board_date || '-'}｜tid ${r.board_tid || '-'}`}>
          <Space size={2} wrap>
            <Tag>total {r.board_total}</Tag>
            {r.board_tid ? <Tag color="blue">有 tid</Tag> : <Tag>无 tid</Tag>}
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 108,
      render: (v: ProductionState) => <ProductionStateTag status={v} />,
    },
    {
      title: '投递',
      key: 'attempts',
      width: 130,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text>
            {r.attempts > 0 ? `投 ${r.attempts} 次` : '未投'}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.started_at ? `起 ${parseServerTime(r.started_at)?.format('MM-DD HH:mm')}` : ''}
            {r.completed_at ? `｜完 ${parseServerTime(r.completed_at)?.format('MM-DD HH:mm')}` : ''}
          </Text>
        </Space>
      ),
    },
    {
      title: '正文',
      dataIndex: 'prompt_text',
      width: 210,
      render: (v: string | null, r) =>
        v ? (
          <Space size={2}>
            {/* expandable: 'collapsible'（antd ≥5.18）——原来写 `expandable: true` 只能展开、
                点了「展开」之后那个按钮就没了，长正文收不回去，表格里一撑到底（11-04 用户反馈）。 */}
            <Paragraph
              style={{ marginBottom: 0, fontSize: 12 }}
              ellipsis={{ rows: 2, expandable: 'collapsible', symbol: (expanded) => (expanded ? '收起' : '展开') }}
            >
              {v}
            </Paragraph>
            <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(v, '提示词')} />
          </Space>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.error ? `（不外泄：${r.error}）` : '（裸单/未展开）'}
          </Text>
        ),
    },
    {
      title: '提醒',
      key: 'warn',
      width: 110,
      render: (_, r) => (
        <Space size={2} wrap>
          {r.drift && (
            <Tooltip title={r.drift_reason || ''}>
              <Tag color="red">漂移</Tag>
            </Tooltip>
          )}
          {r.error && (
            <Tooltip title={r.error}>
              <Tag color="volcano">有成因</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  const today = dispatch?.today;

  return (
    <Card size="small">
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={4}>
          <Statistic title="生产单" value={dispatch?.total ?? 0} />
        </Col>
        <Col span={4}>
          <Statistic title="待投放" value={dispatch?.order_ready ?? 0} />
        </Col>
        <Col span={4}>
          <Statistic title="已投" value={dispatch?.dispatched ?? 0} />
        </Col>
        <Col span={4}>
          <Statistic title="成功" value={dispatch?.succeeded ?? 0} valueStyle={{ color: '#3f8600' }} />
        </Col>
        <Col span={4}>
          <Statistic title="失败" value={dispatch?.failed ?? 0} valueStyle={{ color: '#cf1322' }} />
        </Col>
        <Col span={4}>
          <Statistic title="成功率（只按终态）" value={rate(dispatch?.success_rate)} />
        </Col>
      </Row>

      {today && (
        <Alert
          type={today.over_cap > 0 ? 'error' : today.board_rows > today.soft_cap * 0.8 ? 'warning' : 'info'}
          showIcon
          style={{ marginBottom: 12 }}
          message={`${today.day} 号池：吃掉 ${today.board_rows} 条（Σ 板上 total）／软提示线 ${today.soft_cap} 条／板上任务 ${today.tasks} 行（按 board_date，还没投的单不在里面）；成功 ${today.succeeded}、失败 ${today.failed}${today.over_cap > 0 ? `；超线 ${today.over_cap} 条` : ''}`}
          description={
            <Space direction="vertical" size={2}>
              {today.note && <Text style={{ fontSize: 12 }}>{today.note}</Text>}
              <Text type="secondary" style={{ fontSize: 12 }}>
                {dispatch?.scope_note}｜产能不做硬限（11-03 拍板），这里只把数报清楚。
              </Text>
            </Space>
          }
        />
      )}

      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 140 }}
          value={status}
          onChange={setStatus}
          options={Object.entries(PRODUCTION_STATE_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <Input
          placeholder="批次 ID"
          allowClear
          style={{ width: 170 }}
          value={batchFilter}
          onChange={(e) => setBatchFilter(e.target.value || undefined)}
        />
        <Input
          placeholder="素材 ID"
          allowClear
          style={{ width: 170 }}
          value={assetFilter}
          onChange={(e) => setAssetFilter(e.target.value || undefined)}
        />
        <Button icon={<ReloadOutlined />} onClick={() => fetchList(page, pageSize)}>
          刷新
        </Button>
        <Button icon={<ExportOutlined />} onClick={() => setExportOpen(true)}>
          导出（txt / 板面七键）
        </Button>
        {canWriteBack && (
          <Button
            type="primary"
            disabled={!ids.length}
            onClick={() => {
              setWriteStatus('queued');
              setWriteError('');
              setWriteTid('');
              setWriteOpen(true);
            }}
          >
            回写投递态（{ids.length}）
          </Button>
        )}
      </Space>

      <Table<AssetProduction>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1250 }}
        rowSelection={
          canWriteBack
            ? {
                selectedRowKeys: ids,
                onChange: (_, rows) => {
                  setSelected(rows);
                  setExportOnlySelected(false);
                },
              }
            : undefined
        }
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 张单`,
          onChange: (p, ps) => {
            setPageSize(ps);
            fetchList(p, ps);
          },
        }}
      />

      <Modal
        open={writeOpen}
        title={`回写 ${ids.length} 张生产单的投递态`}
        onCancel={() => setWriteOpen(false)}
        onOk={submitWriteBack}
        confirmLoading={busy}
        okText="提交"
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Radio.Group
            value={writeStatus}
            onChange={(e) => setWriteStatus(e.target.value as DispatchReportStatus)}
            optionType="button"
            options={DISPATCH_REPORT_STATUSES.map((s) => ({ value: s, label: PRODUCTION_STATE_LABELS[s] }))}
          />
          {writeStatus === 'failed' && (
            <Input.TextArea
              rows={2}
              placeholder="失败成因（必填，我们侧判读；板上失败行没有原因字段）"
              value={writeError}
              onChange={(e) => setWriteError(e.target.value)}
            />
          )}
          <Input
            placeholder="board_tid（回读主键，多条时留空）"
            value={writeTid}
            disabled={ids.length > 1}
            onChange={(e) => setWriteTid(e.target.value)}
          />
          <Alert
            type="info"
            showIcon
            message="P0 没有自动投递：投板是人在企微后台做的动作，这里只是把台账补上"
            description={
              <span style={{ fontSize: 12 }}>
                同态重报幂等跳过；queued 每报一次 attempts +1（重投也计）。
                superseded/cancelled/skipped 是系统态，写不进来。
              </span>
            }
          />
        </Space>
      </Modal>

      <Modal
        open={exportOpen}
        title="导出提示词"
        width={860}
        onCancel={() => setExportOpen(false)}
        footer={
          exportData ? (
            <Space>
              <Button onClick={() => setExportData(null)}>重新选</Button>
              <Button
                icon={<DownloadOutlined />}
                onClick={() =>
                  download(
                    `生产单-${exportData.format}-${exportData.count}条.txt`,
                    exportData.format === 'txt'
                      ? exportData.export_text || ''
                      : JSON.stringify((exportData as AssetExportPayload).payloads || [], null, 2),
                  )
                }
              >
                下载
              </Button>
              <Button
                type="primary"
                onClick={() =>
                  copyText(
                    exportData.format === 'txt'
                      ? exportData.export_text || ''
                      : JSON.stringify((exportData as AssetExportPayload).payloads || [], null, 2),
                    exportData.format === 'txt' ? '文本' : '板面七键',
                  )
                }
              >
                复制
              </Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={() => setExportOpen(false)}>关闭</Button>
              <Button type="primary" loading={exportBusy} onClick={() => doExport()}>
                生成
              </Button>
            </Space>
          )
        }
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Space wrap>
            <Radio.Group
              value={exportFormat}
              onChange={(e) => {
                setExportFormat(e.target.value);
                setExportData(null);
              }}
              optionType="button"
              options={[
                { value: 'json', label: 'json（只出清单，不给正文）' },
                { value: 'txt', label: 'txt（段头+正文+推荐标题，可粘豆包）' },
                { value: 'payload', label: '板面七键（企微后台建任务那七个字段）' },
              ]}
            />
            <span>
              <Text>豆包号数：</Text>
              <Input
                type="number"
                min={1}
                max={50}
                style={{ width: 70, marginLeft: 4 }}
                value={exportAccounts}
                onChange={(e) => setExportAccounts(Math.max(1, Number(e.target.value) || 1))}
              />
            </span>
            <Checkbox checked={exportOnlySelected} onChange={(e) => setExportOnlySelected(e.target.checked)}>
              只导选中的 {ids.length} 张
            </Checkbox>
          </Space>

          {exportData ? (
            <>
              <Alert
                type={exportData.blocked_count ? 'warning' : 'success'}
                showIcon
                message={`共 ${exportData.count} 张，可投 ${exportData.ready} 张，挡下 ${exportData.blocked_count} 张；按 ${exportData.capacity.account_count} 号折算 ${exportData.capacity.days} 天`}
                description={
                  <span style={{ fontSize: 12 }}>
                    {exportData.note}
                    {exportData.format === 'payload' && (exportData as AssetExportPayload).card_advisory
                      ? `｜${(exportData as AssetExportPayload).card_advisory}`
                      : ''}
                  </span>
                }
              />
              {!!exportData.blocked?.length && (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    被挡下的（状态照实回显、正文不外泄）：
                  </Text>
                  <Space wrap size={4} style={{ marginTop: 4 }}>
                    {exportData.blocked.slice(0, 20).map((b) => (
                      <Tooltip key={b.id} title={b.reason}>
                        {/* blocked 只有 id/seq/status/reason（后端不给正文），所以按单号点名 */}
                        <Tag color="red">
                          {b.id.slice(0, 8)}#{b.seq}（{PRODUCTION_STATE_LABELS[b.status]}）
                        </Tag>
                      </Tooltip>
                    ))}
                  </Space>
                </div>
              )}
              {/* R-4：导出前按当前违禁词表重扫——命中的一定是「过审之后运营才加的词」，
                  所以这里必须单独说清楚，不能混在「作废/失败」那堆里让一线以为是单子坏了。 */}
              {!!(exportData as AssetExportJson).risk_recheck?.hit_count && (
                <Alert
                  type={(exportData as AssetExportJson).risk_recheck?.blocked?.length ? 'error' : 'warning'}
                  showIcon
                  message={
                    `${(exportData as AssetExportJson).risk_recheck!.hit_count} 张单的正文里有现在不许用的词：`
                    + `${(exportData as AssetExportJson).risk_recheck!.blocked.length} 张已挡下`
                    + ((exportData as AssetExportJson).risk_recheck!.forced?.length
                      ? `、${(exportData as AssetExportJson).risk_recheck!.forced.length} 张由管理员放行`
                      : '')
                  }
                  description={
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <Text style={{ fontSize: 12 }}>
                        {(exportData as AssetExportJson).risk_recheck!.note}
                      </Text>
                      <Space wrap size={4}>
                        {(exportData as AssetExportJson).items
                          .filter((i) => i.risk_hits?.length)
                          .map((i) => (
                            <Tag key={i.id} color={i.risk_forced ? 'orange' : 'red'}>
                              {i.hook_code || i.id.slice(0, 8)}#{i.seq}：
                              {i.risk_hits!.map((x) => x.word).join('、')}
                              {i.risk_forced ? '（已放行）' : ''}
                            </Tag>
                          ))}
                      </Space>
                      {isAdmin
                        && (exportData as AssetExportJson).risk_recheck!.blocked.length > 0 && (
                        <Space wrap>
                          <Input
                            style={{ width: 320 }}
                            placeholder="写一句为什么这些词在这批里没问题（会进审计）"
                            value={exportForceReason}
                            onChange={(e) => setExportForceReason(e.target.value)}
                          />
                          <Button size="small" loading={exportBusy} onClick={() => doExport(true)}>
                            管理员：带理由强行导出
                          </Button>
                        </Space>
                      )}
                      {!isAdmin && (exportData as AssetExportJson).risk_recheck!.blocked.length > 0 && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          要放行得找管理员（谁能导、谁不能导是审核口径定的，不是投放这边自己判）；
                          或者回去改文案、重新投产。
                        </Text>
                      )}
                    </Space>
                  }
                />
              )}
              {exportData.format === 'txt' ? (
                <Paragraph>
                  <pre style={{ maxHeight: 420, overflow: 'auto', fontSize: 12, whiteSpace: 'pre-wrap' }}>
                    {exportData.export_text || '（没有可交付的正文）'}
                  </pre>
                </Paragraph>
              ) : (
                <Table
                  size="small"
                  rowKey={(r) => r.id}
                  dataSource={(exportData as AssetExportPayload).payloads || []}
                  pagination={{ pageSize: 5 }}
                  columns={[
                    { title: '编号', dataIndex: 'hook_code', width: 90, render: (v: string | null) => v || '-' },
                    { title: '素材', dataIndex: 'asset_code', width: 100 },
                    {
                      title: '七键',
                      key: 'p',
                      render: (_, r: AssetExportPayload['payloads'][number]) => (
                        <Space size={2} wrap>
                          {Object.keys(r.payload).map((k) => (
                            <Tag key={k}>{k}</Tag>
                          ))}
                        </Space>
                      ),
                    },
                    {
                      title: '',
                      key: 'copy',
                      width: 90,
                      render: (_, r: AssetExportPayload['payloads'][number]) => (
                        <Button size="small" onClick={() => copyText(JSON.stringify(r.payload), '这单的板面七键')}>
                          复制
                        </Button>
                      ),
                    },
                  ]}
                />
              )}
            </>
          ) : (
            <Text type="secondary">
              选一种形态再点「生成」。txt 每条是「段头（五位编号）+ 正文 + 推荐标题（编号在尾）」一整块，末尾接这一批的产出清单，复制进豆包就能用；
              板面七键每条是企微后台「创建AI视频」要收的那七个字段，复制过去直接建任务。
            </Text>
          )}
        </Space>
      </Modal>
    </Card>
  );
};

export default AssetProductionPanel;
