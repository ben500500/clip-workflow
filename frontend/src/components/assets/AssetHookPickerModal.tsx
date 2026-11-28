import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Modal, Space, Spin, Table, Tag, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { assetApi, type AssetOutput } from '../../api/assets';
import { durationText } from '../assets/AssetBits';

const { Text } = Typography;

/**
 * 「从成片墙选」钩子挑选弹窗（2026-11-28，接力包 1128-asset-output-compose §9B）。
 *
 * 一句话：成片墙的豆包成片 → 勾选（1～10 条，多选保序）→ 后端同桶复制进 `hook/`
 * （`assetApi.outputsAsHook`）→ 返回的 key 直接并进切片详情的 `hookVideoKeys`。
 * 加入后就是普通钩子：混搭模式、片头片尾、生成数量全部照旧生效。
 *
 * 两条必须写在界面上的事实（设计 §2.1 读码核实）：
 * - 钩子在切片时按成品档位重转后**整段拼入，不截短**——勾了 >10s 的成片当钩子，
 *   成品就是「10s 预滚 + 正片」，所以给一行橙色提示，不静默；
 * - 同一支成片已在钩子里（按返回 key 的原名对不上，按 output id 对）→ 行置灰，不加第二次。
 */
const AssetHookPickerModal: React.FC<{
  open: boolean;
  /** 已在钩子里的成片 id（防重复加） */
  existingOutputIds: string[];
  /** 加入成功：交回可直接塞进 hookVideoKeys 的 key/名字＋来源 output_id（父层记防重） */
  onAdd: (items: { key: string; name: string; output_id: string }[]) => void;
  onClose: () => void;
}> = ({ open, existingOutputIds, onAdd, onClose }) => {
  const [rows, setRows] = useState<AssetOutput[]>([]);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      const data = await assetApi.listOutputs({ limit: 300 });
      // 交付包/文案文件不是视频；没有 file_key 的拼不了也复制不了
      setRows((data.items || []).filter((o) => o.kind !== 'package' && o.kind !== 'copy' && !!o.file_key));
    } catch (e) {
      message.error((e as Error).message || '成片列表读取失败');
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (open) {
      setPicked([]);
      void fetchRows();
    }
  }, [open, fetchRows]);

  const existing = new Set(existingOutputIds);
  const pickedRows = picked.map((id) => rows.find((r) => r.id === id)).filter((r): r is AssetOutput => !!r);
  const tooLong = pickedRows.some((r) => (r.duration ?? 0) > 10);

  const add = async () => {
    if (!picked.length) return;
    setBusy(true);
    try {
      const res = await assetApi.outputsAsHook(picked);
      onAdd(res.items.map((x) => ({ key: x.file_key, name: x.file_name, output_id: x.output_id })));
      message.success(res.message || '已加入钩子');
    } catch (e) {
      message.error((e as Error).message || '加钩子没成', 8);
    } finally {
      setBusy(false);
    }
  };

  const columns: ColumnsType<AssetOutput> = [
    {
      title: '成片',
      dataIndex: 'file_name',
      ellipsis: true,
      render: (v: string | null, r) => (
        <Space size={6}>
          {r.thumb_url ? (
            <img src={r.thumb_url} alt="" style={{ width: 46, height: 26, objectFit: 'cover', borderRadius: 2 }} />
          ) : (
            <div style={{ width: 46, height: 26, background: '#f0f0f0', borderRadius: 2 }} />
          )}
          <Text style={{ fontSize: 12 }}>{v || r.id.slice(0, 8)}</Text>
        </Space>
      ),
    },
    { title: '时长', dataIndex: 'duration', width: 72, render: (v: number | null) => durationText(v) },
    { title: '画幅', dataIndex: 'resolution', width: 88, render: (v: string | null) => v || '-' },
    {
      title: '钩子号',
      dataIndex: 'hook_code',
      width: 84,
      render: (v: string | null) => (v ? <Tag style={{ marginInlineEnd: 0 }}>{v}</Tag> : <Text type="secondary">—</Text>),
    },
  ];

  return (
    <Modal
      open={open}
      width={720}
      title="从成片墙选钩子：勾选豆包成片，复制一份当钩子"
      onCancel={onClose}
      destroyOnClose
      footer={
        <Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            加入后与手传的钩子混在一起用；复制不移动，原成片不受影响
          </Text>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={busy} disabled={!picked.length} onClick={() => void add()}>
            加入钩子（{picked.length}）
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        {tooLong && (
          <Alert
            type="warning"
            showIcon
            message="勾选里有超过 10 秒的成片——钩子会整段拼在片头，不会自动截短"
            description="要短钩子就去成片墙挑短的，或先确认成品时长变长是可接受的。"
          />
        )}
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 8, size: 'small', showSizeChanger: false }}
          rowSelection={{
            type: 'checkbox',
            selectedRowKeys: picked,
            getCheckboxProps: (r) => ({ disabled: existing.has(r.id) }),
            onChange: (keys) => setPicked(keys.map(String)),
            preserveSelectedRowKeys: true,
          }}
          locale={{ emptyText: loading ? <Spin size="small" /> : '成片墙还没有可当钩子的成片' }}
          scroll={{ y: 320 }}
        />
        {!!existingOutputIds.length && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            灰掉的 {existingOutputIds.length} 条已经在钩子里了，不会重复加。
          </Text>
        )}
      </Space>
    </Modal>
  );
};

export default AssetHookPickerModal;
