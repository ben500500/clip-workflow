import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Button, Collapse, Input, Radio, Select, Space, Spin, Tag, Tooltip, Typography,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetPromptElementFound, AssetSummary } from '../../api/assets';
import { HelpDot } from './AssetBits';

const { Text } = Typography;

/**
 * 这三个数是后端 `asset_prompt_elements.py` 的常量，前端抄一份只为了**提前拦**：
 * 后端真判在 `expand_matrix`（超了 400），但那时候人已经填完一整屏了。
 * 改这里必须同步改后端，别拿前端这份当权威。
 */
const MAX_VALUES_PER_PARAM = 50;
const MAX_VALUE_LEN = 600;
const MAX_MATRIX_ROWS = 100;

/** 一个参数槽位在界面上的样子（字典行 + 各篇稿子里认到的原值） */
interface SlotView {
  key: string;
  label: string;
  mode: 'literal' | 'pattern' | 'manual';
  note: string;
  pool: string[];
  /** summary_id → 这一篇稿子里认到的原值（manual／没认出的篇目不在里面） */
  currents: Record<string, string>;
  /**
   * 11-10 用户口径「把原提示词中对应的内容也放出来，这样可以做一个对比」：
   * 后端给的那个词在稿子里**所在那一行**的原文（截断到 160 字），拿它当"改之前长什么样"。
   * 一批多篇时只留第一篇认到的那句——要逐篇看全文，去 ④ 投板那一步的「改投递稿」。
   */
  context: string;
  /** `context` 来自哪一篇（只有多篇时才显示，免得让人以为是"这批的原文"） */
  contextFrom?: string;
  protected?: boolean;
}

/**
 * 批 O（11-10 用户口径）：开单屏的「换皮参数」区算出来的东西，父组件直接拼进 produce 请求。
 *
 * ⚠️ 键的口径（后端两套，混了就换不上词）：
 *  - `values` / `base` / `baseBySummary` 用**槽位 key**（字典里那个 `a_scene`）；
 *  - 结果页 `element_fanout.params` 用**中文 label**（后端换过一次，别拿它回传）。
 */
export interface ProduceParams {
  /** 每条文案扇出几张（1＝没填任何值，等于不扇出，走今天同一条路径） */
  rows: number;
  values: Record<string, string[]>;
  base: Record<string, string>;
  baseBySummary: Record<string, Record<string, string>>;
  mode: 'zip' | 'product';
  /** 已填的参数（label 给按钮文案用） */
  filled: Array<{ key: string; label: string; count: number }>;
  /** 非空＝现在还不能提交（对不齐／超上限），内容是要亮给一线的白话 */
  blocked: string | null;
}

export const EMPTY_PRODUCE_PARAMS: ProduceParams = {
  rows: 1,
  values: {},
  base: {},
  baseBySummary: {},
  mode: 'zip',
  filled: [],
  blocked: null,
};

/** 与后端 `_clean_words` 同口径：去空、去重、保序（顺序＝按行配对时的行序） */
const cleanList = (raw: string[]): string[] => {
  const out: string[] = [];
  (raw || []).forEach((v) => {
    const w = String(v ?? '').trim().slice(0, MAX_VALUE_LEN);
    if (w && !out.includes(w)) out.push(w);
  });
  return out;
};

interface Props {
  /** 弹窗开着才认参数：字典是 admin 随时在改的，缓存一份会让新加的参数项看不见 */
  active: boolean;
  summaries: AssetSummary[];
  onChange: (p: ProduceParams) => void;
}

/**
 * 批 O（11-10 用户口径）：「生成生产单这一页要按类型摆出需要设定的参数项，并自动提取原脚本中的参数
 * （动物名称、场景关键词、动物说的话…），每个参数可填多个值，一次生成多条钩子视频。」
 *
 * 三件事各自落在哪：
 *  1. **参数项从哪来**＝后端字典（批 N 按《钩子模版换皮参数设定.docx》种的 A–F 各原型行），
 *     本组件只负责按所选文案的原型把它摆出来 + 拿 `extractPromptElements` 从底稿认原值。
 *     前端**不自己拼参数名**：字典是唯一权威，界面自造的词后端换不动。
 *  2. **多值 → 多条**＝批 P 的扇出口（`element_values`/`element_mode`）。这里只算行数、拦对不齐，
 *     真换词在后端展开好的那份正文上做（字面替换，**0 元、不再调模型**）。
 *  3. **底稿可编辑**＝那一段 `Collapse`。改的是**认参数用的底稿**：词面得和稿子里写的一致才换得动，
 *     自动认出的（`current=null`）多半就是这稿的写法和词表不一样，抄原句进来重新认一次即可。
 *     ⚠️ 这里改的字**不会**变成投递稿正文——进板面的正文只有 ④ 投板那一步的「改投递稿」那道口，
 *     界面上把这句说死，不让人以为在这里改了就会投出去。
 */
const AssetProduceParams: React.FC<Props> = ({ active, summaries, onChange }) => {
  const [slots, setSlots] = useState<SlotView[]>([]);
  const [values, setValues] = useState<Record<string, string[]>>({});
  /** 槽位 key → 人手填的公共原值（逐篇没认出、或整句话那种 manual 项，全靠这里） */
  const [baseDraft, setBaseDraft] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<'zip' | 'product'>('zip');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [categoryName, setCategoryName] = useState('');
  /** 底稿：summary_id → 正文（没改过的用 prompt_preview，退一步用文案本身） */
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;
  const summaryIds = summaries.map((s) => s.id).join(',');

  const baseText = (s: AssetSummary) =>
    drafts[s.id] ?? s.prompt_preview ?? s.text ?? '';

  /** 认一次参数：open／换文案／点「重新认参数」时跑 */
  const extract = async () => {
    if (!summaries.length) {
      setSlots([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const texts: Record<string, string> = {};
      summaries.forEach((s) => {
        texts[s.id] = baseText(s);
      });
      // 同批只有一种原型时才限定参数项；混着好几种就不限定（各篇按自己的原型换，
      // 后端 compose_variants 逐条按那条的原型判 categories，界面把该看的都摆出来）
      const cats = Array.from(
        new Set(summaries.map((s) => (s.category_name || '').trim()).filter(Boolean)),
      );
      const res = await assetApi.extractPromptElements({
        texts,
        category: cats.length === 1 ? cats[0] : undefined,
        // 这个屏要的是「这一型**该设**的参数项」，认不出原值的也要摆出来（current=null）
        include_unmatched: true,
      });
      const byKey = new Map<string, SlotView>();
      summaries.forEach((s) => {
        (res.items?.[s.id] || []).forEach((f: AssetPromptElementFound) => {
          let slot = byKey.get(f.key);
          if (!slot) {
            slot = {
              key: f.key,
              label: f.label,
              mode: f.mode,
              note: f.note || '',
              pool: [],
              currents: {},
              context: '',
              protected: f.protected,
            };
            byKey.set(f.key, slot);
          }
          if (f.current) slot.currents[s.id] = f.current;
          // 原句只留**第一篇**认到的那句，并记下是哪篇的稿子（多篇时不注明会让人以为是"这批的原文"）
          if (!slot.context && f.context) {
            slot.context = f.context;
            slot.contextFrom = s.asset_code || s.hook_code || s.id.slice(0, 8);
          }
          (f.pool || []).forEach((p) => {
            if (!slot!.pool.includes(p)) slot!.pool.push(p);
          });
        });
      });
      setSlots(Array.from(byKey.values()));
      setNotes(res.notes || []);
      setCategoryName(res.category || (cats.length === 1 ? cats[0] : ''));
    } catch (e) {
      setError((e as Error).message || '参数项认不出来（不影响照常开单）');
      setSlots([]);
    } finally {
      setLoading(false);
    }
  };

  // 打开／换文案时自动认一次；底稿是本地状态，靠「重新认参数」按钮才再打接口，
  // 否则每敲一个字就发一次请求（正文上千字，一次一屏）。
  useEffect(() => {
    if (!active || !summaries.length) return;
    setValues({});
    setBaseDraft({});
    setDrafts({});
    void extract();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, summaryIds]);

  /** 每篇各认各的原值；没认出的篇目不塞空串（后端把空当「没给」，会落到公共兜底那份） */
  const baseBySummary = useMemo(() => {
    const out: Record<string, Record<string, string>> = {};
    slots.forEach((slot) => {
      Object.entries(slot.currents).forEach(([sid, cur]) => {
        out[sid] = { ...(out[sid] || {}), [slot.key]: cur };
      });
    });
    return out;
  }, [slots]);

  /** 算扇出行数 + 拦下后端一定会 400 的两种填法 */
  const computed = useMemo(() => {
    const filled = slots
      .map((slot) => ({ key: slot.key, label: slot.label, list: cleanList(values[slot.key] || []) }))
      .filter((c) => c.list.length);
    const counts = filled.filter((c) => c.list.length > 1);
    let rows = 1;
    let blocked: string | null = null;
    const tooLong = filled.find((c) => c.list.some((v) => v.length >= MAX_VALUE_LEN));
    const tooMany = filled.find((c) => c.list.length > MAX_VALUES_PER_PARAM);
    if (tooMany) {
      blocked = `「${tooMany.label}」填了 ${tooMany.list.length} 个，一个参数最多 ${MAX_VALUES_PER_PARAM} 个值（后端同样上限），少填几个`;
    } else if (tooLong) {
      blocked = `「${tooLong.label}」有一个值超过 ${MAX_VALUE_LEN} 字，整句话太长会被截断，改短一点`;
    } else if (mode === 'product') {
      rows = filled.reduce((acc, c) => acc * c.list.length, 1) || 1;
      if (rows > MAX_MATRIX_ROWS) {
        blocked = `全组合会扇出 ${rows} 张，超过上限 ${MAX_MATRIX_ROWS} 张：少填几个值，或改用「按行配对」`;
      }
    } else {
      rows = counts.length ? Math.max(...counts.map((c) => c.list.length)) : 1;
      if (new Set(counts.map((c) => c.list.length)).size > 1) {
        blocked =
          '「按行配对」要求填多个值的参数个数一样，现在对不齐：' +
          counts.map((c) => `「${c.label}」${c.list.length} 个`).join('、') +
          '。补齐到一样多（少的那几个重复填一遍），或切「全组合」';
      }
    }
    const valueMap: Record<string, string[]> = {};
    const baseMap: Record<string, string> = {};
    filled.forEach((c) => {
      valueMap[c.key] = c.list;
      const b = (baseDraft[c.key] || '').trim();
      if (b) baseMap[c.key] = b;
    });
    return {
      rows: filled.length ? rows : 1,
      values: valueMap,
      base: baseMap,
      baseBySummary,
      mode,
      filled: filled.map((c) => ({ key: c.key, label: c.label, count: c.list.length })),
      blocked,
    } as ProduceParams;
  }, [slots, values, baseDraft, mode, baseBySummary]);

  // 只在算出来的东西真变了时上报（父组件把 params 放进依赖链，回一个每次都新建的对象会绕回来）
  const sig = JSON.stringify(computed);
  useEffect(() => {
    onChange(computed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  const multiCopy = summaries.length > 1;

  if (!active || !summaries.length) return null;

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <Space wrap size={6}>
        <Text strong>换皮参数（填多个值＝一次出多条）</Text>
        {/* 11-10 用户口径「说明太长篇大论，缩进浮窗」：这段解释从 Tooltip 换成「？」，界面只留标题 */}
        <HelpDot text="参数项来自「可替换元素库」字典（按钩子原型配的行）；原值是这一批稿子里自动认出来的。填多个值＝一次扇多条，换词不花钱。" />
        {!!categoryName && <Tag color="blue">{categoryName}</Tag>}
        {multiCopy && (
          <Tooltip title={`这批选了 ${summaries.length} 条文案，各篇的原值可能不同：后端按每条稿子自己认到的值分别换，认不出的那些才用下面手填的公共原值`}>
            <Tag>{summaries.length} 篇各认各的原值</Tag>
          </Tooltip>
        )}
        <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={extract}>
          重新认参数
        </Button>
      </Space>

      {loading && !slots.length && <Spin size="small" />}
      {error && <Alert type="warning" showIcon message={`参数项认不出来：${error}`} description="不影响照常开单，只是这一屏没有参数行。" />}
      {!loading && !error && !slots.length && (
        <Space wrap size={6}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            这个原型在字典里还没配参数项——不加也能照常开单（走每条文案出 n 份的老路径）
          </Text>
          <HelpDot text="要在这里换皮，先去「可替换元素库」按原型加参数项（管理员），加完回来点「重新认参数」。这一屏只摆当前原型配的那些行，别的原型的行不会混进来。" />
        </Space>
      )}

      {slots.map((slot) => {
        const list = values[slot.key] || [];
        const currents = Object.values(slot.currents);
        const same = currents.length > 0 && currents.every((c) => c === currents[0]);
        const baseVal = baseDraft[slot.key] ?? (currents.length && same ? currents[0] : '');
        return (
          <div key={slot.key}>
            <Space wrap size={6} style={{ marginBottom: 2 }}>
              <Tooltip title={slot.note || undefined}>
                <Text style={{ fontSize: 12 }}>
                  {slot.label}
                  {slot.mode === 'manual' && <Tag style={{ marginLeft: 6 }}>要自己抄原句</Tag>}
                  {slot.mode === 'pattern' && <Tag style={{ marginLeft: 6 }}>按写法认</Tag>}
                </Text>
              </Tooltip>
              {currents.length === 0 ? (
                <Text type="warning" style={{ fontSize: 12 }}>
                  稿子里没认出原值
                  <HelpDot text="展开下面「模板脚本提示词」，把稿子里那句原话照抄进这一行的「原稿里写的是」，再点「重新认参数」——词面一致了才换得动。抄不进也没关系：留空只是这一项不换。" />
                </Text>
              ) : same ? (
                <Text type="secondary" style={{ fontSize: 12 }}>原稿里：{currents[0]}</Text>
              ) : (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  各篇不同：{Array.from(new Set(currents)).slice(0, 3).join('／')}
                  {currents.length > 3 ? '…' : ''}（逐篇各换各的）
                </Text>
              )}
              {!!list.length && <Tag color="green">{list.length} 个值</Tag>}
            </Space>
            {/* 11-10 用户口径「把原提示词中对应的内容也放出来，这样可以做一个对比」：
                这一行是那个词在**稿子里所在那一行**的原文（后端截断），改之前长什么样一眼看得到 */}
            {!!slot.context && (
              <div style={{ marginBottom: 2 }}>
                <Text type="secondary" style={{ fontSize: 12, lineHeight: '18px' }}>
                  稿子里这句{multiCopy && slot.contextFrom ? `（${slot.contextFrom}）` : ''}：
                  <span style={{ background: '#fffbe6', padding: '0 2px' }}>{slot.context}</span>
                </Text>
              </div>
            )}
            <Select
              mode="tags"
              style={{ width: '100%' }}
              value={list}
              onChange={(v) => setValues((prev) => ({ ...prev, [slot.key]: v as string[] }))}
              placeholder={`填入要换上的${slot.label}，回车分隔，可多个（留空＝这一项不换）`}
              options={slot.pool.map((p) => ({ value: p, label: p }))}
              maxTagCount="responsive"
              tokenSeparators={[',', '，', ' ', '\n']}
              // 候选池只是推荐：一线手打的词必须打得进去（用户口径「所有可替换参数由手动输入」，
              // antd 的 mode="tags" 本身就是「池子里没有的也能回车加进去」，别再找别的开关）
              disabled={loading}
            />
            {/* 公共原值：认不到、或各篇认法不一样时由人补。留空就不传，后端拿逐篇认到的那份 */}
            {(currents.length === 0 || !same) && (
              <Input
                size="small"
                style={{ marginTop: 4 }}
                placeholder="原稿里写的是（从底稿复制，整句也行）——这一行的值是把它换掉用的"
                value={baseVal}
                maxLength={MAX_VALUE_LEN}
                onChange={(e) => setBaseDraft((prev) => ({ ...prev, [slot.key]: e.target.value }))}
              />
            )}
          </div>
        );
      })}

      {!!computed.filled.length && (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space wrap>
            <Text style={{ fontSize: 12 }}>多个值怎么配对：</Text>
            <Radio.Group
              size="small"
              value={mode}
              onChange={(e) => setMode(e.target.value as 'zip' | 'product')}
              options={[
                { label: '按行配对（第1个场景配第1只动物…）', value: 'zip' },
                { label: '全组合（个数相乘）', value: 'product' },
              ]}
            />
          </Space>
          {computed.blocked ? (
            // 拦人的话不留浮窗里——这是「现在点提交会被打回」，必须摆在界面上
            <Text type="danger" style={{ fontSize: 12 }}>
              {computed.blocked}
            </Text>
          ) : (
            <Space wrap size={6}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {`每条文案扇 ${computed.rows} 张 → 本批 ${summaries.length * computed.rows} 组稿子`}
              </Text>
              <HelpDot
                text={`还要 × 派生份数 N × 每份出几版，见下面「要投 X 条」。换词是在展开好的那份稿子上做的，这 ${computed.rows} 张不多花模型钱，但每张各占一个钩子编号、各吃一条当天额度。`}
              />
            </Space>
          )}
        </Space>
      )}

      {!!notes.length && (
        <Space wrap size={6}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {`认参数时有 ${notes.length} 条提示`}
          </Text>
          <HelpDot
            text={
              <Space direction="vertical" size={2}>
                {notes.map((nx, i) => (
                  <span key={i}>{nx}</span>
                ))}
              </Space>
            }
          />
        </Space>
      )}

      {/* 底稿：默认收起，不把人原本就紧张的弹窗高度吃掉 */}
      {!!slots.length && (
        <Collapse
          size="small"
          items={[
            {
              key: 'draft',
              label: (
                <span style={{ fontSize: 12 }}>
                  模板脚本提示词（{summaries.length} 篇，可改）
                  <HelpDot text="改这里是让「认参数」认得准，不会改到投出去的正文。这份是过审后自动备好的投产稿预览（缺预览的用文案本身），改完点上面的「重新认参数」，词面一致了那一行才换得动。真正要改投到板上的正文，在 ④ 生产单页投板那一步的「改投递稿」里改——那才是进板面的那份字。" />
                </span>
              ),
              children: (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {summaries.map((s) => (
                    <div key={s.id}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {s.asset_code || s.id.slice(0, 8)} #{s.seq}
                        {!s.prompt_preview && '（这条没有投产稿预览，显示的是过审文案）'}
                      </Text>
                      <Input.TextArea
                        rows={4}
                        value={baseText(s)}
                        onChange={(e) => setDrafts((prev) => ({ ...prev, [s.id]: e.target.value }))}
                      />
                    </div>
                  ))}
                </Space>
              ),
            },
          ]}
        />
      )}
    </Space>
  );
};

export default AssetProduceParams;
