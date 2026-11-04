import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Select, Tag, Tooltip } from 'antd';
import { assetApi } from '../../api/assets';
import type { AssetCategory, AssetCategoriesResult } from '../../api/assets';

/**
 * 钩子原型（A–G）共用的取数与展示件（11-04 拍板①）。
 *
 * 三个面板（素材列表 / 导入 / 审核台）都要同一个字典，所以取数集中在这里：
 * 字典就 7 行、0 元、纯读，进程内缓存 60 秒足够；抽屉保存后调
 * `invalidateAssetCategories()` 让下一次读打真接口，别让人改完词看不到。
 *
 * ⚠️ 名称**照《钩子模版换皮参数设定.docx》原名**（「原型 A：非人物件 / 动物开口说话…」），
 * 展示时才截成「原型 A」＋副标题；任何地方都别拿截短后的串去比 id 或当数据用。
 */

/** 列表筛选里代表「未分类」的取值（后端 `category_id=none` 认 none/unclassified/null） */
export const UNCLASSIFIED = 'none';

/** 模块级缓存：三个面板共用一份，避免每个面板 mount 都打一次 GET /assets/categories */
let cache: { at: number; data: AssetCategoriesResult } | null = null;
let inflight: Promise<AssetCategoriesResult> | null = null;
const TTL_MS = 60_000;
const listeners = new Set<() => void>();
/** 版本号：保存字典后 +1，正在用的面板靠它重拉（列表页的「未分类 N 条」要跟着变） */
let version = 0;

export const invalidateAssetCategories = (): void => {
  cache = null;
  version += 1;
  listeners.forEach((fn) => fn());
};

const fetchCategories = async (force: boolean): Promise<AssetCategoriesResult> => {
  if (!force && cache && Date.now() - cache.at < TTL_MS) return cache.data;
  if (inflight) return inflight;
  inflight = assetApi
    .listCategories()
    .then((data) => {
      cache = { at: Date.now(), data };
      return data;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
};

export interface UseAssetCategories {
  loading: boolean;
  /** 整张字典（含已下线的行；筛选要能用它，历史条目还挂在上面） */
  items: AssetCategory[];
  /** 只看在用的：点分类（新增引用）只允许挑这些，后端对下线行会 400 */
  activeItems: AssetCategory[];
  byId: Record<string, AssetCategory>;
  unclassified: { asset_count: number; copy_count: number };
  canEdit: boolean;
  note: string;
  reload: (force?: boolean) => Promise<void>;
}

export const useAssetCategories = (): UseAssetCategories => {
  const [data, setData] = useState<AssetCategoriesResult | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (force = false) => {
    setLoading(true);
    try {
      setData(await fetchCategories(force));
    } catch {
      // 字典读不到不该弹窗打断一线：下拉空着、标签回退成「未分类」就是可见的异常
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const run = (force: boolean) => {
      if (!alive) return;
      fetchCategories(force)
        .then((d) => alive && setData(d))
        .catch(() => alive && setData(null));
    };
    run(false);
    const bump = () => run(true);
    listeners.add(bump);
    return () => {
      alive = false;
      listeners.delete(bump);
    };
  }, []);

  const items = useMemo(() => data?.items || [], [data]);
  return {
    loading,
    items,
    activeItems: useMemo(() => items.filter((i) => i.active), [items]),
    byId: useMemo(() => Object.fromEntries(items.map((i) => [i.id, i])), [items]),
    unclassified: data?.unclassified || { asset_count: 0, copy_count: 0 },
    canEdit: !!data?.can_edit,
    note: data?.note || '',
    reload: load,
  };
};

/** 「原型 A：非人物件 / 动物开口说话（报恩·预警·神谕）」→ 主标签 + 副标题 */
export const splitCategoryName = (name: string): { short: string; topic: string } => {
  const i = name.indexOf('：');
  return i < 0
    ? { short: name, topic: '' }
    : { short: name.slice(0, i), topic: name.slice(i + 1).trim() };
};

/**
 * 行内标签：只显示「原型 A」这种短串（列表列宽放不下 docx 原名），
 * 鼠标点上去给全名＋钩法内核（原型 D 的合规提醒就来自 note，按拍板只做展示、不进闸门）。
 */
export const CategoryTag: React.FC<{ categoryId?: string | null; categoryName?: string | null }> = ({
  categoryId,
  categoryName,
}) => {
  if (!categoryId || !categoryName) {
    return (
      <Tooltip title="没点原型也能走完全链（拍板：不设为必填）。出文案的提示词模板不读这一列，所以不会自动归类。">
        <Tag style={{ marginRight: 0 }}>未分类</Tag>
      </Tooltip>
    );
  }
  const { short, topic } = splitCategoryName(categoryName);
  return (
    <Tooltip
      title={
        <CategoryTooltipBody title={categoryName} topic={topic} />
      }
    >
      <Tag color="geekblue" style={{ marginRight: 0 }}>
        {short}
      </Tag>
    </Tooltip>
  );
};

/** Tooltip 内容：全名 + 钩法内核（topic 为空就只显示全名） */
const CategoryTooltipBody: React.FC<{ title: string; topic: string }> = ({ title, topic }) => (
  <div style={{ maxWidth: 360 }}>
    <div>{title}</div>
    {topic && <div style={{ opacity: 0.85, marginTop: 4 }}>{topic}</div>}
  </div>
);

/**
 * 原型下拉（可搜索）。两种用法差一个参数：
 *  - **筛选**（`withUnclassified`）：带「未分类」项、也带已下线的行（历史条目筛得出来）；
 *  - **点分类**（默认）：只列在用行，清空＝清成未分类（后端 `category_id=null` 的语义）。
 */
export const CategorySelect: React.FC<{
  value?: string | null;
  onChange: (v?: string) => void;
  items: AssetCategory[];
  placeholder?: string;
  width?: number | string;
  size?: 'small' | 'middle' | 'large';
  withUnclassified?: boolean;
  disabled?: boolean;
  loading?: boolean;
}> = ({ value, onChange, items, placeholder, width = 180, size = 'middle', withUnclassified, disabled, loading }) => {
  const options = useMemo(() => {
    const opts: { value: string; label: string; disabled?: boolean }[] = items.map((c) => ({
      value: c.id,
      // 搜索按 docx 原名整串命中（一线按「偷听」「反转」这类词找）
      label: c.active ? c.name : `${c.name}（已下线）`,
    }));
    /**
     * 点分类那些口子只喂在用行，但条目上挂着的原型可能已经被管理员下线了——
     * 这时 Select 拿不到对应项，会把 id 原样显示成「cat-a」，一线根本认不出。
     * 所以补一个**禁用**项：显示得出全名，但不许再往上挂新条目（后端同样会 400 拦）。
     */
    if (value && !opts.some((o) => o.value === value)) {
      const hit = cache?.data.items.find((c) => c.id === value);
      if (hit) {
        opts.unshift({ value: hit.id, label: `${hit.name}（已下线，请另选）`, disabled: true });
      }
    }
    return withUnclassified ? [{ value: UNCLASSIFIED, label: '未分类（没点原型的）' }, ...opts] : opts;
  }, [items, withUnclassified, value]);

  return (
    <Select
      allowClear
      showSearch
      size={size}
      disabled={disabled}
      loading={loading}
      style={{ width }}
      placeholder={placeholder || (withUnclassified ? '钩子原型' : '选原型')}
      value={value || undefined}
      onChange={(v) => onChange(v == null ? undefined : String(v))}
      options={options}
      optionFilterProp="label"
      // docx 原名很长（30+ 字），默认下拉宽度会截断到认不出是哪一条
      dropdownStyle={{ minWidth: Math.max(260, typeof width === 'number' ? width : 260) }}
    />
  );
};
