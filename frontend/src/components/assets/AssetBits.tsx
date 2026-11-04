import React from 'react';
import { Tag, Tooltip, Typography } from 'antd';
import {
  ASSET_STAGE_LABELS,
  ASSET_STATUS_LABELS,
  AUDIT_STATUS_LABELS,
  PRODUCTION_STATE_LABELS,
  STAGE_FIELDS,
} from '../../api/assets';
import type { AssetBudgetGate, AssetBudgetGateInfo, AssetItem, AssetStage, AssetStatus, AuditStatus, ProductionState } from '../../api/assets';

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
  summarizing: 'processing',
  awaiting_review: 'orange',
  ready_to_produce: 'green',
  producing: 'processing',
  composing: 'processing',
  ready: 'success',
  failed: 'error',
  archived: 'warning',
};

export const AssetStatusTag: React.FC<{ status: AssetStatus }> = ({ status }) => (
  <Tag color={ASSET_STATUS_COLOR[status] || 'default'}>{ASSET_STATUS_LABELS[status] || status}</Tag>
);

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
