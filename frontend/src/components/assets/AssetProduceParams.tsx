import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Collapse, Input, Radio, Select, Space, Spin, Tag, Tooltip, Typography, message } from 'antd';
import { BulbOutlined, ReloadOutlined } from '@ant-design/icons';
import { assetApi } from '../../api/assets';
import type { AssetPromptElementFound, AssetSummary, FanoutPreviewVariant } from '../../api/assets';
import { HelpDot, HighlightedPrompt } from './AssetBits';

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
  /**
   * 11-10「帮我提炼原值」：这一行**至少有一格的原值是模型从稿子里抄回来的**。
   * 只用来打标签。模型会编，后端已经按"逐字出现在这一篇稿子的可动区间"筛过一轮，
   * 但"词在稿子里"≠"词就是这一项"（同一句里它能挑错成分），所以必须让人看一眼再投。
   */
  modelFilled?: boolean;
  /**
   * 11-11 批 Z：稿子 id → 这一格原值的**来源**。
   * `model`＝这次真问了模型（花钱）；`cache`＝这份稿子上一次抄回来的结果（0 元）；
   * 不在里面＝词表认出来的。界面按它分开打标签——"上次抄回"和"刚抄回"在人眼里的
   * 核验优先级不一样（稿子改写过后缓存才会失效，刚抄的那份才是生的一次都没人看过）。
   */
  origins?: Record<string, 'model' | 'cache'>;
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
  /**
   * 11-11 用户口径「再重新生成的时候可以重新获取」：父层去库里把这几条文案的**当前稿子**
   * 取回来（覆盖重出／改后重提／补网页版提示词都可能已经换了正文），换进来后本组件按新稿重认。
   * 不传＝这一屏没有"取最新"这条路（比如父层手里就是实时数据），按钮也就不出现。
   */
  /** 取库里最新（0 元）。返回**有变化的条数**：0＝没变化（调用方就地重认），>0＝换入后自动重认 */
  onRefetch?: () => Promise<number>;
  /** `onRefetch` 在跑：按钮转圈，别让人连点（重复取回会把上一轮的自动重认打断） */
  refetching?: boolean;
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
const AssetProduceParams: React.FC<Props> = ({ active, summaries, onChange, onRefetch, refetching }) => {
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
  /** 11-10「帮我提炼原值」：模型那一路的回话（白话说明＋丢弃清单），只在这一屏活着 */
  const [guessing, setGuessing] = useState(false);
  const [guessInfo, setGuessInfo] = useState<string[]>([]);
  const [guessError, setGuessError] = useState<string | null>(null);
  /**
   * 11-11 批 Z：刚才那一枪（自动补位／人点重问）的**花费实况**。
   * `paid=false` 时界面不许说"问了模型"——全缓存命中、没空格要补、旋钮关了、模型没通，
   * 这四种都是一分钱没花，说成花钱的会让人不敢点。
   */
  const [guessCost, setGuessCost] = useState<{
    paid: boolean;
    cached: number;
    cells: number;
  } | null>(null);
  /**
   * 11-11「再重新生成的时候可以重新获取」：稿子刚被换过、这一屏自动重认了一遍参数，
   * 就在界面上留一句话说明**重认过、并且哪些人填的东西被作废了**。不说这句，人会看见
   * 自己填的原值凭空变了（那是按新稿重认的），或投出去才发现换的是旧稿的词。
   */
  const [recheckNote, setRecheckNote] = useState<string | null>(null);
  /**
   * 11-10 用户口径①「我刚选了几个元素，但是没有看到正文被替换的地方」：
   * 「换完长这样」那一段的回包（逐篇 → 扇出的 N 张稿子）。只在点按钮时刷新，
   * `previewSig` 记住"这批预览是按哪一版参数算的"，改了参数就打陈旧标。
   */
  const [preview, setPreview] = useState<{
    items: { id: string; variants: FanoutPreviewVariant[] }[];
    rows: number;
    notes: string[];
    risk_words: string[];
    sig: string;
  } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  /** 预览展开到哪一张（每篇一份，默认第一篇的第 1 张） */
  const [previewOpen, setPreviewOpen] = useState<string[]>([]);
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;
  const summaryIds = summaries.map((s) => s.id).join(',');

  const baseText = (s: AssetSummary) =>
    drafts[s.id] ?? s.prompt_preview ?? s.text ?? '';

  /**
   * 11-10「帮我提炼原值」：模型抄回来的那几个字**在稿子里长什么样**（整行，截 160 字）。
   * 后端认出来的行有 `context`（它截的），模型这条路只有值本身，那行只能在这儿自己捞——
   * 判据就是"值逐字出现在这篇稿子里"（后端已经这么筛过），所以 indexOf 一定命中。
   * 160 = 后端 `MAX_CONTEXT_LEN`，两条路的对照长度保持一致，免得同一屏一行长一行短。
   */
  const lineHolding = (text: string, value: string): string => {
    const i = (text || '').indexOf(value || '');
    if (i < 0 || !value) return '';
    const start = text.lastIndexOf('\n', i) + 1;
    const end = text.indexOf('\n', i);
    const line = text.slice(start, end < 0 ? text.length : end).trim();
    return line.length > 160 ? `${line.slice(0, 160)}…` : line;
  };

  /**
   * 认一次参数：open／换文案／稿子换了／点「重新认参数」时跑。
   *
   * `serverDraft`＝按**库里那份稿子**认，忽略本屏还没保存的底稿编辑。
   * 「稿子刚被重新生成」那条路必须走它：人在这一屏手抄/改过的那几行是按**旧稿**改的，
   * 新稿都换了还拿旧稿的编辑去认，界面摆出来的原值在新稿里根本不存在——换词只会 skipped，
   * 而 skipped 只写在开单回执里，一线看不见，投出去才发现是一条错稿。
   * 默认（按钮／首次打开）按界面上的底稿认：人刚抄进来的那句就是要拿来认参数的，那是他主动的改动。
   */
  const extract = async (serverDraft = false) => {
    setGuessInfo([]);
    setGuessError(null);
    setGuessCost(null);
    // 底稿/字典变了，上一版预览就不是现在这套参数的结果了——宁可没有，不许陈旧还摆着像新的
    setPreview(null);
    setPreviewError(null);
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
        texts[s.id] = serverDraft ? (s.prompt_preview ?? s.text ?? '') : baseText(s);
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
      const nextSlots = Array.from(byKey.values());
      // 底稿逐字没换（还是上次问模型那一版）才把抄回的那几格接回去；换了就作废，
      // 那句是从旧稿抄来的，留着＝拿旧稿的词去新稿里换。
      const textsSig = JSON.stringify(texts);
      if (guessedCellsRef.current && guessedCellsRef.current.textsSig === textsSig) {
        const saved = guessedCellsRef.current.cells;
        nextSlots.forEach((slot) => {
          const per = saved[slot.key];
          if (!per) return;
          Object.entries(per).forEach(([sid, value]) => {
            if (!value || slot.currents[sid]) return;
            slot.currents[sid] = value;
            slot.origins = { ...(slot.origins || {}), [sid]: 'cache' };
          });
        });
        const anyHeld = nextSlots.some((slot) => Object.values(slot.origins || {}).length);
        if (anyHeld) {
          nextSlots.forEach((slot) => {
            if (Object.values(slot.origins || {}).length) slot.modelFilled = true;
          });
        }
      } else {
        guessedCellsRef.current = null;
      }
      setSlots(nextSlots);
      setNotes(res.notes || []);
      setCategoryName(res.category || (cats.length === 1 ? cats[0] : ''));
      // 2026-11-12（用户现场 AS-9305555A）：认完要给一句可见回执——参数项没变时
      // 界面一格不动，一线只会觉得「点了没反应」。顺带把两个按钮的分工说清。
      message.info(
        `已重新认出 ${nextSlots.length} 项参数${
          res.items ? `（${Object.keys(res.items).length} 篇稿子）` : ''
        }${cats.length === 1 ? `，按原型「${cats[0]}」限定` : '（这批没点原型，不限定参数项）'}`,
        6,
      );
      // 11-11 批 Z（用户原话「你不能按照固定的词典去识别，你要调用大模型的能力去做这个事情」）：
      // 词表退成**第一道 0 元粗筛**，认完还空着的那几格当场自动接模型补位，不再等人点按钮。
      // 钱有上限：后端按这份稿子的正文指纹缓存，同一篇同一格只花一次（全命中这次就 0 元）。
      void autoGuess(nextSlots, texts, cats.length === 1 ? cats[0] : undefined);
    } catch (e) {
      setError((e as Error).message || '参数项认不出来（不影响照常开单）');
      setSlots([]);
    } finally {
      setLoading(false);
    }
  };

  /**
   * 「让模型逐字抄回原值」这一枪的实现——开单屏认完词表**自动**打（`auto`）和
   * 人点「再问一次模型」（手动）共用同一段，只差三个入参，免得两条路长歪成两套口径。
   *
   * 三条不许商量的边界（都写死在后端 `accept_guessed_values`，这里只负责回填）：
   *  - **只填还没有的那一格**：已经认出的原值一个字不被覆盖，模型只补空白；
   *  - 抄回来的串必须逐字出现在这一篇稿子的可动区间里，模型编的当场丢弃，清单摆在界面上；
   *  - 只改「原稿里写的是」这半边，换成什么仍然由人填——它不是"自动生成投递稿"。
   *
   * `auto=true` 时后端不会抛错（模型那一路没通也只回一条说明，照常开单），所以异常照旧
   * 只可能来自手动那一支——那一下是人自己要的答复，失败必须原样亮出来。
   */
  const runGuess = async (opts: {
    texts: Record<string, string>;
    category?: string;
    /** 提交时那版参数行（计数按它算，回填走 setState 的 `prev`，不受中途重认影响） */
    rows: SlotView[];
    auto: boolean;
    /** 稿子 id → 词表还没认出的参数项 key；不给＝这一型全部参数项都问 */
    onlyMissing?: Record<string, string[]>;
  }) => {
    setGuessing(true);
    setGuessError(null);
    setGuessInfo([]);
    try {
      const res = await assetApi.guessPromptElementValues({
        texts: opts.texts,
        category: opts.category,
        auto: opts.auto,
        // 人主动点「再问一次」＝绕过缓存（拿上一次的结果回他等于没重问）；自动补位照旧先查缓存
        use_cache: opts.auto,
        only_missing: opts.onlyMissing,
      });
      // 先在闭包里按 `rows` 算好"这一枪补到了哪几格"，再交给 setSlots。
      // （反过来在 setState 的 updater 里边算边累加是错的：StrictMode 下 updater 会跑两遍，
      //  而且外面同步读那个计数器读到的还是 0。）
      let filledCells = 0;
      opts.rows.forEach((slot) => {
        Object.keys(opts.texts).forEach((sid) => {
          if ((res.values?.[sid] || {})[slot.key] && !slot.currents[sid]) filledCells += 1;
        });
      });
      const cachedCells = Object.values(res.from_cache || {}).reduce((a, v) => a + v.length, 0);
      setSlots((prev) =>
        prev.map((slot) => {
          const hits: Record<string, string> = {};
          const origins: Record<string, 'model' | 'cache'> = {};
          Object.keys(opts.texts).forEach((sid) => {
            const v = (res.values?.[sid] || {})[slot.key];
            // 只补空位：词表认出来的那份永远优先
            if (v && !slot.currents[sid]) {
              hits[sid] = v;
              origins[sid] = (res.from_cache?.[sid] || []).includes(slot.key) ? 'cache' : 'model';
            }
          });
          if (!Object.keys(hits).length) return slot;
          const firstSid = Object.keys(hits)[0];
          return {
            ...slot,
            currents: { ...slot.currents, ...hits },
            origins: { ...(slot.origins || {}), ...origins },
            modelFilled: true,
            // 没有对照原句的行（模型补出来的那些）把值所在那一行捞出来，
            // 这样"改之前长什么样"这一栏对自动认／模型认两种来源都一样摆得出来
            context: slot.context || lineHolding(opts.texts[firstSid] || '', hits[firstSid]),
            contextFrom: slot.context
              ? slot.contextFrom
              : summaries.find((s) => s.id === firstSid)?.asset_code || undefined,
          };
        }),
      );
      setGuessInfo([...(res.notes || []), ...(res.dropped || [])]);
      setGuessCost({ paid: !!res.paid, cached: cachedCells, cells: filledCells });
      // 记这笔账给「重新认参数」用（见 guessedCellsRef）：底稿没换时把这几格接回去，
      // 词表自己认得出的那些格接不进来都无所谓——合并那一步只填还空着的格子。
      const textsSig = JSON.stringify(opts.texts);
      if (guessedCellsRef.current?.textsSig !== textsSig) {
        guessedCellsRef.current = { textsSig, cells: {} };
      }
      Object.entries(res.values || {}).forEach(([sid, per]) => {
        Object.entries((per as Record<string, string>) || {}).forEach(([key, value]) => {
          if (!value) return;
          const slot = (guessedCellsRef.current as NonNullable<typeof guessedCellsRef.current>).cells;
          slot[key] = { ...(slot[key] || {}), [sid]: value };
        });
      });
      if (!filledCells) {
        // 两种「没补到」得说不同的话：模型那一路根本没通，和模型通了但抄回来的串不在稿子里。
        // 后者才该让人去底稿自己照抄；前者照实说"这次只用了词表的认法"，别把没发生的事写成品状。
        const downNote = (res.notes || []).some((n) => /模型那一路这次没通/.test(String(n)));
        setGuessError(
          downNote
            ? '模型那一路这次没通，这批只用了词表认出来的原值——不影响照常开单；下面那句是它回的原话，' +
              '要再试一次点上面「再问一次模型（花钱）」。'
            : '模型没抄回能用的原值（它给的串都不在这批稿子里，或这一型确实没写那些东西）——' +
              '下面展开底稿自己照抄那一句，留空不影响开单',
        );
      }
    } catch (e) {
      setGuessError((e as Error).message || '提炼原值没成功（不影响照常开单）');
    } finally {
      setGuessing(false);
    }
  };

  /**
   * 「同一版底稿同一格别重复花钱」的账本：底稿逐字签名 → 每篇**已经问过**哪几格。
   *
   * 为什么逐格记，而不是拿「这批稿子＋要补的格子」整个比签名：词表重认时会把已经抄回的那几格
   * 接回界面（见 `guessedCellsRef`），于是「还空着哪些格」这个集合自己会变小 → 整批签名一变就
   * 重新开枪，等于把上一枪**没抄到**的那几格（缓存里没有，问一次花一次钱）又问了一遍。
   * 这个漏是接回逻辑带出来的，只有逐格记账拦得住。
   */
  const askedRef = useRef<{ textsSig: string; per: Record<string, string[]> } | null>(null);

  const textsSigOf = (texts: Record<string, string>) => JSON.stringify(texts);

  const markAsked = (textsSig: string, map: Record<string, string[]>) => {
    if (!askedRef.current || askedRef.current.textsSig !== textsSig) {
      askedRef.current = { textsSig, per: {} };
    }
    Object.entries(map).forEach(([sid, keys]) => {
      const prev = askedRef.current?.per[sid] || [];
      if (askedRef.current) askedRef.current.per[sid] = Array.from(new Set([...prev, ...keys]));
    });
  };

  /**
   * 上一枪模型/缓存抄回来的那几格，连同**当时那版底稿**一起记着。
   *
   * 为什么要有这份账：`extract()` 每认一次就把整包 slots 按词表回包重建，模型补的那些格子
   * 不在词表回包里 → 点一下「重新认参数」就把刚抄回的原值当场擦成空；而花钱闸又**正确地**
   * 拦着「同一版稿子同一格别重复问」→ 两条各自都对，合起来让人看见刚有值的行又没了，
   * 而且怎么点都不会回来（只有重开弹窗或点花钱那颗才动）。所以词表重认时把这份账接回去：
   * 底稿逐字没变才接（变了说明那句是从旧稿抄的，按 11-11 口径作废），接回去的来源一律算
   * 「上次抄回（0 元）」——这一枪确实一分钱没花。
   */
  const guessedCellsRef = useRef<{
    textsSig: string;
    cells: Record<string, Record<string, string>>;
  } | null>(null);

  const autoGuess = async (rows: SlotView[], texts: Record<string, string>, category?: string) => {
    const textsSig = textsSigOf(texts);
    const missing: Record<string, string[]> = {};
    rows.forEach((slot) => {
      Object.keys(texts).forEach((sid) => {
        if (!slot.currents[sid] && (texts[sid] || '').trim()) {
          (missing[sid] = missing[sid] || []).push(slot.key);
        }
      });
    });
    const seen = askedRef.current && askedRef.current.textsSig === textsSig ? askedRef.current.per : {};
    const left: Record<string, string[]> = {};
    Object.entries(missing).forEach(([sid, keys]) => {
      const rest = keys.filter((k) => !(seen[sid] || []).includes(k));
      if (rest.length) left[sid] = rest;
    });
    if (!Object.keys(left).length) return;
    // 先记账再开枪：这一枪哪怕模型没通、或一个字都没抄到，也不该在同一个空格上原地再花一次钱
    markAsked(textsSig, left);
    await runGuess({ texts, category, rows, auto: true, onlyMissing: left });
  };

  /**
   * 人主动点的「再问一次模型」：绕过缓存原样再问一遍（11-10 用例钉的就是这一支失败要 502
   * 原样传出、一条审计都不留），所以它不带 `only_missing`——这一型的参数项全部重问。
   */
  const guess = async () => {
    if (!summaries.length || !slots.length) return;
    const texts: Record<string, string> = {};
    summaries.forEach((s) => {
      texts[s.id] = baseText(s);
    });
    const cats = Array.from(
      new Set(summaries.map((s) => (s.category_name || '').trim()).filter(Boolean)),
    );
    // 人自己掏钱把这一型的格子全问过一遍了，自动补位就不必再对同一版底稿打第二枪
    markAsked(
      textsSigOf(texts),
      Object.fromEntries(summaries.map((s) => [s.id, slots.map((x) => x.key)])),
    );
    await runGuess({ texts, category: cats.length === 1 ? cats[0] : undefined, rows: slots, auto: false });
  };

  /**
   * 这批文案「库里那份稿子」的签名（正文＋豆包提示词预览＋原型）。**不含本地底稿编辑**——
   * 人在这一屏敲字不该打接口（正文上千字，一次一屏），那种改动照旧靠「重新认参数」按钮。
   */
  const incomingSig = useMemo(
    () =>
      summaries
        .map((s) => `${s.id}#${(s.category_name || '').trim()}#${s.text ?? ''}#${s.prompt_preview ?? ''}`)
        .join('|'),
    [summaries],
  );
  /** 上一次自动认参数是**按哪一批**、**按哪一版稿子**认的（关掉弹窗就清空＝下次打开算新一轮） */
  const scopeRef = useRef('');
  const sigRef = useRef('');

  /**
   * 什么时候自动重认——11-11 用户口径「再重新生成的时候可以重新获取」要求两种情况分开，
   * 因为它们该留的东西不一样：
   *  ① **换了一批文案**（勾选变了）＝这一屏重开。上一批的换后值／公共原值／底稿编辑都是
   *     按上一批稿子填的，留着会往这批上换错词 → 全部归零再认（沿用原口径，顺带也解决了
   *     「admin 刚在字典里加了参数项，缓存那份看不见」）。
   *  ② **还是这批文案，但稿子本身换了**——在别的屏「覆盖重出」／「改后重提」／补网页版提示词，
   *     或点了本屏的「取最新稿子」。这时**自动重新认原值**，而且人填的「换成什么」照旧留着
   *     （那是人打的字，跟稿子新旧无关，清掉等于把输入抹了）；但本地底稿编辑和手填的公共原值
   *     按新稿作废（它俩都是从**旧稿**抄来的，留着＝拿旧稿的词去新稿里换，后端只会记一条
   *     skipped，界面看不出来）。上一版「换完长这样」也跟着作废，不许陈旧还摆着像新的。
   */
  useEffect(() => {
    if (!active || !summaries.length) {
      scopeRef.current = '';
      sigRef.current = '';
      // 关掉弹窗＝闸门作废：下次重开还要自动补位（这一枪**不会白花钱**——已经抄回来的
      // 那几格后端按正文指纹命中缓存、0 元，只有上次真没抄到的才会再问一次）
      askedRef.current = null;
      guessedCellsRef.current = null;
      return;
    }
    const prevScope = scopeRef.current;
    const prevSig = sigRef.current;
    scopeRef.current = summaryIds;
    sigRef.current = incomingSig;
    if (prevScope !== summaryIds) {
      setValues({});
      setBaseDraft({});
      setDrafts({});
      setPreview(null);
      setPreviewOpen([]);
      setRecheckNote(null);
      askedRef.current = null;
      guessedCellsRef.current = null;
      void extract();
      return;
    }
    if (prevSig && prevSig !== incomingSig) {
      setBaseDraft({});
      setDrafts({});
      setPreview(null);
      setPreviewOpen([]);
      setRecheckNote(
        '这批文案的稿子刚被重新生成过，参数项已按新稿重认一遍。你填的「换成什么」都留着；' +
          '「原稿里写的是」和下面手改的底稿是按旧稿抄的，已清空——按新稿重填即可（不填也能照常开单）。',
      );
      void extract(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, summaryIds, incomingSig]);

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

  /**
   * 这次预览是按哪一版参数算的（值／原值／配对方式／底稿全算进去）。
   * 拿它和当前 `computed` 比，不一样就是"人又改了"——界面上打陈旧标，不骗人说这就是现在的稿子。
   */
  const previewSig = JSON.stringify({
    v: computed.values,
    b: computed.base,
    bb: computed.baseBySummary,
    m: computed.mode,
    t: summaries.map((s) => `${s.id}:${baseText(s).length}:${baseText(s)}`),
  });

  /**
   * 11-10 用户口径①：把「每个参数填了多个值」扇出来的那几张稿子**当场组给人看**。
   * 走的是开单同一个引擎（后端 `expand_matrix`＋`compose_variants`），
   * 0 元、不落库、不占号；换词位置由后端算（`marks`），这里只描色。
   */
  const runPreview = async () => {
    if (!computed.filled.length || computed.blocked) return;
    setPreviewing(true);
    setPreviewError(null);
    try {
      const texts: Record<string, string> = {};
      summaries.forEach((s) => {
        texts[s.id] = baseText(s);
      });
      const cats = Array.from(
        new Set(summaries.map((s) => (s.category_name || '').trim()).filter(Boolean)),
      );
      const res = await assetApi.previewPromptElementFanout({
        texts,
        category: cats.length === 1 ? cats[0] : undefined,
        values: computed.values,
        base: computed.base,
        base_by_summary: computed.baseBySummary,
        mode: computed.mode,
      });
      setPreview({ items: res.items || [], rows: res.rows, notes: res.notes || [], risk_words: res.risk_words || [], sig: previewSig });
      // 默认只展开第一篇的第 1 张：一屏全展开的话，"看得清"又变回"一坨"
      const first = (res.items || [])[0];
      setPreviewOpen(first?.variants?.length ? [`${first.id}-1`] : []);
    } catch (e) {
      setPreviewError((e as Error).message || '这份预览没组出来（不影响照常开单）');
      setPreview(null);
    } finally {
      setPreviewing(false);
    }
  };

  /** 「一行原值都没认出」的参数项行数：只给「帮我提炼原值」那个按钮写清楚它是为谁跑的 */
  const unrecognized = slots.filter((s) => !Object.keys(s.currents).length).length;

  if (!active || !summaries.length) return null;

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <Space wrap size={6}>
        <Text strong>换皮参数（填多个值＝一次出多条）</Text>
        {/* 11-10 用户口径「说明太长篇大论，缩进浮窗」：这段解释从 Tooltip 换成「？」，界面只留标题 */}
        <HelpDot text="参数项来自「可替换元素库」字典（按钩子原型配的行）。原值分两道认：先用字典里的词面 0 元认一遍，认不出的那几格**自动**交给模型从这篇稿子里逐字抄回（后端按正文存着，同一篇同一格只花一次钱）。标签会写明每一格是词表认的还是模型抄的。填多个值＝一次扇多条，换词本身不花钱。" />
        {!!categoryName && <Tag color="blue">{categoryName}</Tag>}
        {!categoryName && (
          <Tooltip title="这批候选还没点钩子原型：不限定参数项，全部参数都会摆出来。想让开单只按某个原型的参数换皮，去审核台给候选「点原型」（素材上改原型只影响以后新出的文案）。">
            <Tag color="orange">未点原型</Tag>
          </Tooltip>
        )}
        {multiCopy && (
          <Tooltip title={`这批选了 ${summaries.length} 条文案，各篇的原值可能不同：后端按每条稿子自己认到的值分别换，认不出的那些才用下面手填的公共原值`}>
            <Tag>{summaries.length} 篇各认各的原值</Tag>
          </Tooltip>
        )}
        {/* 2026-11-12 审计（用户现场「搞这么复杂吗」）：原来「重新认参数／取最新稿子」
            两颗按钮的分工没人分得清——一线改了原型点重认，界面纹丝不动。合并成一颗：
            点一下＝先去库里拉最新（0 元；正文/提示词/原型有更新就换入并自动重认），
            库里没变化就按屏幕这一版就地重认。你手抄的底稿编辑照旧保留（独立状态）。 */}
        <Tooltip title="去库里取这批文案最新的正文、提示词和原型（0 元），有更新自动重认；没更新就按当前屏幕底稿重认一遍。你在本屏手抄/改过的底稿不会被动冲掉。">
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={loading || refetching}
            onClick={async () => {
              setRecheckNote(null);
              const changed = (await onRefetch?.()) ?? 0;
              if (!changed) void extract();
            }}
          >
            重新认参数
          </Button>
        </Tooltip>
        {/* 11-11 批 Z 改了口径（用户原话「你不能按照固定的词典去识别，你要调用大模型的能力
            去做这个事情」）：认不出来的那一格**认完词表就已经自动问过模型**了，这颗按钮不再
            是唯一入口，只留给人主动「绕过已经存着的结果、让模型重新抄一遍」。
            它一定会再花一次钱，所以措辞不许含糊，花钱与否在下一行按实况说真话。 */}
        {!!slots.length && (
          <Tooltip title="认不出来的那几格，点「重新认参数」后会自动问一轮模型（同一篇稿子同一格只花一次钱，之后走缓存）。这一颗是绕过缓存原样再问一遍——会再花一次钱，改了字典或想让模型重看时用它。">
            <Button size="small" icon={<BulbOutlined />} loading={guessing} onClick={guess}>
              再问一次模型（花钱）
            </Button>
          </Tooltip>
        )}
      </Space>

      {recheckNote && (
        <Alert type="info" showIcon closable onClose={() => setRecheckNote(null)} message={recheckNote} />
      )}
      {guessing && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          词表认完了，正在让模型把还空着的那几格逐字抄回稿子里的原话…（不等开单，投不投都照旧）
        </Text>
      )}
      {!guessing && guessCost && !guessError && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {guessCost.paid
            ? `这一下问了模型：补到 ${guessCost.cells} 格` +
              (guessCost.cached
                ? `，另有 ${guessCost.cached} 格直接用了这份稿子上一次抄回的结果（0 元）`
                : '（同一篇稿子的同一格下次不再花钱）')
            : guessCost.cached
              ? `没花钱：${guessCost.cached} 格用的是这份稿子上一次抄回的结果`
              : '这一枪一分钱没花（没有要补的空格／自动提炼的旋钮关了／模型那一路这次没通），下面那句是原话'}
        </Text>
      )}
      {/* 词表＋模型都跑过还全行皆空的参数项：把"为什么还是空的"说在前面，不然人会以为这一屏坏了 */}
      {!guessing && !!slots.length && unrecognized > 0 && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          还有 {unrecognized} 行一个原值都没认出来（词表和模型都过了一遍）——多半这几篇稿子里确实没写那样东西，
          留空照常开单，只是这一项不换。
        </Text>
      )}
      {guessError && (
        <Alert
          type="warning"
          showIcon
          message={guessError}
          description={
            guessInfo.length ? (
              <Space direction="vertical" size={2}>
                {guessInfo.slice(0, 8).map((nx, i) => (
                  <span key={i} style={{ fontSize: 12 }}>
                    {nx}
                  </span>
                ))}
                {guessInfo.length > 8 && (
                  <span style={{ fontSize: 12 }}>另有 {guessInfo.length - 8} 条没列出</span>
                )}
              </Space>
            ) : undefined
          }
        />
      )}
      {!guessError && !!guessInfo.length && (
        <Space wrap size={6}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {`模型提炼回话 ${guessInfo.length} 条`}
          </Text>
          {/* 同 212 批的口径：长说明缩进浮窗，不吃掉弹窗高度 */}
          <HelpDot
            text={
              <Space direction="vertical" size={2}>
                {guessInfo.map((nx, i) => (
                  <span key={i}>{nx}</span>
                ))}
              </Space>
            }
          />
        </Space>
      )}

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
        // 11-11 批 Z：这一行里模型补的格子分「这次真问了模型」和「上次抄回、这次 0 元复用」两种，
        // 分开打标签——前者一次都没人看过，核验优先级更高。
        const originList = Object.values(slot.origins || {});
        const freshCells = originList.filter((o) => o === 'model').length;
        const reusedCells = originList.length - freshCells;
        return (
          <div key={slot.key}>
            <Space wrap size={6} style={{ marginBottom: 2 }}>
              <Tooltip
                title={
                  slot.modelFilled
                    ? `${slot.note ? `${slot.note}\n` : ''}这一行的原值里有模型从稿子里逐字抄回来的那几格（后端验过确实出现在这一篇里，编的已经丢掉）。词在稿子里≠词就是这一项——投之前扫一眼；抄错了就在下面「原稿里写的是」那格改成对的。`
                    : slot.note || undefined
                }
              >
                <Text style={{ fontSize: 12 }}>
                  {slot.label}
                  {slot.mode === 'manual' && !slot.modelFilled && (
                    <Tag style={{ marginLeft: 6 }}>要自己抄原句</Tag>
                  )}
                  {slot.mode === 'pattern' && <Tag style={{ marginLeft: 6 }}>按写法认</Tag>}
                  {/* 来源标必须摆出来：模型只保证"这几个字在这篇稿子里"，不保证"这几个字就是这一项" */}
                  {!!freshCells && (
                    <Tag color="gold" style={{ marginLeft: 6 }}>
                      模型抄回 {freshCells} 格，请核一眼
                    </Tag>
                  )}
                  {!!reusedCells && (
                    <Tooltip title="这份稿子上一次已经问过模型、结果按正文存着（`asset_element_guesses`），这次直接复用，一分钱没花。稿子一改写就会重新问。">
                      <Tag style={{ marginLeft: 6 }}>上次抄回 {reusedCells} 格（0 元）</Tag>
                    </Tooltip>
                  )}
                </Text>
              </Tooltip>
              {currents.length === 0 ? (
                <Text type={guessing ? 'secondary' : 'warning'} style={{ fontSize: 12 }}>
                  {guessing ? '词表没认出，正在让模型从这篇稿子里抄…' : '词表和模型都没认出原值'}
                  <HelpDot text="这一行 0 元的词表和模型都过了一遍还是空的——认完词表会自动问一次模型（同一篇稿子的同一格只花一次钱）。空着多半是这篇稿子里确实没写那样东西，也可能是模型抄回来的词没通过「必须逐字出现在稿子里」那道校验。要自己填：展开下面「模板脚本提示词」，把稿子里那句原话照抄进这一行的「原稿里写的是」，词面一致了才换得动。留空不影响开单，只是这一项不换。" />
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

          {/* ── 「换完长这样」（11-10 用户口径①「选了元素但看不到正文被替换的地方」）──
              0 元、不占号，走的和开单同一个引擎，所以这里看到的字＝开出去那张单带的字
              （唯一差别：开单时模型还会把文案展开成投递稿，那份以 ④「改投递稿」为准——这句话必须摆出来） */}
          {!computed.blocked && (
            <div style={{ borderTop: '1px dashed #e5e5e5', paddingTop: 6 }}>
              <Space wrap size={6}>
                <Text strong style={{ fontSize: 12 }}>
                  换完长这样
                </Text>
                <Button size="small" loading={previewing} onClick={runPreview}>
                  {preview ? '按现在的参数重新算一遍' : `看看这 ${computed.rows} 张换完长什么样`}
                </Button>
                {preview && preview.sig !== previewSig && (
                  <Tooltip title="参数在这份预览之后又改过了，下面还是按上一次那份算的——点左边按钮重算">
                    <Tag color="orange">参数改了，这份是旧的</Tag>
                  </Tooltip>
                )}
                <HelpDot text="不花钱、不占号、不落库：就是拿上面那份底稿，按你现在填的值逐张替换一遍给你看。绿底＝换上的新词（位置由后端算，不是前端猜）。开单时模型还会把文案展开成投递稿，那一版和这里可能有个别字的差别，最终以 ④ 投板前「改投递稿」那一屏为准。" />
              </Space>

              {previewError && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginTop: 6 }}
                  message={`预览没组出来：${previewError}`}
                  description="不影响照常开单，这只是这一屏的对照稿。"
                />
              )}
              {!!preview?.risk_words.length && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginTop: 6 }}
                  message={`这几处换上来的词会被投板闸门拦下（${preview.risk_words.length} 条）`}
                  description={
                    <Space direction="vertical" size={2}>
                      {preview.risk_words.slice(0, 6).map((w, i) => (
                        <span key={i} style={{ fontSize: 12 }}>
                          {w}
                        </span>
                      ))}
                      {preview.risk_words.length > 6 && (
                        <span style={{ fontSize: 12 }}>另有 {preview.risk_words.length - 6} 条没列出</span>
                      )}
                    </Space>
                  }
                />
              )}

              {/* 11-10 用户口径①「选了元素但看不到正文被替换的地方」补齐的另一半：
                  后端 fanout-preview 回的 `notes` 说的是**这批值怎么配成这几张**
                  （「光线只填了一个值，2 条里都用它」／「全组合：2×3＝6 条」）。
                  以前只把 `risk_words` 摆了，notes 存进 state 却从不渲染——人看到 6 张却不知道
                  为什么是 6 张，跟"看不到换了哪"是同一个毛病。摆一行，长话进「？」。 */}
              {!!preview?.notes.length && (
                <Space wrap size={6}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {`这批值配成 ${preview.rows} 张：${preview.notes[0]}`}
                  </Text>
                  {preview.notes.length > 1 && (
                    <HelpDot
                      text={
                        <Space direction="vertical" size={2}>
                          {preview.notes.map((nx, i) => (
                            <span key={i}>{nx}</span>
                          ))}
                        </Space>
                      }
                    />
                  )}
                </Space>
              )}

              {!!preview && (
                <Collapse
                  size="small"
                  style={{ marginTop: 6 }}
                  activeKey={previewOpen}
                  onChange={(k) => setPreviewOpen(Array.isArray(k) ? (k as string[]) : [k as string])}
                  items={preview.items.flatMap((it) => {
                    const s = summaries.find((x) => x.id === it.id);
                    const shown = it.variants.slice(0, 8);
                    return shown.map((v, i) => {
                      const code = s?.asset_code || s?.hook_code || it.id.slice(0, 8);
                      return {
                        key: `${it.id}-${v.seq}`,
                        label: (
                          <span style={{ fontSize: 12 }}>
                            {multiCopy ? `${code} 第 ${v.seq} 张` : `第 ${v.seq} 张`}
                            {v.changed ? (
                              <Tag color="green" style={{ marginLeft: 6 }}>
                                换了 {v.replaced.filter((r) => r.count > 0).length} 项
                              </Tag>
                            ) : (
                              <Tag style={{ marginLeft: 6 }}>这一张和底稿一模一样</Tag>
                            )}
                            {!!v.missing.length && (
                              <Tooltip title={`这几项没有原值，这一张没换：${v.missing.join('、')}`}>
                                <Tag color="gold" style={{ marginLeft: 4 }}>
                                  {v.missing.length} 项没换
                                </Tag>
                              </Tooltip>
                            )}
                          </span>
                        ),
                        children: (
                          <Space direction="vertical" size={6} style={{ width: '100%' }}>
                            <Space wrap size={4}>
                              {Object.entries(v.values).map(([k, val]) => {
                                const lb =
                                  v.replaced.find((r) => r.key === k)?.label || slots.find((sl) => sl.key === k)?.label || k;
                                return (
                                  <Tag key={k} color="blue">
                                    {`${lb}→${val}`}
                                  </Tag>
                                );
                              })}
                            </Space>
                            <HighlightedPrompt text={v.text} marks={v.marks} maxHeight={220} />
                            {!!v.notes.length && (
                              <Space wrap size={6}>
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {`这一张有 ${v.notes.length} 句要说`}
                                </Text>
                                <HelpDot
                                  text={
                                    <Space direction="vertical" size={2}>
                                      {v.notes.map((n, ni) => (
                                        <span key={ni}>{n}</span>
                                      ))}
                                    </Space>
                                  }
                                />
                              </Space>
                            )}
                          </Space>
                        ),
                      };
                    });
                  })}
                />
              )}
              {!!preview && preview.items.some((it) => it.variants.length > 8) && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  每篇只列出前 8 张，剩下的开完单在生产单页逐张看（那张数一样的字）。
                </Text>
              )}
            </div>
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
