import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Modal, Select, Space, Spin, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { assetApi } from '../../api/assets';
import type { AssetSummary, AssetSummaryListParams } from '../../api/assets';
import { parseServerTime } from '../../utils/format';
import { AuditStatusTag, MonoText } from './AssetBits';

const { Text } = Typography;

/**
 * 文案列表口后端 `page_size` 封顶就是 300：一次取满，取不满就在界面上说
 * 「只列了一部分」，不装作看全了（原来生产单页那种「两态各拉 300 再前端拼」
 * 量大时 total 会把人骗到——批 M 后端补了逗号多状态 + asset_ids，一次请求
 * 就能拿到准确的全集，这里统一走那一条路）。
 */
const PAGE_SIZE = 300;

/** ② 页勾到的素材：id 拿去捞文案，code 用来点名「哪几条排在外面」 */
export interface PickerAsset {
  id: string;
  code: string;
}

interface Props {
  open: boolean;
  onCancel: () => void;
  /**
   * 勾完点「去生成生产单」：选中的文案交回父层，由父层开 `ProduceOrderModal`。
   * 风险词、一致性、钩子编号、号池、成本这些闸门**只在投产弹窗里有一套**，
   * 这里只管「选哪几条文案」，绝不重算第二套（第二套早晚和第一套对不上）。
   */
  onConfirm: (rows: AssetSummary[]) => void;
  /** 弹窗标题：两页话术不同，但都必须在标题里点清范围 */
  title: string;
  /**
   * 给了它＝**按勾选素材取**（② 素材页「投去 AI 生成」）：走 `asset_ids` 口，
   * 不再摆批次筛选（范围已经由勾选钉死了，再套一层批次只会让人以为还能放宽）。
   * 不给＝按批次/全库取（④ 生产单页「从过审文案开单」）。
   */
  assets?: PickerAsset[];
  /** 「按批次取」模式下的批次下拉数据——父层本来就有，别在这里再发一次请求 */
  batchOptions?: { value: string; label: string }[];
}

/**
 * 过审文案挑选弹窗（②④ 两页共用，11-09 收的「两套入口」）。
 *
 * 为什么要有这个文件：批 L 在生产单页做了一版挑选器，批 M 又在素材列表页做了
 * 一版长得几乎一样、拉法却不同的挑选器（旧那版「approved / passed_edited 各拉
 * 300 条再前端拼」）。两版并存迟早出现「同一句按钮话术、两种数出来的条数」，
 * 现在收成一个组件，两种范围（按素材 / 按批次）用 props 分流。
 */
const ApprovedSummaryPickerModal: React.FC<Props> = ({
  open, onCancel, onConfirm, title, assets, batchOptions,
}) => {
  const byAssets = !!assets?.length;
  const [batch, setBatch] = useState<string | undefined>();
  const [rows, setRows] = useState<AssetSummary[]>([]);
  const [sel, setSel] = useState<AssetSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // 只在打开时取数；assets/batch 变了重新取（弹窗关着不占请求）
  const assetIdsKey = useMemo(
    () => (byAssets ? assets!.map((a) => a.id).join(',') : ''),
    [byAssets, assets],
  );

  useEffect(() => {
    if (!open) return;
    // 每次开弹窗都从干净状态起：上一次的勾选跨范围留着＝投出去才发现多带了几条
    setSel([]);
    let cancelled = false;
    setLoading(true);
    const params: AssetSummaryListParams = {
      // 一次请求拿全「已过审 + 改后通过」：后端 11-09 起支持逗号多状态 + asset_ids，
      // 所以 total 是准的。别退回「两态各拉 300 条再前端拼」——量大时那样 total 会骗人。
      audit_status: 'approved,passed_edited',
      page_size: PAGE_SIZE,
    };
    if (byAssets) params.asset_ids = assetIdsKey;
    else if (batch) params.batch_id = batch;

    assetApi
      .listSummaries(params)
      .then((res) => {
        if (cancelled) return;
        const items = [...(res.items || [])].sort((x, y) =>
          (y.reviewed_at || '').localeCompare(x.reviewed_at || ''),
        );
        setRows(items);
        setTotal(res.total || 0);
      })
      .catch((e) => {
        if (cancelled) return;
        // 拉不到就别留一个空壳弹窗：关掉 + 报错，让人重点
        setRows([]);
        setTotal(0);
        onCancel();
        message.error((e as Error).message || '过审文案拉不到');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // onCancel 每次渲染都是新函数，放进依赖会让 effect 反复重发；它只做「关闭」，不进依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, byAssets, assetIdsKey, batch]);

  /** 按素材取时，点名「勾了但没有过审文案」的那几条——不点名就得挨个开抽屉查 */
  const missingCodes = useMemo(() => {
    if (!byAssets) return [];
    const covered = new Set(rows.map((r) => r.asset_id));
    return assets!.filter((a) => !covered.has(a.id)).map((a) => a.code);
  }, [byAssets, assets, rows]);

  const truncated = rows.length < total;

  const columns: ColumnsType<AssetSummary> = [
    {
      title: '素材',
      dataIndex: 'asset_code',
      width: 112,
      // 列表口 join 素材行才有 asset_code；万一没带就退回 id 前缀，不给一个空「—」
      render: (v: string | undefined, row) => (
        <MonoText>{(v || row.asset_id).slice(0, 11)}</MonoText>
      ),
    },
    {
      title: '文案',
      dataIndex: 'text',
      ellipsis: true,
      render: (v: string, row) => (
        <span style={{ fontSize: 12 }}>
          #{row.seq} {v}
        </span>
      ),
    },
    { title: '字数', dataIndex: 'word_count', width: 56 },
    {
      title: '状态',
      dataIndex: 'audit_status',
      width: 92,
      render: (v: AssetSummary['audit_status']) => <AuditStatusTag status={v} />,
    },
    {
      title: '已开单',
      dataIndex: 'production_count',
      width: 68,
      render: (v?: number) =>
        v ? (
          <Tooltip title="这条文案之前开过几张生产单（重复开＝重复占当天号池额度）">
            <Tag color="orange">{v}</Tag>
          </Tooltip>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            0
          </Text>
        ),
    },
    {
      /**
       * 批 N（11-09）：这条文案名下**预取好、还没用掉**的钩子编号。
       * 挑文案的人最想知道的就是"这条还要不要现去取号"——有这列就不用猜，
       * 开单时后端会自动把它顶到缺号槽位（顶掉即清）。
       */
      title: '备号',
      dataIndex: 'hook_code',
      width: 84,
      render: (v?: string | null) =>
        v ? (
          <Tooltip title="已提前取好放在这条文案名下：开单时自动顶到缺号的槽位上，用掉就清（一钩一号）。已投出去的编号在 ④ 生产单行上。">
            <Tag color="purple">
              <MonoText>{v}</MonoText>
            </Tag>
          </Tooltip>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            —
          </Text>
        ),
    },
    {
      title: '过审时间',
      dataIndex: 'reviewed_at',
      width: 96,
      render: (v: string | null) => (v ? parseServerTime(v)?.format('MM-DD HH:mm') : '—'),
    },
  ];

  return (
    <Modal
      open={open}
      title={title}
      width={820}
      onCancel={onCancel}
      footer={
        <Space>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" disabled={!sel.length} onClick={() => onConfirm(sel)}>
            去生成生产单（{sel.length}）
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        {!byAssets && !!batchOptions?.length && (
          <Space wrap size={8}>
            {/* 批 N（评审二·P1-2）：按批次筛——量大时找文案不能靠翻相册 */}
            <Select
              style={{ width: 280 }}
              placeholder="按批次筛选（可选）"
              allowClear
              showSearch
              optionFilterProp="label"
              value={batch}
              onChange={setBatch}
              loading={loading}
              options={batchOptions}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              共 {total} 条过审文案
            </Text>
          </Space>
        )}
        {loading && <Spin size="small" />}
        {!loading && !rows.length && (
          <Alert
            type="warning"
            showIcon
            message={
              byAssets
                ? `勾的 ${assets!.length} 条素材名下没有「已过审 / 改后通过」的文案`
                : '这个范围里没有「已过审 / 改后通过」的文案'
            }
            description={
              <span style={{ fontSize: 12 }}>
                {byAssets
                  ? '没出过文案就回上一排点「出钩子文案」；出了文案还没审，去「文案审核」页签过审。'
                  : '去「文案审核」页签过审，或回「素材与文案」勾素材点「出钩子文案」。'}
                只有过审的文案能开生产单——这道在后端也拦着，绕不过去。
              </span>
            }
          />
        )}
        {!loading && byAssets && !!missingCodes.length && !!rows.length && (
          <Alert
            type="info"
            showIcon
            message={`${missingCodes.length} 条素材没过审文案，已排在外面`}
            description={
              <span style={{ fontSize: 12 }}>
                {missingCodes.slice(0, 12).join('、')}
                {missingCodes.length > 12 ? `…等 ${missingCodes.length} 条` : ''}
              </span>
            }
          />
        )}
        {truncated && (
          <Alert
            type="warning"
            showIcon
            message={`过审文案多于 ${PAGE_SIZE} 条，这里只列了一部分`}
            description={
              <span style={{ fontSize: 12 }}>
                下面列的是最近的 {rows.length} 条（共 {total} 条）。
                {byAssets
                  ? '少勾几条素材分批开单，或去「生产与投板」页签按批次开单。'
                  : '用上面的批次筛选缩小范围。'}
              </span>
            }
          />
        )}
        {!!rows.length && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            一条文案＝一组生产单。「已开单」是这条之前开过几张，防止同一版重复投。
          </Text>
        )}
        <Table<AssetSummary>
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={rows}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          rowSelection={{
            selectedRowKeys: sel.map((s) => s.id),
            // 换批次/换范围时 sel 已清空，这里只认当前列表里的行
            onChange: (_, picked) => setSel(picked),
          }}
          columns={columns}
        />
      </Space>
    </Modal>
  );
};

export default ApprovedSummaryPickerModal;
