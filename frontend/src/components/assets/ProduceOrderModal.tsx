import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Button, Checkbox, Descriptions, Input, Modal, notification, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { RECHECK_CODE_LABELS, assetApi, isAssetJobAck, waitForAssetJob } from '../../api/assets';
import type { AssetProduceResponse, AssetSummary } from '../../api/assets';
import { HOOK_CODE_RE, MonoText, parseHookCodes } from './AssetBits';
import AssetCardPicker from './AssetCardPicker';
import AssetProduceParams, { EMPTY_PRODUCE_PARAMS } from './AssetProduceParams';
import type { ProduceParams } from './AssetProduceParams';
import { nudgeAssetJobBanner } from './AssetJobBanner';
import { withCrossOwnerConfirm } from './crossPerson';
import { useAuth } from '../../contexts/AuthContext';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  /** 只有「已过审 / 改后通过」的文案能进这里（后端也会挡） */
  summaries: AssetSummary[];
  isAdmin: boolean;
  onClose: () => void;
  /** 建单成功后回主面板（切到生产单页签＋重新拉列表）。 */
  onDone: () => void;
  /**
   * 11-10 用户口径「一屏到底」：点「生成生产单并投去出片」→ 开单这一屏**自己缩掉**，
   * 把刚建的那几张单直接顶进 ④ 生产单的「投去 AI 出片」确认窗（不再让人回列表勾一遍）。
   * `notes` 是开单结果里那些「原来那一屏会亮、缩掉后就没人说」的提醒（漂移/没过自动检查/
   * 标题超字…），由投板确认窗接着说。父层没接（老入口）就退化成一条消息条。
   */
  onProduced?: (ids: string[], notes: string[]) => void;
  /**
   * 批 L：就地上传角色卡挂的批次（=被投产素材所在批次）。可选——
   * 生产单页「全部」视图开单时拿不到，就由上传口新建小批次。
   */
  batchId?: string;
}

/**
 * 建单结果压成白话句子（11-10 一屏到底）。
 *
 * 原来这些全在开单窗的「结果屏」上分六个 Alert 摆着；现在点完建单窗口就缩了，
 * 警示不能跟着一起消失——所以在这里收成几句人话，交给**下一屏**（投板确认窗／
 * 右上角消息条）接着说。只留会影响「要不要投」的那几类，逐条上限 5 条免得刷屏。
 */
export function produceResultNotes(res: AssetProduceResponse): string[] {
  const out: string[] = [];
  (res.recheck_failed || []).slice(0, 5).forEach((f) =>
    out.push(`${f.code}：自动检查没过（${(f.problems || []).map((p) => p.message).join('；')}），这条没建单`),
  );
  (res.drifted || []).slice(0, 5).forEach((d) =>
    out.push(`${d.code} #${d.seq}：正文和过审文案对不上（${d.reason || '对不上'}）——别直接投，先在生产单页逐条改名或回审核台改文案`),
  );
  (res.element_fanout?.skipped || []).slice(0, 5).forEach((s) =>
    out.push(`${s.code}：这组词拼进句子后撞上高风险词 ${s.words.join('、')}，那一条没建单（同批其它条照常建）`),
  );
  (res.prompt_skeleton_gaps || []).slice(0, 3).forEach((g) =>
    out.push(`${g.code} #${g.seq}：缺 ${g.missing.join('、')}（缺「负面约束」会出怪片、缺「音频与字幕」会被加字幕）`),
  );
  (res.title_warnings || []).slice(0, 3).forEach((w) =>
    out.push(`${w.asset_code} #${w.seq}：推荐标题「${w.title}」实测 ${w.chars} 字／上限 ${w.limit} 字，超了会被截断`),
  );
  (res.cards || [])
    .filter((c) => c.orientation === 'landscape')
    .slice(0, 2)
    .forEach((c) => out.push(`角色卡「${c.file_name || c.code || ''}」是横版：出的是横屏片（画幅由卡决定，提示词写 9:16 压不住）`));
  (res.warnings || []).slice(0, 4).forEach((wn) => out.push(wn));
  return out;
}

/**
 * 投产：过审文案 → N 条差异化提示词（生产单）。
 *
 * 三个量必须分开，混了就白烧号池：
 *  - `n`：一条文案派生几份**差异化**提示词（＝几个任务）；
 *  - `board_total`：板上 total＝同一条提示词出几版；
 *  - 真实投板量 = 文案数 × n × board_total。
 * 号池实测 ≈120 条/日，产能不做硬限（11-03 拍板），但建单当场就把「今天已经吃掉多少」摆出来。
 * 钩子编号只能从 hook_id.py 取号带进来，前端不生成、后端不编号。
 */
const ProduceOrderModal: React.FC<Props> = ({ open, summaries: picked, isAdmin, onClose, onDone, onProduced, batchId }) => {
  const { user } = useAuth();
  const currentUserId = user?.id;
  /**
   * 11-11 用户口径「再重新生成的时候可以重新获取」：`picked` 是**进弹窗那一刻**的快照，
   * 而这一屏可能开着就去别的屏「覆盖重出」／「改后重提」／补了网页版提示词——稿子换了，
   * 换皮参数还按旧稿认，投出去就是拿旧稿的词换新稿（后端只会记一条 skipped，界面看不见）。
   * 所以本组件自己持一份「当前用的文案」，「取最新稿子」把库里现在的样子换进来，
   * 下面所有算法（待取号数、扇出行数、提交入参）跟着一起换——只有一处真相。
   */
  const [liveSummaries, setLiveSummaries] = useState<AssetSummary[]>(picked);
  const summaries = liveSummaries;
  const [refetching, setRefetching] = useState(false);

  // 父层那份快照：**打开这一屏**或**勾选的那几条变了**才以它为准。
  // ⚠️ 不能按 `picked` 的引用同步（三个入口里 `approvedSelected` 这类是每次渲染现算的数组，
  // 引用天天变），那样父层一重渲染就把本屏「取最新稿子」换回来的行覆盖回旧快照，
  // 人刚看见的新稿又变回旧的——按 id 集合判"是不是同一批"才是这件事的本意。
  const pickedIds = picked.map((s) => s.id).join(',');
  useEffect(() => {
    setLiveSummaries(picked);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pickedIds]);

  /**
   * 取回这几条文案**当前**的稿子：一次列表读口（0 元、不动库、不占号）。
   * 三种结果分开说，因为下一步动作不一样：
   *  - 有变化 → 换进来，子组件那段签名会自动按新稿重认参数（人填的换后值保留）；
   *  - 没变化 → 明说「还是刚才那一版」，别让人以为点了没反应；
   *  - 库里查不到（撤审后整批重出把旧行作废了、或素材被删）→ 保留旧的那份并点名，
   *    开单时后端那道闸门会自己拦下；这里先说一声，省得人投出去才发现少了几条。
   */
  const refetchLatest = async () => {
    if (!liveSummaries.length) return;
    setRefetching(true);
    try {
      const res = await assetApi.listSummaries({
        ids: liveSummaries.map((s) => s.id).join(','),
        page_size: 300,
      });
      const byId = new Map((res.items || []).map((i) => [i.id, i]));
      const sameDraft = (a: AssetSummary, b: AssetSummary) =>
        (a.text ?? '') === (b.text ?? '')
        && (a.prompt_preview ?? '') === (b.prompt_preview ?? '')
        && (a.category_name ?? '') === (b.category_name ?? '');
      const gone: string[] = [];
      const changed: string[] = [];
      const next = liveSummaries.map((s) => {
        const fresh = byId.get(s.id);
        if (!fresh) {
          gone.push(s.asset_code || s.hook_code || s.id.slice(0, 8));
          return s;
        }
        if (!sameDraft(s, fresh)) {
          changed.push(s.asset_code || s.hook_code || s.id.slice(0, 8));
          return fresh;
        }
        // 稿子没动就别换引用：换了子组件的签名不变、不重认，但 React 会白重渲染一整屏
        return s;
      });
      if (changed.length) setLiveSummaries(next);
      if (gone.length) {
        message.warning(
          `${gone.length} 条在库里已经查不到了（${gone.slice(0, 3).join('、')}${gone.length > 3 ? '…' : ''}）`
            + '——多半是刚被撤审重出或素材删掉了，这里先留着旧稿，开单时后端会点名拦下',
          8,
        );
      }
      if (changed.length) {
        message.success(`已取回最新稿子：${changed.length} 条正文/提示词变了，参数项按新稿重认过`, 6);
      } else if (!gone.length) {
        message.info('这几条的稿子没变，还是刚才那一版（参数项不用重认）');
      }
    } catch (e) {
      message.error(`${(e as Error).message || '取最新稿子没成功'}——不影响照常开单，按手里这一版继续`, 8);
    } finally {
      setRefetching(false);
    }
  };

  const [n, setN] = useState(3);
  const [boardTotal, setBoardTotal] = useState(1);
  const [accounts, setAccounts] = useState(1);
  const [titleCount, setTitleCount] = useState<number | undefined>(undefined);
  const [boardTag, setBoardTag] = useState('');
  /**
   * 批 G：角色卡改成「从素材库挑」，这里存的是 asset_items.id 数组，
   * **顺序＝板上 picDatas 顺序**。旧的那个手填 MinIO key 的框已经删掉——
   * 那个值被后端原样当 key 用，打错一个字符照样建单，只是投出去是一条没卡的片。
   */
  const [cardIds, setCardIds] = useState<string[]>([]);
  const [dramaAbbr, setDramaAbbr] = useState('');
  const [codeText, setCodeText] = useState('');
  /**
   * 11-06 拍板③：填了号就查哪些已经被钉在生产单上（GET /assets/hook-codes/used）。
   * 回显是软提醒（打字过程中尽力而为），提交时后端还有一道硬查重兜底——
   * 号一发就烧掉，作废单也不复用，所以这里查到的直接拦提交。
   */
  const [usedCodes, setUsedCodes] = useState<
    { code: string; asset_code: string; seq: number; status: string }[]
  >([]);
  const usedReqRef = useRef(0);
  const [expand, setExpand] = useState(true);
  const [waiveReason, setWaiveReason] = useState('');
  /**
   * R-6 分粒度：上一次自动检查拦下的问题类型（union）。管理员默认全放行＝整条放过，
   * 想只放一类（例如只放字数、把违禁词继续卡住）就取消勾选。空列表＝这次不放行任何一类，
   * 所以提交时不带 waive_codes（后端把留空当整条放过，绝不能由「全取消」误触发）。
   */
  const [waiveCodes, setWaiveCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AssetProduceResponse | null>(null);
  /**
   * D-1：投产（expand=true）要按 n 逐条调模型，一批几分钟到十几分钟，
   * 同步等会一路撞上浏览器/nginx 超时。现在提交即回任务号，这里**边轮询边把状态显示出来**；
   * 人中途关掉窗口也安全——任务在后台照跑，顶部横幅和生产单列表会接住结果。
   */
  const [jobHint, setJobHint] = useState<string | null>(null);
  const giveUpRef = useRef(false);
  /**
   * 11-10「钩子编号也自动取了，不要人工参与」：自动取号失败时才有内容。
   * 失败不静默放行（缺号单导出带不上编号、回头补号要一张一张钉），而是把白话原因摆出来，
   * 顺带给出唯一的两条退路：我自己贴号 / 复制待取号清单去服务器跑。
   */
  const [autoTakeError, setAutoTakeError] = useState<string | null>(null);
  /** 手工贴号那一格默认不出现——只有自动取号失败、且人自己点开才给（正常路径零人工） */
  const [codesManualOpen, setCodesManualOpen] = useState(false);
  /**
   * 批 O（11-10 用户口径）：换皮参数区算出来的那份（多值＋配对方式＋扇出行数）。
   * 放在父组件而不是子组件里，是因为**三个地方都要用它**：待填号数、要投几条的预告、
   * 以及提交时的 element_* 入参——一处算两份口径迟早对不上。
   */
  const [params, setParams] = useState<ProduceParams>(EMPTY_PRODUCE_PARAMS);

  // 11-10 用户口径「一屏到底」＋「确认去投产的时候那个窗口就自动关闭掉吧」：
  // 批 I 的「结果屏上再点一次投去出片」取消了——点「生成生产单并投去出片」这一颗按钮
  // 就代表要投，建完单当场关窗，把新单直接顶进 ④ 的投板确认窗（那一屏照旧能看全文／
  // 改投递稿／挑拼接素材，确认那一下也是当场关窗）。这里不再自己调 dispatch 口。
  /** 这一颗按钮按下去是要「建完就投」还是「只建单」——决定成功后的分流，也决定哪颗按钮转圈 */
  const [submitIntent, setSubmitIntent] = useState<'dispatch' | 'build_only'>('dispatch');

  // 批 M（评审二·P1-4）：Modal destroyOnClose 只销毁子树，本组件的 state 跨开合残留——
  // cardIds/codeText 这类"上一单填的"会 silently 落到下一单上。
  // 打开时统一归零；n/boardTotal/accounts 这类"上一批怎么配的"保留——批量开单时是顺手的好默认。
  useEffect(() => {
    if (!open) return;
    setSubmitIntent('dispatch');
    setResult(null);
    setJobHint(null);
    giveUpRef.current = false;
    setCardIds([]);
    setCodeText('');
    setUsedCodes([]);
    setAutoTakeError(null);
    setCodesManualOpen(false);
    setBoardTag('');
    setDramaAbbr('');
    setWaiveReason('');
    setWaiveCodes([]);
    // 批 O：参数行/底稿是**这一批文案**的，换一批必须归零（子组件自己也会重认，
    // 但父组件留着上一批的 rows 会把待填号数算错）
    setParams(EMPTY_PRODUCE_PARAMS);
  }, [open]);

  // 批 O：扇出是「一条稿子换词后另立单」，所以**编号与投板条数都要乘上扇出行数**
  // （后端 codes_for_summary 一次取 n×扇出行数，号不够就只能建出缺号的单）。
  const fanoutRows = Math.max(1, params.rows);
  const needCodes = summaries.length * n * fanoutRows;
  const codes = useMemo(() => parseHookCodes(codeText), [codeText]);
  const badCodes = codes.filter((c) => !HOOK_CODE_RE.test(c));
  const dupCodes = codes.length !== new Set(codes).size;
  const plannedRows = summaries.length * n * boardTotal * fanoutRows;

  /**
   * 批 N（11-09 用户口径「现有已经导入的那些文案，你都去取一个编号放着吧」）：
   * 文案名下预取好、还没用掉的号。后端在**开单当场**把它们顶到缺号的槽位上
   * （一条文案最多顶一个），顶掉即清空，所以这里只报「有几个备用」并把待填数扣掉，
   * 不做任何前端拼装——编号的前途由后端一处决定，避免两套口径。
   */
  const parkedCodes = useMemo(
    () => summaries.map((s) => s.hook_code).filter((c): c is string => !!c),
    [summaries],
  );
  /**
   * 11-10「编号也自动取」还差几个＝需要的总数 − 文案名下已预取的 − 这一屏已经拿到的。
   * 自动取来的号会回填进 `codeText`，所以点第二次提交不会二次取号（号一发即烧，
   * 取两遍就是白废一批）。
   */
  const needAutoCodes = Math.max(0, needCodes - parkedCodes.length - codes.length);

  // 11-06 拍板③：500ms 防抖查已用号（不逐键打接口）；请求序号防乱序回包。
  // 回显失败静默——提交时后端硬查重还在，别因为一个回显口把填单卡死。
  useEffect(() => {
    if (!open || !codes.length) {
      setUsedCodes([]);
      return;
    }
    const reqId = ++usedReqRef.current;
    const timer = setTimeout(async () => {
      try {
        const res = await assetApi.hookCodesUsed(codes);
        if (usedReqRef.current === reqId) setUsedCodes(res.used);
      } catch {
        /* 尽力而为 */
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [open, codes]);

  /** 自动检查拦下的问题类型回填到表单，回到表单就能按类只放行一部分（R-6 分粒度） */
  const collectRecheckCodes = (res: AssetProduceResponse) => {
    const seen: string[] = [];
    (res.recheck_failed || []).forEach((f) =>
      (f.problems || []).forEach((p) => !seen.includes(p.code) && seen.push(p.code)),
    );
    if (seen.length) setWaiveCodes(seen);
  };

  /**
   * 建单成功后的分流（11-10 一屏到底）。三种收场：
   *  - **有单＋要投**：当场关窗，把新单 id／该接着说的提醒交给父层——下一屏就是 ④ 的
   *    「投去 AI 出片」确认窗（预勾好这几张），人不用再点一次「去投板」；
   *  - **有单＋只建单**（或父层没接 onProduced／通道不是企微任务板）：当场关窗＋一条
   *    右上角消息条；有提醒时消息条**不自动关**，因为那是「这批单有问题、先别投」的证据；
   *  - **一张都没建成**：**不关窗**。原来那一屏的分项警示（自动检查没过／漂移／缺行…）
   *    这时候是唯一的现场证据，缩掉了人就只剩一句「失败」。
   */
  const afterProduced = (res: AssetProduceResponse, intent: 'dispatch' | 'build_only') => {
    collectRecheckCodes(res);
    const ids = (res.production_ids || []).filter(Boolean);
    const notes = produceResultNotes(res);
    if (!ids.length) {
      setResult(res);
      message.error('这一批一张生产单都没建出来，原因见窗口里列的几条', 8);
      return;
    }
    setResult(null);
    setJobHint(null);
    onClose();
    const channelOk = res.board.channel === 'wework_aivideo';
    if (intent === 'dispatch' && onProduced && channelOk) {
      onProduced(ids, notes);
      return;
    }
    onDone();
    notification.open({
      key: 'asset-produce-built',
      placement: 'topRight',
      duration: notes.length ? 0 : 10,
      style: { width: 460 },
      message: `生产单已建好：${ids.length} 张（本批 ≈${res.board.planned_rows} 条额度）`,
      description: (
        <Space direction="vertical" size={2}>
          <Text style={{ fontSize: 12 }}>
            {channelOk
              ? '还没投板。要投就在 ④ 生产单页勾上点「投去 AI 出片」，出好的片子自己回 ⑤ 成片墙。'
              : `这批的投板渠道是「${res.board.channel}」，机器不自动投，请导出后手工投。`}
          </Text>
          {notes.slice(0, 6).map((nx, i) => (
            <Text key={i} type="warning" style={{ fontSize: 12 }}>
              {nx}
            </Text>
          ))}
          {notes.length > 6 && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              另有 {notes.length - 6} 条提醒没列出
            </Text>
          )}
        </Space>
      ),
    });
  };

  const submit = async (intent: 'dispatch' | 'build_only' = 'dispatch') => {
    setSubmitIntent(intent);
    if (!summaries.length) {
      message.warning('没有已过审的文案');
      return;
    }
    if (badCodes.length) {
      message.error(`钩子编号不对：${badCodes.slice(0, 3).join('、')}（必须是五位 0-9/A-Z，从取号工具 hook_id.py 拿，不能自己编）`);
      return;
    }
    if (dupCodes) {
      message.error('钩子编号重复：一个编号只能用在一条上');
      return;
    }
    if (usedCodes.length) {
      message.error(
        `这些编号已经被用掉了：${usedCodes.slice(0, 3).map((u) => u.code).join('、')}（一钩一号，回 hook_id.py 重新取号）`,
        8,
      );
      return;
    }
    // 批 O：参数行「按行配对对不齐」「全组合超 100 张」后端一定会 400，在这里先拦一句，
    // 别让人等完一次模型展开（几分钟）才看到红字。
    if (params.blocked) {
      message.error(params.blocked, 8);
      return;
    }
    if (needAutoCodes > 500) {
      message.error(`这批要 ${needAutoCodes} 个号，一次最多取 500 个：请分几批开单`, 8);
      return;
    }
    setBusy(true);
    giveUpRef.current = false;
    // 11-10 用户口径「钩子编号这个也自动取了，不要人工参与」：差额在**这一刻**向后端取号命令要。
    // 放在提交而不是开屏，是因为号一发就烧掉——打开看看又关掉不该烧掉一批号。
    // 取不到就停在这里（不建缺号单）：界面把原因说白，并给「我自己贴号」这一条退路。
    let finalCodes = codes;
    if (needAutoCodes > 0) {
      setAutoTakeError(null);
      try {
        const taken = await assetApi.takeHookCodes(needAutoCodes);
        // 与已预取/已手工贴的号去重：撞上了宁可少一个槽（后端会拿预取号补），
        // 也不要让两个槽位挂同一个号——一钩一号是导出与回收对账的地基。
        const seen = new Set([...codes, ...parkedCodes]);
        const fresh = (taken.codes || []).filter((c) => !seen.has(c));
        finalCodes = [...codes, ...fresh];
        // 落到状态里，别让"提交失败再点一次"变成第二次取号（号一发就烧掉，取两遍就是白废一批）
        if (fresh.length) setCodeText((prev) => (prev ? `${prev} ${fresh.join(' ')}` : fresh.join(' ')));
      } catch (e) {
        setAutoTakeError((e as Error).message || '取号命令没回话');
        setCodesManualOpen(true);
        setBusy(false);
        message.error('自动取号没成功，这批还没建单（原因见「钩子编号」那一栏）', 8);
        return;
      }
    }
    try {
      // A′（2026-11-08 定稿）：跨人确认改**会话级一次性**——同一条候选本会话确认过一次
      // （sessionStorage 记账）就不再弹；换会话/新候选仍会问那一句（知情不能省）。
      // 谁投账算谁（生产单记实际投产人，候选过审人进 strict 审计）。
      const crossIds = summaries
        .filter((s) => s.reviewed_by && s.reviewed_by !== currentUserId)
        .map((s) => s.id);
      const allRemembered =
        crossIds.length > 0 && crossIds.every((id) => sessionStorage.getItem(`xowner:${id}`) === '1');
      const markRemembered = () => crossIds.forEach((id) => sessionStorage.setItem(`xowner:${id}`, '1'));
      const doProduce = (confirmed: boolean) =>
        assetApi.produce({
          summary_ids: summaries.map((s) => s.id),
          n,
          board_total: boardTotal,
          accounts,
          recommended_title_count: titleCount,
          board_tag: boardTag || undefined,
          card_asset_ids: cardIds.length ? cardIds : undefined,
          drama_abbr: dramaAbbr.trim() || undefined,
          hook_codes: finalCodes.length ? finalCodes : undefined,
          expand,
          waive_reason: waiveReason || undefined,
          waive_codes: waiveCodes.length ? waiveCodes : undefined,
          // 批 O/P：换皮参数扇出。没填任何值就**整个字段不传**（后端把空当不扇出，
          // 走今天完全同一条路径）；填了就三样一起给——values 是要换上的多值、
          // base 是公共原值、baseBySummary 是各篇自己认到的原值（后端按「逐篇优先」合并）。
          element_values: params.filled.length ? params.values : undefined,
          element_base: params.filled.length && Object.keys(params.base).length ? params.base : undefined,
          element_base_by_summary:
            params.filled.length && Object.keys(params.baseBySummary).length ? params.baseBySummary : undefined,
          element_mode: params.filled.length ? params.mode : undefined,
          async_mode: true,
          cross_person_confirm: confirmed || allRemembered || undefined,
        });
      const res = (allRemembered
        ? await doProduce(true)
        : await withCrossOwnerConfirm(async (confirmed) => {
            const r = await doProduce(confirmed);
            if (r && confirmed) markRemembered();
            return r;
          })) as AssetProduceResponse;
      if (!res) return; // 取消了「替他人投产」确认：什么都不做
      if (isAssetJobAck(res)) {
        // 叫一声让顶部横幅立刻登记这条活：人中途关窗后由横幅接住结果
        nudgeAssetJobBanner();
        setJobHint(res.message);
        const job = await waitForAssetJob(res.job_id, {
          onTick: (j) => {
            if (giveUpRef.current) return;
            const p = j.progress;
            setJobHint(
              `「${j.kind_label}」${j.status_label}` +
                (p?.done !== null && p?.done !== undefined && j.planned_units
                  ? `（已收敛 ${p.done}/${j.planned_units} 条）`
                  : '') +
                '——嫌慢可以关掉窗口，任务在后台照跑，跑完在顶部横幅和生产单列表里都能看到',
            );
          },
        });
        // 人已经关掉了窗口：结果交给顶部横幅接住，这里不再往已卸载的组件里塞状态
        if (giveUpRef.current) return;
        setJobHint(null);
        if (job.status !== 'succeeded') {
          message.error(job.error || `后台任务${job.status_label}，生产单没建成（任务号 ${job.id}）`, 8);
          return;
        }
        afterProduced(job.result as AssetProduceResponse, intent);
        return;
      }
      afterProduced(res, intent);
    } catch (e) {
      message.error((e as Error).message || '生成生产单失败');
    } finally {
      setBusy(false);
    }
  };

  // 关掉窗口 = 放弃在这里看结果，**不是**取消任务（后台照跑，横幅接住）。
  // 必须先置 giveUp 再关：轮询回来后靠它决定要不要往已卸载的组件里塞状态。
  const closeAndGiveUp = () => {
    giveUpRef.current = true;
    setJobHint(null);
    setResult(null);
    onClose();
  };

  return (
    <Modal
      open={open}
      title={`生成生产单：${summaries.length} 条过审文案`}
      // 11-10 用户口径「窗口宽度弄宽一点，不要点到旁边它就消失」：这一屏要摆换皮参数
      // （每个参数一行输入框），720 宽时标签＋输入框＋提示挤成三行；且误点遮罩会把一整屏参数丢掉。
      width="min(1120px, 94vw)"
      maskClosable={false}
      styles={{ body: { maxHeight: '72vh', overflowY: 'auto', paddingRight: 6 } }}
      onCancel={closeAndGiveUp}
      footer={
        result ? (
          <Space>
            <Button onClick={() => setResult(null)}>回到表单</Button>
            <Button type="primary" onClick={() => { setResult(null); onDone(); }}>
              去生产单列表
            </Button>
          </Space>
        ) : (
          <Space>
            <Button onClick={closeAndGiveUp}>{busy ? '先关掉，后台继续跑' : '取消'}</Button>
            {/* 11-10 用户口径「我投去了，生产出来了就给我看，不要搞这么复杂」：
                主按钮＝建完单直接进投板确认（窗口自己缩掉）；想先囤着不投走左边那颗。 */}
            <Button
              loading={busy && submitIntent === 'build_only'}
              disabled={busy && submitIntent !== 'build_only'}
              onClick={() => submit('build_only')}
            >
              只建单，先不投
            </Button>
            <Button
              type="primary"
              danger
              loading={busy && submitIntent === 'dispatch'}
              disabled={busy && submitIntent !== 'dispatch'}
              onClick={() => submit('dispatch')}
            >
              生成生产单并投去出片（{plannedRows} 条）
            </Button>
          </Space>
        )
      }
      destroyOnClose
    >
      {result ? (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Alert
            type={result.created ? 'success' : 'error'}
            showIcon
            message={`已生成 ${result.created} 张生产单，本批要投 ${result.board.planned_rows} 条（${result.board.tasks} 个任务 × 每个任务出 ${result.board.board_total} 版）`}
            description={result.message}
          />
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="投板渠道">
              {result.board.channel === 'wework_aivideo' ? '企微后台「创建AI视频」任务板' : result.board.channel}
            </Descriptions.Item>
            <Descriptions.Item label="板上的归属标记">{result.board.tag}</Descriptions.Item>
            <Descriptions.Item label="板上的建任务时间（系统生成）">{result.board.date}</Descriptions.Item>
            <Descriptions.Item label="出片规格">{result.board.output}</Descriptions.Item>
            <Descriptions.Item label="预计要跑几天">
              {result.capacity_hint.days} 天（{result.capacity_hint.account_count} 个号 × 每号每日 {result.capacity_hint.per_account_per_day} 条）
            </Descriptions.Item>
            {/* 用户口径 2026-11-09：暂不设上限/预警，只报数 */}
            <Descriptions.Item label="当日投板量">
              今天已排 {result.dispatch.today.board_rows} 条
            </Descriptions.Item>
            <Descriptions.Item label="今天投板情况" span={2}>
              已投出 {result.dispatch.today.dispatched} 条｜成功 {result.dispatch.today.succeeded} 条｜失败 {result.dispatch.today.failed} 条
              {result.dispatch.today.note && (
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                  {result.dispatch.today.note}
                </Text>
              )}
            </Descriptions.Item>
          </Descriptions>

          {/* 批 O/P（11-10）：这批是换皮扇出来的话必须在这里说清两件事——
              「多出来的张数不花模型钱」和「每张照样各占一个号、一条当天额度」。
              少说一句，一线就会以为 20 张＝花了 20 次的钱，或者以为不占额度。 */}
          {!!result.element_fanout?.rows_per_copy && (
            <Alert
              type="info"
              showIcon
              message={`这批按参数扇出：每条文案 ${result.element_fanout.rows_per_copy} 张（${
                result.element_fanout.mode === 'product' ? '全组合' : '按行配对'
              }）`}
              description={
                <Space direction="vertical" size={2}>
                  <Text style={{ fontSize: 12 }}>
                    {Object.entries(result.element_fanout.params || {})
                      .map(([label, vals]) => `${label} ${vals.length} 个（${vals.slice(0, 4).join('、')}${vals.length > 4 ? '…' : ''}）`)
                      .join('｜')}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    换词是在展开好的那份稿子上做的，多出来的张数不再花模型钱；但每张各占一个钩子编号、各吃一条当天额度。
                  </Text>
                  {(result.element_fanout.skipped || []).map((s, i) => (
                    <Text key={`${s.code}-${i}`} type="danger" style={{ fontSize: 12 }}>
                      {s.code}：这组词拼进句子后撞上高风险词 {s.words.join('、')}，那一条没建单（同批其它条照常建），改词再来一次
                    </Text>
                  ))}
                  {(result.element_fanout.notes || []).slice(0, 6).map((nx, i) => (
                    <Text key={i} type="warning" style={{ fontSize: 12 }}>
                      {nx}
                    </Text>
                  ))}
                  {(result.element_fanout.notes || []).length > 6 && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      另有 {result.element_fanout.notes!.length - 6} 条「其实没换动」的备注没列出（多是因为原稿里没认出那个值）
                    </Text>
                  )}
                </Space>
              }
            />
          )}

          {/* 11-10 一屏到底：批 I 那颗「投去出片」没了。现在主按钮就叫
              「生成生产单并投去出片」——建完当场关窗、把这批单直接顶进 ④ 的投板确认窗。
              还能走到这一屏只剩一种情况：一张都没建成（幂等复活除外），
              那就先照下面列的原因改，不用谈投。 */}

          {!!result.recheck_failed?.length && (
            <Alert
              type="warning"
              showIcon
              message={`${result.recheck_failed.length} 条在出生产单前的自动检查没通过（没生成单，钩子编号还能原号重投）`}
              description={
                <Space direction="vertical" size={2}>
                  {result.recheck_failed.slice(0, 8).map((f) => (
                    <Text key={f.summary_id} style={{ fontSize: 12 }}>
                      {f.code}：{f.problems.map((p) => p.message).join('；')}
                    </Text>
                  ))}
                </Space>
              }
            />
          )}
          {!!result.recheck_waived?.length && isAdmin && (
            <Alert
              type="info"
              showIcon
              message={`${result.recheck_waived.length} 条由管理员带理由放行（已留档，可抽查）`}
            />
          )}
          {!!result.drifted?.length && (
            <Alert
              type="error"
              showIcon
              message={`${result.drifted.length} 条正文对不上：展开后的提示词和过审文案不是同一条`}
              description={
                <Space direction="vertical" size={2}>
                  {result.drifted.slice(0, 8).map((d) => (
                    <Text key={`${d.summary_id}-${d.seq}`} style={{ fontSize: 12 }}>
                      {d.code} #{d.seq}：{d.reason || '对不上'}
                    </Text>
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    单子照常生成、没有偷偷丢掉，但别直接投——逐条改名或回审核台改文案。
                  </Text>
                </Space>
              }
            />
          )}
          {!!result.prompt_skeleton_gaps?.length && (
            <Alert
              type="warning"
              showIcon
              message={`${result.prompt_skeleton_gaps.length} 条缺十行模板必须有的行（只提醒不拦：缺「负面约束」会出怪片、缺「音频与字幕」会被加字幕）`}
              description={
                <Space direction="vertical" size={2}>
                  {result.prompt_skeleton_gaps.slice(0, 6).map((g, i) => (
                    <Text key={`${g.code}-${g.seq}-${i}`} style={{ fontSize: 12 }}>
                      {g.code} #{g.seq}：缺 {g.missing.join('、')}
                    </Text>
                  ))}
                </Space>
              }
            />
          )}
          {!!result.title_warnings?.length && (
            <Alert
              type="warning"
              showIcon
              message={`${result.title_warnings.length} 条推荐标题正文超预算（只提醒：单子已建好、不拦出生产单，请把标题改短再投）`}
              description={
                <Space direction="vertical" size={2}>
                  {result.title_warnings.slice(0, 8).map((w, i) => (
                    <Text key={`${w.asset_code}-${w.seq}-${i}`} style={{ fontSize: 12 }}>
                      {w.asset_code} #{w.seq}：「{w.title}」实测 {w.chars} 字 / 上限 {w.limit} 字
                    </Text>
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    报表/任务板的标题列只显示前 22 字（发布侧补 4 字【账号】前缀，正文 ≤18）：
                    超了的那条会被截断、回收改名对不上。
                  </Text>
                </Space>
              }
            />
          )}
          {!!result.cards?.length && (
            <Alert
              type={result.cards.some((c) => c.orientation === 'landscape') ? 'warning' : 'info'}
              showIcon
              message={`这批带上的角色卡 ${result.cards.length} 张（第 1 张＝板上的第 1 张图＝主形象）`}
              description={
                <Space direction="vertical" size={2}>
                  {result.cards.map((c, i) => (
                    <Text key={`${c.asset_id}-${i}`} style={{ fontSize: 12 }}>
                      {i + 1}. {c.code || (c.asset_id || '').slice(0, 8)}｜{c.hint}
                    </Text>
                  ))}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    导出任务文件时还会逐张核对能不能读到；画幅不合就现在回去换卡，别等投上板。
                  </Text>
                </Space>
              }
            />
          )}
          {!!result.warnings?.length && (
            <Alert
              type="info"
              showIcon
              message={`提醒 ${result.warnings.length} 条`}
              description={
                <Space direction="vertical" size={2}>
                  {result.warnings.slice(0, 10).map((w, i) => (
                    <Text key={i} style={{ fontSize: 12 }}>
                      {w}
                    </Text>
                  ))}
                </Space>
              }
            />
          )}
          <Table<AssetSummary>
            size="small"
            rowKey="id"
            dataSource={summaries}
            pagination={false}
            columns={[
              { title: '素材', dataIndex: 'asset_code', width: 110, render: (v?: string) => v || '-' },
              { title: '候选', key: 'seq', width: 70, render: (_, r) => `#${r.seq}${r.is_recommended ? ' 推荐' : ''}` },
              {
                title: '过审文案',
                dataIndex: 'text',
                render: (v: string) => (
                  <Paragraph
                    style={{ marginBottom: 0, fontSize: 12 }}
                    ellipsis={{ rows: 2, expandable: 'collapsible', symbol: (expanded: boolean) => (expanded ? '收起' : '展开') }}
                  >
                    {v}
                  </Paragraph>
                ),
              },
            ]}
          />
        </Space>
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {jobHint && (
            <Alert
              type="info"
              showIcon
              message={jobHint}
              description={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  在等模型逐条展开（一条几十秒）；重复点不会更快，关窗不取消任务。
                </Text>
              }
            />
          )}
          <Space wrap size={16}>
            <span>
              <Text>N 每条文案派生份数：</Text>
              <Input type="number" min={1} max={10} style={{ width: 80, marginLeft: 6 }} value={n} onChange={(e) => setN(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} />
            </span>
            <Tooltip title="板上的 total＝同一条提示词出几版（1..20）。和 N 是两回事，弄混会白花 N×total 的量">
              <span>
                <Text>每份出几版：</Text>
                <Input type="number" min={1} max={20} style={{ width: 80, marginLeft: 6 }} value={boardTotal} onChange={(e) => setBoardTotal(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} />
              </span>
            </Tooltip>
            <span>
              <Text>豆包号数（折算天数）：</Text>
              <Input type="number" min={1} max={50} style={{ width: 80, marginLeft: 6 }} value={accounts} onChange={(e) => setAccounts(Math.max(1, Number(e.target.value) || 1))} />
            </span>
            <Tooltip title="K＝这部剧发布账号的数量，决定推荐视频标题给几条（现在不再固定 5 条）">
              <span>
                <Text>推荐标题条数（K）：</Text>
                {/* 批 N（评审二·P2）：留空行为不说明＝每单都要人肉猜一次；placeholder 写明白 */}
                <Input
                  type="number"
                  min={1}
                  max={20}
                  style={{ width: 80, marginLeft: 6 }}
                  value={titleCount}
                  placeholder="留空＝按模板默认"
                  onChange={(e) => setTitleCount(e.target.value ? Number(e.target.value) : undefined)}
                />
              </span>
            </Tooltip>
          </Space>

          {/* 批 O（11-10 用户口径）：按原型摆参数项＋自动提原值＋每行可填多值 → 一次扇多条 */}
          <AssetProduceParams
            active={open}
            summaries={summaries}
            onChange={setParams}
            onRefetch={refetchLatest}
            refetching={refetching}
          />

          <div>
            {/* 11-10 用户口径「钩子编号这个也自动取了，不要人工参与」：
                这一屏不再有"贴号"这一步。号的两条来源都在后端：文案名下预取的那份
                （开单当场顶槽），加上**点提交那一刻**向取号命令现取的差额。
                ⚠️ 取号必须压在提交那一刻，不能开屏就取：号一发就烧掉，人只是打开看看
                又把窗关了，那几个号就白废了（原来那颗「代取 N 个号」就是这么烧号的）。 */}
            <Space wrap size={6}>
              <Text>钩子编号（本单共需 {needCodes} 个，自动取，不用你填）</Text>
              {parkedCodes.length > 0 && (
                <Tooltip title={`这些号是提前取好放在文案名下的（${parkedCodes.slice(0, 6).join('、')}${parkedCodes.length > 6 ? '…' : ''}）。开单时后端自动把它们顶到缺号的槽位上，顶掉就清空——一钩一号，不会重复投。`}>
                  <Tag color="purple">已预取 {parkedCodes.length} 个</Tag>
                </Tooltip>
              )}
              {needAutoCodes > 0 && <Tag color="blue">提交时自动取 {needAutoCodes} 个</Tag>}
              {codes.length > 0 && (
                <Tooltip
                  title={
                    autoTakeError
                      ? '这一格是你手工贴进来的号（自动取号没成才用得上）。五位编号，一钩一号。'
                      : '点「生成生产单」那一下向服务器取号命令拿到的号。号一发就烧掉：这批要是没建成，下次提交会沿用这几个号，不会再取一遍。'
                  }
                >
                  <Tag color={badCodes.length || dupCodes || usedCodes.length ? 'red' : 'green'}>
                    {autoTakeError ? `手工填 ${codes.length} 个` : `已备好 ${codes.length} 个号`}
                  </Tag>
                </Tooltip>
              )}
            </Space>
            {/* 自动取号没成时才把退路摆出来：先说清为什么，再给「我自己贴」和取号清单 */}
            {!!autoTakeError && (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 6 }}
                message={`自动取号没成功，这批先别建单：${autoTakeError}`}
                description={
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      缺号建出来的单导出内容带不上编号，回头补号要一张一张钉。管理员把服务器取号命令
                      （ASSET_HOOK_ID_CMD）配好，这里就能全自动。
                    </Text>
                    <Space size={8} wrap>
                      <Button size="small" type={codesManualOpen ? 'primary' : 'default'} onClick={() => setCodesManualOpen((v) => !v)}>
                        {codesManualOpen ? '收起手工贴号' : '我自己贴号'}
                      </Button>
                      <Button
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={() => {
                          const lines = [
                            `本单待取号 ${needAutoCodes} 个（${summaries.length} 条文案 × 每条 ${n} 份${fanoutRows > 1 ? ` × 换皮扇出 ${fanoutRows} 张` : ''}${parkedCodes.length ? `，另 ${parkedCodes.length} 个已预取` : ''}）`,
                            ...summaries.map((s) => `${s.asset_code || s.id.slice(0, 8)}｜${(s.text || '').slice(0, 40)}${s.hook_code ? `｜已预取 ${s.hook_code}` : ''}`),
                          ];
                          navigator.clipboard
                            .writeText(lines.join('\n'))
                            .then(() => message.success(`待取号清单已复制（${needAutoCodes} 个号），去服务器照着跑 hook_id.py`))
                            .catch(() => message.error('复制失败：浏览器没给剪贴板权限，请手动抄'));
                        }}
                      >
                        复制待取号清单（{needAutoCodes} 个）
                      </Button>
                    </Space>
                    {codesManualOpen && (
                      <Input.TextArea
                        rows={2}
                        placeholder="空格/逗号/换行分隔，如：7C0B1 7C0B2（五位编号，不能自己编）"
                        value={codeText}
                        onChange={(e) => setCodeText(e.target.value)}
                      />
                    )}
                  </Space>
                }
              />
            )}
            {!!usedCodes.length && (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 6 }}
                message={`${usedCodes.length} 个编号已经被用掉了，提交会被拦`}
                description={
                  <div style={{ fontSize: 12 }}>
                    {usedCodes.slice(0, 8).map((u) => (
                      <div key={u.code}>{u.code}（已钉在素材 {u.asset_code} 的第 {u.seq} 张单上）</div>
                    ))}
                    {usedCodes.length > 8 && <div>另有 {usedCodes.length - 8} 个没列出</div>}
                    <div>一钩一号：号一发就烧掉，作废的单也不复用，回 hook_id.py 重新取号再投产。</div>
                  </div>
                }
              />
            )}
          </div>

          <Space wrap>
            <Input placeholder="板上的归属标记（留空用默认）" style={{ width: 220 }} value={boardTag} onChange={(e) => setBoardTag(e.target.value)} />
            <Tooltip title="剧名缩写要用 NAS《剧名缩写表.json》里的，禁止临时造；留空标题降级为「编号·精简钩子」，偏差说明记缺剧缩。">
              <Input
                placeholder="剧名缩写（可选，如 救总裁）"
                style={{ width: 200 }}
                maxLength={12}
                value={dramaAbbr}
                onChange={(e) => setDramaAbbr(e.target.value)}
              />
            </Tooltip>
          </Space>

          <AssetCardPicker active={open} value={cardIds} onChange={setCardIds} batchId={batchId} />

          <Checkbox checked={expand} onChange={(e) => setExpand(e.target.checked)}>
            让 AI 按标准模板把文案展开成能直接投的提示词
          </Checkbox>
          {!expand && (
            <Alert type="warning" showIcon message="不展开就是没正文的单：上面只有过审文案本身，不能投板，导出也不带正文" />
          )}

          {isAdmin && (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Input.TextArea
                rows={2}
                placeholder="（仅管理员）自动检查没过仍要坚持出生产单时的放行理由——会逐条留档"
                value={waiveReason}
                onChange={(e) => setWaiveReason(e.target.value)}
              />
              {!!waiveCodes.length && (
                <>
                  <Text style={{ fontSize: 12 }}>上一次拦下的问题类型，这次放行哪几类（不勾的那类仍然拦着）：</Text>
                  <Checkbox.Group
                    value={waiveCodes}
                    onChange={(v) => setWaiveCodes(v as string[])}
                    options={waiveCodes.map((c) => ({ label: RECHECK_CODE_LABELS[c] || c, value: c }))}
                  />
                </>
              )}
            </Space>
          )}

          <Tooltip title="内容更长只能拆上/下集；视频时长上限只影响反推文案成本，与任务板无关">
            <Alert
              type="info"
              showIcon
              message={`出片恒 10.08s / 720×1280；本批 ${plannedRows} 条计入当日额度（≈120 条/日，只报数不拦）`}
            />
          </Tooltip>
          <MonoText>{summaries.map((s) => s.asset_code || s.id.slice(0, 8)).join(' · ')}</MonoText>
        </Space>
      )}
    </Modal>
  );
};

export default ProduceOrderModal;
