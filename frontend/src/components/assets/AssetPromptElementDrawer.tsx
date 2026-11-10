import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button, Drawer, Input, Modal, Select, Space, Switch, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import { PlusOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetPromptElementSlot, AssetPromptElementsConfig } from '../../api/assets';
import { HelpDot } from './AssetBits';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

/** 界面上一行就是后端字典的一行；anchors/pool/categories 用「、」或换行分隔的文本编辑。 */
interface SlotRow {
  key: string;
  label: string;
  /** 批 N 起三种：词面／正则／手填（系统不猜原句，整句由人抄） */
  mode: 'literal' | 'pattern' | 'manual';
  anchors: string;
  pattern: string;
  /** 批 N：只用来认位置的写法（场景这类「词面全文换、但要先认出当前值」的槽位） */
  probe: string;
  pool: string;
  categories: string;
  note: string;
  /**
   * 保护行三态。后端判的是**键在不在**：不传＝用默认那串（护住「钩子原文」行和 ① 剧名行），
   * 传空串＝这一行允许碰那两行，传别的＝自定义手法。所以这里必须留三态，
   * 不能统一成一个字符串——一律发字符串会把「用默认」和「不保护」混成同一次保存。
   */
  skip: SkipMode;
  /** 仅 skip='custom' 时用的写法 */
  skipPattern: string;
}

type SkipMode = 'default' | 'custom' | 'none';

/** 后端 DEFAULT_SKIP_LINES 的兜底显示串（真值优先取接口回的 default_skip_lines） */
const FALLBACK_DEFAULT_SKIP = '^(钩子原文|生成【)';

const splitList = (raw: string): string[] =>
  raw
    .split(/[\n,，、;；]+/)
    .map((s) => s.trim())
    .filter(Boolean);

const joinList = (arr: string[]): string => arr.join('、');

const toRow = (s: AssetPromptElementSlot, defaultSkip: string): SlotRow => {
  // 读回来的行后端都已清洗成具体串（出厂那几行的 skip_lines 键根本不存在，吐回来是默认串），
  // 所以这里按「等于默认串＝仍用默认」还原三态，别让一线以为有人手写过保护行。
  const skipRaw = s.skip_lines;
  let skip: SkipMode = 'default';
  if (skipRaw === '') skip = 'none';
  else if (skipRaw && skipRaw !== defaultSkip) skip = 'custom';
  return {
    key: s.key,
    label: s.label,
    mode: s.mode,
    anchors: joinList(s.anchors || []),
    pattern: s.pattern || '',
    probe: s.probe || '',
    pool: joinList(s.pool || []),
    categories: joinList(s.categories || []),
    note: s.note || '',
    skip,
    skipPattern: skip === 'custom' ? skipRaw || '' : '',
  };
};

const toSlot = (r: SlotRow): AssetPromptElementSlot => ({
  key: r.key.trim(),
  label: r.label.trim() || r.key.trim(),
  mode: r.mode,
  // 后端对 manual 行会清掉词面/正则、对 pattern 行会清掉识别位置：界面跟着 disable，
  // 但**照原样发过去**也没关系（存进去生效的是清洗后的），少一处分叉口径。
  anchors: splitList(r.anchors),
  pattern: r.pattern.trim(),
  probe: r.probe.trim(),
  pool: splitList(r.pool),
  categories: splitList(r.categories),
  note: r.note.trim(),
  skip_lines: r.skip === 'default' ? undefined : r.skip === 'none' ? '' : r.skipPattern.trim(),
});

const blankRow = (): SlotRow => ({
  key: '',
  label: '',
  mode: 'literal',
  anchors: '',
  pattern: '',
  probe: '',
  pool: '',
  categories: '',
  note: '',
  skip: 'default',
  skipPattern: '',
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
 *            **每一处**这个词面都换掉（长词面先换，重叠命中不重复计数）。可另配 probe：
 *            一条**只用来认位置**的写法（如「剧情：」后第一段），认到的当当前值，替换仍按
 *            词面全局走——所以 ⑧ 镜头行那句跟着换。
 *   pattern  带捕获组的正则（模板保证存在的那个位置，如「生成【…】」里那一段）；替换**只动捕获组**，
 *            所以时长这种「②⑦⑩⑬ 四处必须一致」的数字绝不会被顺手改掉。
 *            注：出厂表现在**没有**这一行（11-10 按用户口径严格按 docx 删了题材标签／剧名两行），
 *            这条写法留着给管理员自定义槽位用。
 *   manual   系统不猜原句（动物说的话／偷听到的内容／引爆不公那句是间接转述，没有形状可依赖，
 *            硬编正则＝假认）：这一行永远摆出来，让人从稿子里复制。
 *   categories 留空＝所有原型都认；填了＝只在这些钩子原型名下出现（原型名或键都行）。
 *
 * 保护行（skip_lines）默认护住「钩子原文：」行与 ① 生成【…】行：前者是过审的那句话，动它
 * 投产复核判漂移；后者里面写着《剧名》，全文替换动物会把剧名一起换掉，凭空造出一部不存在的剧。
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
  /**
   * 上一次「读回来的样子」，只用来判脏（点遮罩／Esc 时问一句要不要丢改动）。
   * 比 `rows`/`inherit` 的序列化串，不比对后端，所以字段顺序变了也不会误判成脏。
   */
  const [baseline, setBaseline] = useState('');

  /** 默认保护行的原串：优先用接口回的，后端没回才用兜底 */
  const defaultSkip = data?.default_skip_lines || FALLBACK_DEFAULT_SKIP;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await assetApi.getPromptElements();
      const skipDefault = res.default_skip_lines || FALLBACK_DEFAULT_SKIP;
      const nextRows = res.override.map((s) => toRow(s, skipDefault));
      setData(res);
      setInherit(res.inherit);
      setRows(nextRows);
      setBaseline(JSON.stringify({ inherit: res.inherit, rows: nextRows }));
    } catch (e) {
      message.error((e as Error).message || '读取元素字典失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const patch = <K extends keyof SlotRow>(key: string, field: K, value: SlotRow[K]) =>
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
      // 切到「整体替换」前把当前生效表搬进编辑区，否则一存就把出厂那 A–F 参数项丢掉。
      setRows(preview.map((s) => toRow(s, defaultSkip)));
    }
    setInherit(checked);
  };

  const restoreDefaults = () => {
    if (!data) return;
    setInherit(true);
    setRows(data.defaults.map((s) => toRow(s, defaultSkip)));
    message.info(`已填回出厂 ${data.defaults.length} 行，保存后生效`);
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

  /**
   * 11-10 用户口径「不要点到旁边它就消失掉了，很容易误点」：抽屉的 Esc／关闭按钮同样走这里，
   * 改了还没保存先问一句——这份字典是整排元素行的来源，填半屏被点掉最气人。
   */
  const dirty = canEdit && JSON.stringify({ inherit, rows }) !== baseline;
  const requestClose = () => {
    if (!dirty) {
      onClose();
      return;
    }
    Modal.confirm({
      title: '这份字典改动还没保存',
      content: '现在关掉，改动不会生效（下一次打开还是上次存的版本）。',
      okText: '继续留着改',
      cancelText: '不保存关掉',
      okCancel: true,
      onOk: () => undefined,
      onCancel: onClose,
    });
  };

  return (
    <Drawer
      title="可替换元素库"
      width="min(1280px, 96vw)"
      open={open}
      onClose={requestClose}
      maskClosable={false}
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
      {/* 11-10 用户口径「说明文字太长篇大论，全部缩起来放浮窗里，不然界面看起来很乱」：
          这一屏原本被六段说明吃掉半个抽屉，现在收进标题旁那枚「？」，指上去才展开。 */}
      <Space wrap size={6} style={{ marginBottom: 12 }}>
        <Text strong>这里每一行＝投产弹窗「改稿」里的一排元素</Text>
        <HelpDot
          text={
            <div>
              <Paragraph style={{ marginBottom: 4 }}>
                <Tag color="blue">词面（literal）</Tag>
                在正文里<strong>逐字</strong>找 <Monoish>{'anchors'}</Monoish> 给的词，找到几处换几处。
                场景、动物这种写在剧情描述里的东西走这条。要它「先认出当前值」就再配一条识别位置
                <Monoish>{'probe'}</Monoish>（比如「剧情：」后第一段），认到的当原值、替换仍按词面全局走。
              </Paragraph>
              <Paragraph style={{ marginBottom: 4 }}>
                <Tag color="purple">正则（pattern）</Tag>
                带<strong>捕获组</strong>的写法，只换捕获组那一小段——时长这种「②⑦⑩⑬ 四处必须一致」的
                数字只能用这条，不能全局换。出厂表现在没有这一行（11-10 按用户口径严格按参考文档删了
                题材标签／剧名两行），这条写法留着给自定义槽位用。
              </Paragraph>
              <Paragraph style={{ marginBottom: 4 }}>
                <Tag color="orange">手填（manual）</Tag>
                系统<strong>不猜原句</strong>：动物说的那句话、偷听到的内容、引爆不公那句是间接转述，
                没有形状可靠，硬编正则＝假装认得出。这一行永远摆出来，界面上提示「请从稿子里复制」。
              </Paragraph>
              <Paragraph style={{ marginBottom: 4 }}>
                <Tag>保护行</Tag>
                默认<strong>不碰</strong>「钩子原文」那行和 ① 生成【…】那行（那里面有《剧名》，
                全文替换动物会顺手造出一部不存在的剧）。除非确实要开口子，别改成「允许碰」。
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
      </Space>

      {!canEdit && (
        <Space wrap size={6} style={{ marginBottom: 12 }}>
          <Text type="warning">只读：改元素库要管理员权限</Text>
          <HelpDot text="这一份决定了一线点「改稿」时能改哪些位置、给哪几个候选。写错一行（比如正则少了捕获组）会让整排元素点了没反应，所以只有管理员能改。你可以照着这一屏看有哪些槽位，要改词找管理员。" />
        </Space>
      )}

      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
        <Space wrap size={6}>
          <Switch checked={inherit} onChange={switchInherit} disabled={!canEdit} />
          <Text>
            在出厂字典上<strong>{inherit ? '追加／同键覆盖' : '整体替换'}</strong>
          </Text>
          <HelpDot
            text={inherit
              ? `开着＝出厂那 ${data?.defaults.length ?? 0} 行仍生效，下面这一表填的是「新增」和「同键改写」，没填的照出厂走。`
              : `关掉＝出厂那 ${data?.defaults.length ?? 0} 行也不再认，下面填什么才认什么（切回来的时候这一表已经搬进编辑区，不会一存就丢出厂那 A–F 参数项）。`}
          />
          <Text type="secondary">
            保存后生效：{preview.length} 个槽位
            {data?.has_override && `｜上次更新：${data.updated_at || '未知'}`}
          </Text>
          {!!data?.defaults.length && (
            <Tooltip
              title={data.defaults.map((s) => `${s.label}（${s.mode}）`).join('、')}
              overlayStyle={{ maxWidth: 520 }}
            >
              <Text type="secondary" style={{ fontSize: 12 }}>
                出厂 {data.defaults.length} 行
              </Text>
            </Tooltip>
          )}
        </Space>
      </Space>

      <Table
        size="small"
        rowKey={(_, i) => String(i)}
        pagination={false}
        dataSource={rows}
        scroll={{ x: 1500 }}
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
                  { value: 'manual', label: '手填' },
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
              <Tooltip title="词面槽位的「识别位置」：一条带捕获组的写法，只用来认出当前值（如「剧情：」后第一段）。替换仍按词面全文走，所以镜头行那句也一起换。留空＝只按词面找。">
                <span>识别位置</span>
              </Tooltip>
            ),
            dataIndex: 'probe',
            width: 200,
            render: (_, r, i) => (
              <Input
                value={r.probe}
                disabled={!canEdit || r.mode !== 'literal'}
                placeholder="剧情：([^，。]{2,20}?里)"
                onChange={(e) => patch(String(i), 'probe', e.target.value)}
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
            title: (
              <Tooltip
                title={
                  <div>
                    「不碰哪几行」：默认护住<strong>钩子原文</strong>那行（过审句，动它投产判漂移）
                    和 ① 生成【…】那行（里面有《剧名》，全文替换动物会造出一部不存在的剧）。
                    <div>默认串：<Monoish>{defaultSkip}</Monoish></div>
                    <div>「允许碰」＝这一行做全文替换时把那两行也换掉，只有确实要时才用。</div>
                  </div>
                }
              >
                <span>保护行</span>
              </Tooltip>
            ),
            dataIndex: 'skip',
            width: 220,
            render: (_, r, i) => (
              <Space size={4} style={{ width: '100%' }}>
                <Select
                  value={r.skip}
                  disabled={!canEdit || r.mode === 'pattern'}
                  style={{ width: 110 }}
                  options={[
                    { value: 'default', label: '用默认' },
                    { value: 'none', label: '允许碰' },
                    { value: 'custom', label: '自定义' },
                  ]}
                  onChange={(v) => patch(String(i), 'skip', v)}
                />
                {r.skip === 'custom' && (
                  <Input
                    value={r.skipPattern}
                    disabled={!canEdit}
                    placeholder="^(钩子原文|①)"
                    onChange={(e) => patch(String(i), 'skipPattern', e.target.value)}
                  />
                )}
              </Space>
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

/** 行内小代码体（说明里那几个字段名用） */
const Monoish: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }}>
    {children}
  </span>
);

export default AssetPromptElementDrawer;
