import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Drawer, Input, Select, Space, Switch, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import { PlusOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetPromptElementSlot, AssetPromptElementsConfig } from '../../api/assets';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

/** 界面上一行就是后端字典的一行；anchors/pool/categories 用「、」或换行分隔的文本编辑。 */
interface SlotRow {
  key: string;
  label: string;
  mode: 'literal' | 'pattern';
  anchors: string;
  pattern: string;
  pool: string;
  categories: string;
  note: string;
}

const splitList = (raw: string): string[] =>
  raw
    .split(/[\n,，、;；]+/)
    .map((s) => s.trim())
    .filter(Boolean);

const joinList = (arr: string[]): string => arr.join('、');

const toRow = (s: AssetPromptElementSlot): SlotRow => ({
  key: s.key,
  label: s.label,
  mode: s.mode,
  anchors: joinList(s.anchors || []),
  pattern: s.pattern || '',
  pool: joinList(s.pool || []),
  categories: joinList(s.categories || []),
  note: s.note || '',
});

const toSlot = (r: SlotRow): AssetPromptElementSlot => ({
  key: r.key.trim(),
  label: r.label.trim() || r.key.trim(),
  mode: r.mode,
  anchors: splitList(r.anchors),
  pattern: r.pattern.trim(),
  pool: splitList(r.pool),
  categories: splitList(r.categories),
  note: r.note.trim(),
});

const blankRow = (): SlotRow => ({
  key: '', label: '', mode: 'literal', anchors: '', pattern: '', pool: '', categories: '', note: '',
});

/**
 * 可替换元素库抽屉（批 M）。
 *
 * 这里配的每一行，就是投产弹窗里「改稿」上方那一排元素行的来源：
 * 投放人员点「改稿」时，后端拿这份字典在那条投递稿正文里认元素，认出来的每个元素
 * 给几个候选（＝pool，也就是「裂变」出来的几个选择）＋一个自定义输入框。
 *
 * 三种写法要分清：
 *   literal  词面逐字找（场景、动物这类写在③剧情自由文本里的东西）；替换＝把正文里
 *            **每一处**这个词面都换掉（长词面先换，重叠命中不重复计数）。
 *   pattern  带捕获组的正则（①题材标签、剧名这种模板保证存在的位置）；替换**只动捕获组**，
 *            所以时长这种「②⑦⑩⑬ 四处必须一致」的数字绝不会被顺手改掉。
 *   categories 留空＝所有原型都认；填了＝只在这些钩子原型名下出现（原型名或键都行）。
 *
 * 权限跟风险词库完全一套：读全员、写仅 admin——这份字典决定的是「投出去的那份稿子能被改成
 * 什么样」，写错一行（比如正则没捕获组）会让一线点了没反应。存进 system_config，**改完立即生效，不用发版**。
 */
const AssetPromptElementDrawer: React.FC<Props> = ({ open, onClose }) => {
  const [data, setData] = useState<AssetPromptElementsConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [inherit, setInherit] = useState(true);
  const [rows, setRows] = useState<SlotRow[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await assetApi.getPromptElements();
      setData(res);
      setInherit(res.inherit);
      setRows(res.override.map(toRow));
    } catch (e) {
      message.error((e as Error).message || '读取元素字典失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const patch = (key: string, field: keyof SlotRow, value: string) =>
    setRows((prev) => prev.map((r, i) => (i === Number(key) ? { ...r, [field]: value } : r)));

  const preview = useMemo(() => {
    const mine = rows.map(toSlot).filter((s) => s.key);
    if (!data) return mine;
    if (!inherit) return mine;
    const byKey = new Map(data.defaults.map((s) => [s.key, s]));
    mine.forEach((s) => byKey.set(s.key, s));
    return Array.from(byKey.values());
  }, [rows, inherit, data]);

  const switchInherit = (checked: boolean) => {
    if (!checked && data) {
      // 切到「整体替换」前把当前生效表搬进编辑区，否则一存就把出厂那两行（题材/剧名）丢掉。
      setRows(preview.map(toRow));
    }
    setInherit(checked);
  };

  const restoreDefaults = () => {
    if (!data) return;
    setInherit(true);
    setRows(data.defaults.map(toRow));
    message.info('已填回出厂两行，保存后生效');
  };

  const save = async () => {
    setSaving(true);
    try {
      const res = await assetApi.updatePromptElements({ slots: rows.map(toSlot), inherit });
      (res.notes || []).forEach((n) => message.info(n));
      message.success('元素字典已保存，下一次打开「改稿」立即按这份认');
      await load();
    } catch (e) {
      message.error((e as Error).message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const canEdit = !!data?.can_edit;

  return (
    <Drawer
      title="可替换元素库"
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
              保存
            </Button>
          )}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="这里每一行＝投产弹窗「改稿」里的一排元素"
        description={
          <div>
            <Paragraph style={{ marginBottom: 4 }}>
              <Tag color="blue">词面（literal）</Tag>
              在正文里<strong>逐字</strong>找 <Monoish>{'anchors'}</Monoish> 给的词，找到几处换几处。
              场景、动物这种写在剧情描述里的东西走这条。
            </Paragraph>
            <Paragraph style={{ marginBottom: 4 }}>
              <Tag color="purple">正则（pattern）</Tag>
              带<strong>捕获组</strong>的写法，只换捕获组那一小段。①的题材标签、剧名走这条；
              时长在②⑦⑩⑬ 四处必须一致，所以那种数字只能用这条、不能全局换。
            </Paragraph>
            <Paragraph style={{ marginBottom: 4 }}>
              <Tag color="green">候选池（裂变）</Tag>
              这里写几个，界面上就给几个选择（顺序＝推荐顺序）。
              <strong>留空也不断档</strong>：界面上还能自己输入。
            </Paragraph>
            <Paragraph style={{ marginBottom: 4 }}>
              <Tag>适用原型</Tag>
              留空＝所有钩子原型都认这一行；填原型名（如「悬念」）＝只在那一类下出现。
            </Paragraph>
            <Text type="secondary">
              存进系统配置，改完立即生效、不用发版；只改这一次投出去的正文，库里的提示词永不动。
            </Text>
          </div>
        }
      />

      {!canEdit && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="只读：改元素库要管理员权限"
          description="这一份决定了一线点「改稿」时能改哪些位置、给哪几个候选。写错一行（比如正则少了捕获组）会让整排元素点了没反应，所以只有管理员能改。"
        />
      )}

      <Space direction="vertical" size={10} style={{ width: '100%', marginBottom: 12 }}>
        <Space wrap>
          <Switch checked={inherit} onChange={switchInherit} disabled={!canEdit} />
          <Text>
            在出厂字典上<strong>{inherit ? '追加／同键覆盖' : '整体替换'}</strong>
            {inherit
              ? '（出厂那两行仍生效，这里填的是新增和改写）'
              : '（出厂那两行也不再认，这里填什么才认什么）'}
          </Text>
        </Space>
        <Text type="secondary">
          保存后生效：{preview.length} 个元素槽位
          {data?.has_override && `｜上次更新：${data.updated_at || '未知'}`}
        </Text>
        {data && (
          <Text type="secondary">
            出厂字典：{data.defaults.map((s) => `${s.label}（${s.mode}）`).join('、') || '（空）'}
          </Text>
        )}
      </Space>

      <Table
        size="small"
        rowKey={(_, i) => String(i)}
        pagination={false}
        dataSource={rows}
        scroll={{ x: 900 }}
        columns={[
          {
            title: '键',
            dataIndex: 'key',
            width: 120,
            render: (_, r, i) => (
              <Input
                value={r.key}
                disabled={!canEdit}
                placeholder="scene"
                onChange={(e) => patch(String(i), 'key', e.target.value)}
              />
            ),
          },
          {
            title: '显示名',
            dataIndex: 'label',
            width: 120,
            render: (_, r, i) => (
              <Input
                value={r.label}
                disabled={!canEdit}
                placeholder="场景"
                onChange={(e) => patch(String(i), 'label', e.target.value)}
              />
            ),
          },
          {
            title: '认法',
            dataIndex: 'mode',
            width: 110,
            render: (_, r, i) => (
              <Select
                value={r.mode}
                disabled={!canEdit}
                style={{ width: '100%' }}
                options={[
                  { value: 'literal', label: '词面' },
                  { value: 'pattern', label: '正则' },
                ]}
                onChange={(v) => patch(String(i), 'mode', v)}
              />
            ),
          },
          {
            title: (
              <Tooltip title="词面认法要匹配的词，顿号分隔；留空＝拿候选池当词面">
                <span>词面</span>
              </Tooltip>
            ),
            dataIndex: 'anchors',
            width: 180,
            render: (_, r, i) => (
              <Input
                value={r.anchors}
                disabled={!canEdit || r.mode !== 'literal'}
                placeholder="老破小客厅、出租屋"
                onChange={(e) => patch(String(i), 'anchors', e.target.value)}
              />
            ),
          },
          {
            title: (
              <Tooltip title="正则认法的写法，必须带一个捕获组（那一段才是要换的位置）">
                <span>正则写法</span>
              </Tooltip>
            ),
            dataIndex: 'pattern',
            width: 200,
            render: (_, r, i) => (
              <Input
                value={r.pattern}
                disabled={!canEdit || r.mode !== 'pattern'}
                placeholder="生成【([^】]{1,12})】"
                onChange={(e) => patch(String(i), 'pattern', e.target.value)}
              />
            ),
          },
          {
            title: (
              <Tooltip title="裂变出来的几个候选，顿号分隔＝界面上的推荐顺序；留空＝只能自定义输入">
                <span>候选池</span>
              </Tooltip>
            ),
            dataIndex: 'pool',
            width: 220,
            render: (_, r, i) => (
              <Input
                value={r.pool}
                disabled={!canEdit}
                placeholder="阳台、楼道口、天台"
                onChange={(e) => patch(String(i), 'pool', e.target.value)}
              />
            ),
          },
          {
            title: '适用原型',
            dataIndex: 'categories',
            width: 140,
            render: (_, r, i) => (
              <Input
                value={r.categories}
                disabled={!canEdit}
                placeholder="留空＝全部"
                onChange={(e) => patch(String(i), 'categories', e.target.value)}
              />
            ),
          },
          {
            title: '说明',
            dataIndex: 'note',
            width: 180,
            render: (_, r, i) => (
              <Input
                value={r.note}
                disabled={!canEdit}
                placeholder="给一线看的这行是换什么的"
                onChange={(e) => patch(String(i), 'note', e.target.value)}
              />
            ),
          },
          ...(canEdit
            ? [
                {
                  title: '',
                  width: 60,
                  render: (_: unknown, __: SlotRow, i: number) => (
                    <Button
                      size="small"
                      danger
                      onClick={() => setRows((prev) => prev.filter((_, x) => x !== i))}
                    >
                      删
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />

      {canEdit && (
        <Space style={{ marginTop: 12 }}>
          <Button icon={<PlusOutlined />} onClick={() => setRows((prev) => [...prev, blankRow()])}>
            加一个元素
          </Button>
          <Button onClick={restoreDefaults}>恢复出厂</Button>
        </Space>
      )}
    </Drawer>
  );
};

/** 行内小代码体（Alert 文案里那三个字段名用） */
const Monoish: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }}>
    {children}
  </span>
);

export default AssetPromptElementDrawer;
