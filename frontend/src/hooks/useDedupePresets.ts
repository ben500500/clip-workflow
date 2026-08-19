import { useEffect, useState, useCallback } from 'react';
import { dedupeApi, type DedupeFieldDef, type DedupePresetDef } from '../api/dedupe';
import {
  FALLBACK_DEDUPE_PRESETS,
  FALLBACK_DEDUPE_FIELDS,
  FALLBACK_DEDUPE_DEFAULTS,
  DEFAULT_DEDUPE_PRESET,
  DEDUPE_PRESETS_CACHE_KEY,
  DEDUPE_PRESETS_SOURCE_KEY,
} from '../utils/dedupePresets';

// 模块级请求去重：同一时间只发一个 presets 请求，后续调用共享该 Promise，避免页面内多个组件重复请求。
let inflight: Promise<unknown> | null = null;

/**
 * 去重配置单一来源化（Issue #252）——前端共享 hook。
 *
 * 从 GET /api/dedupe/presets 拉取档位列表 + 字段定义 + 每档默认参数，并缓存到
 * localStorage（后续页面直接读缓存，避免重复请求）。接口不可用/加载失败时回退到
 * 内置硬编码默认，不阻塞页面渲染。
 *
 * 返回：
 *  - presets：档位列表（value/label/desc），供各页面下拉统一渲染
 *  - fields ：字段定义（key/label/type/min/max/step/control），供 DedupeManualConfig 动态渲染
 *  - defaults：每档全量默认参数（引擎 DEDUPE_PRESETS 权威值）
 *  - loading：是否正在从接口拉取
 *  - fromRemote：是否来自接口（false 表示回退到本地默认）
 */
export function useDedupePresets() {
  const [presets, setPresets] = useState<DedupePresetDef[]>(() =>
    loadCachedPresets()
  );
  const [fields, setFields] = useState<DedupeFieldDef[]>(() =>
    loadCachedFields()
  );
  const [defaults, setDefaults] = useState<Record<string, Record<string, unknown>>>(() =>
    loadCachedDefaults()
  );
  const [loading, setLoading] = useState(false);
  const [fromRemote, setFromRemote] = useState(false);

  const applyData = useCallback((data: {
    presets?: DedupePresetDef[];
    fields?: DedupeFieldDef[];
    defaults?: Record<string, Record<string, unknown>>;
  }) => {
    if (data.presets && data.presets.length > 0) setPresets(data.presets);
    if (data.fields && data.fields.length > 0) setFields(data.fields);
    if (data.defaults && Object.keys(data.defaults).length > 0) setDefaults(data.defaults);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      // 并发去重：若已有进行中的请求则复用
      if (!inflight) {
        inflight = dedupeApi.getPresets().catch((e) => {
          inflight = null;
          throw e;
        });
      }
      const data = (await inflight) as Awaited<ReturnType<typeof dedupeApi.getPresets>>;
      inflight = null;
      applyData(data);
      setFromRemote(true);
      try {
        localStorage.setItem(DEDUPE_PRESETS_CACHE_KEY, JSON.stringify(data));
        localStorage.setItem(DEDUPE_PRESETS_SOURCE_KEY, 'remote');
      } catch {
        /* 存储失败忽略 */
      }
    } catch {
      // 向后兼容：接口不可用回退硬编码默认，不阻塞页面
      inflight = null;
      setFromRemote(false);
    } finally {
      setLoading(false);
    }
  }, [applyData]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    presets,
    fields,
    defaults,
    loading,
    fromRemote,
    refresh,
    /** 档位下拉选项（供 Select/Cascader 复用） */
    presetOptions: presets,
    /** 取某档位默认值（无档位时回退 DEFAULT_DEDUPE_PRESET） */
    getDefault: (preset?: string) =>
      defaults[preset || DEFAULT_DEDUPE_PRESET] || defaults[DEFAULT_DEDUPE_PRESET] || {},
  };
}

// ── localStorage 缓存读取（损坏时回退内置默认） ──
function loadCachedPresets(): DedupePresetDef[] {
  const data = readCache();
  if (data?.presets && data.presets.length > 0) return data.presets;
  return FALLBACK_DEDUPE_PRESETS;
}

function loadCachedFields(): DedupeFieldDef[] {
  const data = readCache();
  if (data?.fields && data.fields.length > 0) return data.fields;
  return FALLBACK_DEDUPE_FIELDS;
}

function loadCachedDefaults(): Record<string, Record<string, unknown>> {
  const data = readCache();
  if (data?.defaults && Object.keys(data.defaults).length > 0) return data.defaults;
  return FALLBACK_DEDUPE_DEFAULTS;
}

function readCache(): { presets?: DedupePresetDef[]; fields?: DedupeFieldDef[]; defaults?: Record<string, Record<string, unknown>> } | null {
  try {
    const raw = localStorage.getItem(DEDUPE_PRESETS_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed || null;
  } catch {
    return null;
  }
}

export default useDedupePresets;
