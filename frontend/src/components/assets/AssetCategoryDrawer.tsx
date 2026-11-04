import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Drawer, Input, InputNumber, Popconfirm, Space, Switch, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import { PlusOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetCategory, AssetCategoryUpsert } from '../../api/assets';
import { invalidateAssetCategories, splitCategoryName } from './AssetCategoryBits';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

/** 草稿行：带 id＝改既有行，不带 id＝新增。`_key` 只当 rowKey 用。 */
interface DraftRow extends AssetCategoryUpsert {
  _key: string;
  active: boolean;
  asset_count?: number;
  copy_count?: number;
}

let newSeq = 0;
const nextKey = () => `n-${Date.now()}-${(newSeq += 1)}`;

const toDraft = (c: AssetCategory): DraftRow => ({
  _key: c.id,
  id: c.id,
  name: c.name,
  sort: c.sort,
  active: c.active,
  note: c.note,
  asset_count: c.asset_count,
  copy_count: c.copy_count,
});

const usedOf = (r: DraftRow) => (r.asset_count || 0) + (r.copy_count || 0);

/**
 * 钩子原型字典抽屉（11-04 拍板①）。
 *
 * 形态与「违禁词表」抽屉一致：读全员、写仅 admin，保存即生效、改动进审计。
 * 初始 7 行 A–G 的名称照《钩子模版换皮参数设定.docx》原名，别在这里润色；
 * 原型＝结构层，和 style_tag（句式）、formula_tag（文字）是三条独立的轴。
 *
 * 保存是**整单语义**（后端 CategoriesUpdateRequest）：这次没列出来的既有行＝下线。
 * 后端不硬删——素材/文案上的引用是真数据，删行会把一线点好的分类静默清空，
 * 所以「去掉一行」在 UI 上写成「下线」，并当场报这条挂着多少引用。
 *
 * note（钩法内核，含原型 D 的合规提醒）纯展示、不参与任何判定：按拍板拦人的
 * 仍然只有违禁词和字数。
 */
const AssetCategoryDrawer: React.FC<Props> = ({ open, onClose }) => {
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [canEdit, setCanEdit] = useState(false);
  const [unclassified, setUnclassified] = useState({ asset_count: 0, copy_count: 0 });
  const [note, setNote] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 打开抽屉要拿最新的：别的 admin 刚改过字典时，缓存会让人基于旧字典提交
      const res = await assetApi.listCategories();
      setRows(res.items.map(toDraft));
      setCanEdit(res.can_edit);
      setUnclassified(res.unclassified);
      setNote(res.note || '');
    } catch (e) {
      message.error((e as Error).message || '读取原型字典失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const patch = (key: string, changes: Partial<DraftRow>) =>
    setRows((prev) => prev.map((r) => (r._key === key ? { ...r, ...changes } : r)));

  const drop = (key: string) => setRows((prev) => prev.filter((r) => r._key !== key));

  /** 表里仍在用、却没被列进本次提交的行数——整单语义下这些会被下线，必须提醒 */
  const retiredByOmit = useMemo(() => rows.filter((r) => r.id && r.active && usedOf(r) > 0).length, [rows]);

  const save = async () => {
    if (!rows.length) {
      message.warning('字典不能提交空表——一条原型都不留等于把所有人的分类都下线');
      return;
    }
    if (rows.some((r) => !(r.name || '').trim())) {
      message.warning('原型名称不能为空');
      return;
    }
    const seen = new Set<string>();
    for (const r of rows) {
      const nm = (r.name || '').trim();
      if (seen.has(nm)) {
        message.warning(`字典里有重名的原型：${nm}（同名会撞唯一约束，请先去掉一个）`);
        return;
      }
      seen.add(nm);
    }
    setSaving(true);
    try {
      const res = await assetApi.updateCategories({
        items: rows.map((r) => ({
          id: r.id ?? null,
          name: (r.name || '').trim(),
          sort: r.sort == null ? null : Number(r.sort),
          active: r.active,
          note: (r.note || '').trim() || null,
        })),
      });
      setRows(res.items.map(toDraft));
      (res.notes || []).forEach((n) => message.info(n));
      message.success(`原型字典已保存：新增 ${res.added} 条、改 ${res.updated} 条、下线 ${res.retired} 条`);
      invalidateAssetCategories();
    } catch (e) {
      message.error((e as Error).message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    {
      title: '原型（docx 原名）',
      dataIndex: 'name',
      render: (_: unknown, r: DraftRow) => (
        <Space direction="vertical" size={0} style={{ width: '100%' }}>
          <Input
            value={r.name}
            disabled={!canEdit}
            placeholder="例如：原型 A：非人物件 / 动物开口说话（报恩·预警·神谕）"
            onChange={(e) => patch(r._key, { name: e.target.value })}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.id
              ? splitCategoryName(r.name || '').topic || '（原名里没有冒号后的主题串）'
              : '新增行：保存后才有 id'}
          </Text>
        </Space>
      ),
    },
    {
      title: '行内说明',
      dataIndex: 'note',
      width: 200,
      render: (_: unknown, r: DraftRow) => (
        <Input.TextArea
          rows={2}
          value={r.note || ''}
          disabled={!canEdit}
          placeholder="钩法内核／口径提醒（只展示，不拦人）"
          onChange={(e) => patch(r._key, { note: e.target.value })}
        />
      ),
    },
    {
      title: (
        <Tooltip title="小的排在前面；留空＝保存时排到最后。">
          <span>顺序</span>
        </Tooltip>
      ),
      dataIndex: 'sort',
      width: 74,
      render: (_: unknown, r: DraftRow) => (
        <InputNumber
          size="small"
          style={{ width: 62 }}
          value={r.sort == null ? undefined : Number(r.sort)}
          disabled={!canEdit}
          onChange={(v) => patch(r._key, { sort: v == null ? null : Number(v) })}
        />
      ),
    },
    {
      title: '在用',
      dataIndex: 'active',
      width: 66,
      render: (_: unknown, r: DraftRow) => (
        <Switch size="small" checked={r.active} disabled={!canEdit} onChange={(v) => patch(r._key, { active: v })} />
      ),
    },
    {
      title: (
        <Tooltip title="挂着多少条素材／多少条文案。下线不删数据：这些条目仍显示旧原型、仍筛得出来，只是不能再挂新条目。">
          <span>引用</span>
        </Tooltip>
      ),
      key: 'usage',
      width: 106,
      render: (_: unknown, r: DraftRow) =>
        r.id ? (
          <Space size={2}>
            <Tag>{r.asset_count ?? 0} 素材</Tag>
            <Tag>{r.copy_count ?? 0} 文案</Tag>
          </Space>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            -
          </Text>
        ),
    },
    {
      title: '',
      key: 'op',
      width: 92,
      render: (_: unknown, r: DraftRow) => {
        if (!canEdit) return null;
        if (!r.id) {
          return (
            <Button size="small" onClick={() => drop(r._key)}>
              撤销新增
            </Button>
          );
        }
        const used = usedOf(r);
        return (
          <Popconfirm
            title="下线这一行？"
            description={
              <div style={{ maxWidth: 300 }}>
                后端不删行，只标成「已下线」：
                {used > 0
                  ? `这条上挂着 ${r.asset_count ?? 0} 条素材、${r.copy_count ?? 0} 条文案，它们仍显示旧原型，但不能再挂新条目。`
                  : '这条目前没有引用。'}
              </div>
            }
            okText="下线"
            cancelText="先不动"
            onConfirm={() => patch(r._key, { active: false })}
          >
            <Button size="small" danger disabled={!r.active}>
              下线
            </Button>
          </Popconfirm>
        );
      },
    },
  ];

  return (
    <Drawer
      title="钩子原型字典"
      width={880}
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            重新读取
          </Button>
          {canEdit && (
            <Button type="primary" icon={<SaveOutlined />} onClick={save} loading={saving}>
              保存整张字典
            </Button>
          )}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="原型＝结构层（A–G），和句式标签、公式标签是三回事"
        description={
          <div>
            <Paragraph style={{ marginBottom: 4 }}>
              名称照《钩子模版换皮参数设定.docx》原名。列表里显示成「原型 A」只是截短展示，数据仍是整串原名，别改成一个字母。
            </Paragraph>
            <Paragraph style={{ marginBottom: 4 }}>
              分类是<strong>人工点的，也可以不点</strong>（未分类照常走完全链）。当前未分类：素材{' '}
              <strong>{unclassified.asset_count}</strong> 条、文案 <strong>{unclassified.copy_count}</strong> 条。
            </Paragraph>
            <Text type="secondary">
              行内说明（含原型 D 的合规提醒）只是给你看的口径提示，<strong>不参与过审/投产判定</strong>——
              拦人的仍然只有违禁词和字数。
            </Text>
          </div>
        }
      />

      {!canEdit && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="只读：改原型字典要管理员权限"
          description="字典一改，全站的筛选和已挂分类的展示都跟着变，所以只有管理员能保存。这里能看到每条原型挂着多少素材和文案。"
        />
      )}

      {canEdit && retiredByOmit > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={`表里有 ${retiredByOmit} 条在用原型带着引用`}
          description="保存是整单提交：没列进本次提交的既有行会被标成「已下线」（不删数据）。要保留就把它留在表里。"
        />
      )}

      <Table<DraftRow>
        rowKey="_key"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 840 }}
      />

      {canEdit && (
        <Space style={{ marginTop: 12 }} wrap>
          <Button
            icon={<PlusOutlined />}
            onClick={() =>
              setRows((prev) => [...prev, { _key: nextKey(), name: '', active: true, note: null, sort: null }])
            }
          >
            加一条原型
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            新增行没填顺序就排到最后；顺序只影响下拉里的排列，不影响已挂的分类。
          </Text>
        </Space>
      )}

      {note && (
        <Text type="secondary" style={{ display: 'block', marginTop: 12, fontSize: 12 }}>
          {note}
        </Text>
      )}
    </Drawer>
  );
};

export default AssetCategoryDrawer;
