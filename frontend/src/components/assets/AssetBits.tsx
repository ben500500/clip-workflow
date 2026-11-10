import React from 'react';
import { Popover, Tag, Tooltip, Typography } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import {
  ASSET_STAGE_LABELS,
  ASSET_STATUS_LABELS,
  AUDIT_STATUS_LABELS,
  PRODUCTION_STATE_LABELS,
  STAGE_FIELDS,
} from '../../api/assets';
import type { AssetBudgetGate, AssetBudgetGateInfo, AssetImageAspect, AssetItem, AssetMediaKind, AssetStage, AssetStatus, AuditStatus, ProductionState } from '../../api/assets';

const { Text } = Typography;

/** 金额统一两位小数；后端给的是 float（元），这里不做任何换算 */
export const yuan = (v: number | null | undefined): string =>
  v === null || v === undefined ? '-' : `${Number(v).toFixed(2)} 元`;

/**
 * 五位钩子编号：与后端 `svc.HOOK_CODE_RE`（`^[0-9A-Z]{5}$`）同一口径。
 * 号只能来自 hook_id.py 取号工具，这里**只做格式校验、不提供生成**——
 * 多人共享盘取号，前端自己编必撞码，后端也会直接 400「禁止手编」。
 */
export const HOOK_CODE_RE = /^[0-9A-Z]{5}$/;

export const parseHookCodes = (raw: string): string[] =>
  raw
    .split(/[\s,，、;；]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);

/** 时长未知必须显示「未知」：后端探不到回 null，写 0 会让人以为这是个 0 秒的空素材 */
export const durationText = (d: number | null | undefined): string =>
  d === null || d === undefined ? '未知' : `${Math.round(d)}s`;

const STAGE_COLOR: Record<AssetStage, string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  failed: 'error',
  skipped: 'warning',
};

const STAGE_ABBR: Record<string, string> = {
  stage_import: '导',
  stage_prompt: '读',
  stage_summary: '文',
  stage_produce: '单',
  stage_compose: '拼',
};

/** 五个阶段一排摆出来：一线问的是「谁卡在哪一步」，只看 status 答不了 */
export const StageTags: React.FC<{ asset: AssetItem }> = ({ asset }) => (
  <span>
    {STAGE_FIELDS.map(([field, label]) => {
      const value = asset[field] as AssetStage;
      return (
        <Tooltip key={field} title={`${label}：${ASSET_STAGE_LABELS[value] || value}`}>
          <Tag color={STAGE_COLOR[value] || 'default'} style={{ marginRight: 2 }}>
            {STAGE_ABBR[field]}
          </Tag>
        </Tooltip>
      );
    })}
  </span>
);

const ASSET_STATUS_COLOR: Record<AssetStatus, string> = {
  draft: 'default',
  importing: 'processing',
  waiting_prompt: 'default',
  analyzing: 'processing',
  /** 等出文案＝没人提交，给「灰」而不是「蓝（在跑）」，与等读视频同一档 */
  waiting_summary: 'default',
  summarizing: 'processing',
  awaiting_review: 'orange',
  ready_to_produce: 'green',
  producing: 'processing',
  composing: 'processing',
  ready: 'success',
  failed: 'error',
  archived: 'warning',
  /** 批 G：图片不是流水线的一环，是「躺在库里等人挑」的生产输入——给个跟四环都不同的色，一眼分得开 */
  image_ready: 'purple',
};

export const AssetStatusTag: React.FC<{ status: AssetStatus }> = ({ status }) => (
  <Tag color={ASSET_STATUS_COLOR[status] || 'default'}>{ASSET_STATUS_LABELS[status] || status}</Tag>
);

/**
 * 批 G：这行素材是不是图片（角色卡）。
 * 只看 `media_kind` 这一列，**不许拿扩展名判**——后端把扩展名分流收在入库那一次，
 * 之后所有环节都读这一列；前端再按扩展名判一次就是第七处口径。
 */
export const isImageAsset = (
  a: { media_kind?: AssetMediaKind | null } | null | undefined,
): boolean => a?.media_kind === 'image';

/**
 * 画幅短标签（挑卡列表 / 素材行用；投产响应里的整句 hint 后端已经写好，直接用那条）。
 * `ratio/orientation` 一律取后端算好的值，这里**只做显示措辞**：
 * 「成片画幅由角色卡宽高比决定」是实测口径，前端另拼一张比例表日后必打架。
 */
export const aspectShortText = (aspect?: AssetImageAspect | null): string => {
  if (!aspect || !aspect.ratio) return '画幅未知';
  switch (aspect.orientation) {
    case 'landscape':
      return `${aspect.ratio} 横版 → 出横屏`;
    case 'square':
      return `${aspect.ratio} 方图`;
    case 'portrait':
      return `${aspect.ratio} 竖屏`;
    default:
      // 后端量不到尺寸时 orientation=null（老数据或探失败）：只报比例，别替它猜方向
      return aspect.ratio;
  }
};

/** 批 G：视频 / 图片（角色卡）标记，列表与详情共用 */
export const MediaKindTag: React.FC<{ asset: AssetItem }> = ({ asset }) =>
  isImageAsset(asset) ? (
    <Tooltip
      title={
        `图片素材：只作生产输入（投产时当角色卡带上），不参与读视频、出文案、拼接，也不计费。` +
        `画幅：${aspectShortText(asset.aspect)}——成片画幅跟卡走，横版的卡会出横屏。`
      }
    >
      <Tag color="purple">角色卡</Tag>
    </Tooltip>
  ) : (
    <Tag>视频</Tag>
  );

/**
 * 11-09 用户拍板：横屏原片**全部收进来、界面上要标横屏**，而且「豆包生产的时候
 * 可能也需要进行这种横屏素材的」——所以这个徽标不只出现在素材列表，投产口那侧也要看得见。
 * 判据只读后端算好的 `aspect.orientation`（口径在 `_card_ratio_fields` 一处），前端不量尺寸；
 * 竖屏与量不到都不打标（满屏红标会把「横屏」这件事稀释成噪音）。
 */
export const LandscapeTag: React.FC<{
  aspect?: AssetImageAspect | null;
  /** 措辞：原片/成片用「横屏」，角色卡沿用「横版」（跟 aspectShortText 的口径一致） */
  label?: string;
}> = ({ aspect, label = '横屏' }) =>
  aspect?.orientation === 'landscape' ? (
    <Tooltip
      title={
        `量出来宽>高（${aspect.ratio || '比例未知'}${aspect.width && aspect.height ? ` · ${aspect.width}×${aspect.height}` : ''}）。` +
        '成片画幅实际由**角色卡**宽高比决定，提示词写 9:16 压不住一张横版卡；' +
        '这条素材要不要按横屏投产，挑卡/投产那一屏还能再核一次。'
      }
    >
      <Tag color="orange" style={{ fontSize: 11, marginInlineEnd: 0 }}>
        {label}
      </Tag>
    </Tooltip>
  ) : null;

const AUDIT_COLOR: Record<AuditStatus, string> = {
  pending: 'orange',
  approved: 'green',
  rejected: 'red',
  need_rewrite: 'gold',
  passed_edited: 'cyan',
};

export const AuditStatusTag: React.FC<{ status: AuditStatus }> = ({ status }) => (
  <Tag color={AUDIT_COLOR[status] || 'default'}>{AUDIT_STATUS_LABELS[status] || status}</Tag>
);

const PRODUCTION_COLOR: Record<ProductionState, string> = {
  order_ready: 'default',
  queued: 'blue',
  running: 'processing',
  awaiting_rewrite: 'gold',
  success: 'success',
  failed: 'error',
  cancelled: 'warning',
  skipped: 'warning',
  superseded: 'warning',
};

export const ProductionStateTag: React.FC<{ status: ProductionState }> = ({ status }) => (
  <Tag color={PRODUCTION_COLOR[status] || 'default'}>{PRODUCTION_STATE_LABELS[status] || status}</Tag>
);

/**
 * 闸门结论一行话：blocked / need_approval / ok。
 * 余额查不到时后端**仍放行**并带 note，必须把这句摆出来——只回一个 null 会让人以为有钱。
 */
export const GateLine: React.FC<{ gate: AssetBudgetGateInfo | null | undefined; fallbackLevel?: AssetBudgetGate }> = ({
  gate,
}) => {
  if (!gate) return null;
  // antd 的 Text type 只有 secondary/success/warning/danger，闸门 blocked 用 danger
  const tone = gate.level === 'blocked' ? 'danger' : gate.level === 'need_approval' ? 'warning' : 'success';
  return (
    <Text type={tone}>
      {gate.reason || (gate.allowed ? '预算够，可以提交' : '预算不够，先拦下')}
      {gate.note && <span style={{ marginLeft: 8, color: '#8c8c8c' }}>{gate.note}</span>}
    </Text>
  );
};

export const MonoText: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }}>
    {children}
  </Text>
);

/**
 * 11-10 用户口径「说明文字太长篇大论了，把它们全部缩起来放在浮窗里面显示，不然整个界面看起来很乱」：
 * 静态解释一律收进这枚「？」浮窗（`text` 传那段话），标题旁一个点，指上去才展开。
 * `children` 是点后面**仍然显示**的短标签（比如「（这份只投一次）」），不是浮窗内容。
 * **会拦住人的**话（风险词命中、条数对不齐、上限）不算说明，仍留在界面上。
 */
export const HelpDot: React.FC<{ text: React.ReactNode; children?: React.ReactNode }> = ({
  text,
  children,
}) => (
  <Popover
    trigger="hover"
    placement="rightTop"
    overlayStyle={{ maxWidth: 420 }}
    content={<div style={{ fontSize: 12, lineHeight: '20px' }}>{text}</div>}
  >
    {/* 收起面板／挑行这类"点整块都算"的容器里也会摆这枚点：不挡住冒泡的话，
        人只想看个说明，顺手把面板收了（11-10 「缩进浮窗」后 Collapse 标题旁就有一枚） */}
    <span
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
      onClick={(e) => e.stopPropagation()}
    >
      <QuestionCircleOutlined style={{ color: '#8c8c8c', fontSize: 12, cursor: 'help' }} />
      {children}
    </span>
  </Popover>
);

/** 风险词串 `词|block,词|warn` → 可读标签；block 拦过审/投产，warn 只预警 */
export const RiskTags: React.FC<{ riskHit: string | null | undefined }> = ({ riskHit }) => {
  if (!riskHit) return null;
  const parts = riskHit
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  return (
    <span>
      {parts.map((p, i) => {
        const [word, level] = p.split('|');
        return (
          <Tag key={`${p}-${i}`} color={level === 'block' ? 'red' : 'orange'}>
            {word}
            {level === 'block' ? '（不许用）' : '（要注意）'}
          </Tag>
        );
      })}
    </span>
  );
};
