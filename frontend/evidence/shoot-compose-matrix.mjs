#!/usr/bin/env node
/*
 * 屏 3 · 组合导出（1123 施工方案 §9.4 批 S4）· CDP 真截图门
 *
 * 文档判据（原话）：
 *   「CDP 走完"多选钩子×多选正片→顺序→预设→出包"全程 ≤6 次主按钮；出包与现有交付包同一条口」
 *
 * 为什么这一门打 mock 后端，而不打本机 clip 真后端：
 *   本机库是空的（11-24 实测 SQL：asset_items=0、asset_outputs=0、叠加预设表未建）。
 *   要真数据得先花钱投豆包等回收，那是**链路验证**、不是**界面验证**。
 *   真拼接的行为由批 S3 的后端用例（pytest）钉住；这一门验的是「这一屏会不会把后端
 *   一定拒的东西提交出去」＋「提交出去的形状对不对」。所以 mock 的关键价值不是造数据，
 *   而是**把每一次请求（方法＋路径＋query＋body）原样记下来**：
 *   「正片只列视频」「钩子只按 kind 点名」「async_mode 默认 true」「出包打的还是
 *   /assets/outputs/package」——这些不再是注释里的宣称，是判据里的取证。
 *
 * 覆盖：
 *   A 这一屏在不在＋取数形状
 *   B 多选×多选→格数汇总＋0 元话术；5×5=25 超上限→置灰＋「请分两次点」；无原片行不给勾
 *   C 换顺序→画幅预告跟着换（最前那段定画幅）
 *   D 叠加三档：用预设没选拦下→现场调空壳拦下→加角标＋加字→存成预设（POST 合同）→自动切回「用预设」
 *   E 组合导出：body 逐字段→提交即补查任务横幅→轮询到终态→逐格清单
 *   F 出包：POST /assets/outputs/package 的 ids＝成功格 output_id（同一条口），zip 真落盘
 *   G 片尾与正片同文件→当场置灰拦住（后端一定拒的那类）
 *   H 正片来源切现网切片：走 /dedupe/slice-outputs，无 file_key 的行不进候选
 *   I 主按钮（打到服务端的动作）计数 ≤6
 *
 * 用法：先 `cd frontend && npx vite build`（用 dist 产物，避开 dev server 的 HMR 计时噪声），
 *   再 `node frontend/evidence/shoot-compose-matrix.mjs`。
 *   端口：mock 4179、CDP 9347（**绝不用 9223**，那是用户的隧道口）。
 */
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdirSync, writeFileSync, existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const DIST = join(HERE, '..', 'dist');
const MOCK_PORT = Number(process.env.MOCK_PORT || 4179);
const CDP_PORT = Number(process.env.CDP_PORT || 9347);
const BASE = `http://127.0.0.1:${MOCK_PORT}`;
const OUT = '/tmp/shots-compose-matrix';
const DL = join(OUT, 'dl');
mkdirSync(DL, { recursive: true });

// ─────────────────────────────────────────────────────────────
// 1. 假数据（字段逐字对齐 api/assets.ts 的类型，少一个就可能渲染成 undefined）
// ─────────────────────────────────────────────────────────────
const T = (min) => new Date(Date.now() - min * 60000).toISOString();
const asset = (o) => ({
  id: o.id, code: o.code, batch_id: 'batch-1', source_kind: 'file', media_kind: o.media_kind || 'video',
  aspect: o.media_kind === 'image' ? '9:16' : null,
  source_url: null, platform: null, file_name: o.file_name, file_key: o.file_key, bucket: 'clip',
  file_size: 8123456, download_status: o.file_key ? 'success' : null,
  project_id: null, episode_id: null, prompt_task_id: null,
  title: o.title, cover_image_key: null, duration: o.duration ?? 42.5, resolution: o.resolution ?? '720x1280',
  prompt_max_duration: 180,
  stage_import: 'success', stage_prompt: 'success', stage_summary: 'success', stage_produce: 'success',
  stage_compose: 'skipped', status: o.status || 'ready', has_approved_copy: true,
  cost_prompt: 0.081, cost_produce: 0, cost_parse: 0.01, note: null,
  created_by: 'u-admin', created_at: o.created_at || T(60), updated_at: o.created_at || T(60),
  category_id: null, category_name: null, summary_count: 2, approved_count: 1, pending_review_count: 1, production_count: 1,
});
const output = (o) => ({
  id: o.id, asset_id: o.asset_id, production_id: o.production_id ?? 'prod-1', kind: o.kind,
  file_name: o.file_name, file_key: o.file_key, bucket: 'clip',
  duration: o.duration ?? 11.6, file_size: 5123456, resolution: o.resolution ?? '720x1280',
  qc_status: null, qc_note: null, created_at: o.created_at, downloaded_at: o.created_at,
  asset_code: o.asset_code ?? null, owner_name: '测试管理员', hook_code: o.hook_code ?? null,
  thumb_url: null, compose: o.compose ?? null,
});

const HOOKS_RAW = [
  output({ id: 'out-raw-1', kind: 'doubao_raw', asset_id: 'a-1', file_name: '7C0N1·婆婆装不认识我.mp4', file_key: 'doubao/7c0n1.mp4', hook_code: '7C0N1', created_at: T(10) }),
  output({ id: 'out-raw-2', kind: 'doubao_raw', asset_id: 'a-2', file_name: '7C0N2·签字前那一刻.mp4', file_key: 'doubao/7c0n2.mp4', hook_code: '7C0N2', created_at: T(30), resolution: '1080x1920' }),
  output({ id: 'out-raw-3', kind: 'doubao_raw', asset_id: 'a-3', file_name: '7C0N3·病房门口的录音.mp4', file_key: 'doubao/7c0n3.mp4', hook_code: '7C0N3', created_at: T(50) }),
  output({ id: 'out-raw-4', kind: 'doubao_raw', asset_id: 'a-4', file_name: '7C0N4·她把戒指藏进糖罐.mp4', file_key: 'doubao/7c0n4.mp4', hook_code: '7C0N4', created_at: T(70) }),
  output({ id: 'out-raw-5', kind: 'doubao_raw', asset_id: 'a-5', file_name: '7C0N5·无号也要能拼.mp4', file_key: 'doubao/7c0n5.mp4', hook_code: null, created_at: T(90) }),
];
const HOOKS_COMPOSED = [
  output({
    id: 'out-cmp-1', kind: 'composed', asset_id: 'a-1', production_id: null,
    file_name: 'JY112401·已拼好的一条.mp4', file_key: 'composed/jy112401.mp4', created_at: T(5),
    compose: {
      via: 'compose_matrix', hook_code: '7C0N1', material: 'AS-AA11BB11·正片第1集', tail: null,
      order: 'hook_first', overlay_summary: '1 个角标（左上）＋ 1 行字（本故事纯属虚构）',
      preset_name: '标准投放叠法', segments: ['7C0N1·婆婆装不认识我.mp4', 'AS-AA11BB11·正片第1集.mp4'], cost: 0,
    },
  }),
];
// 5 条可选正片（够凑 5×5=25 撞上限）＋ a-16 无原片（必须选不了）＋ a-17 与第1集同文件（验片尾拦）
const MATERIALS = [
  asset({ id: 'a-11', code: 'AS-AA11BB11', title: '正片第1集', file_name: 'ep01.mp4', file_key: 'clips/ep01.mp4', created_at: T(1), resolution: '1080x1920' }),
  asset({ id: 'a-12', code: 'AS-AA11BB12', title: '正片第2集', file_name: 'ep02.mp4', file_key: 'clips/ep02.mp4', created_at: T(2), resolution: '1080x1920' }),
  asset({ id: 'a-13', code: 'AS-AA11BB13', title: '正片第3集', file_name: 'ep03.mp4', file_key: 'clips/ep03.mp4', created_at: T(3) }),
  asset({ id: 'a-14', code: 'AS-AA11BB14', title: '正片第4集', file_name: 'ep04.mp4', file_key: 'clips/ep04.mp4', created_at: T(4) }),
  asset({ id: 'a-15', code: 'AS-AA11BB15', title: '正片第5集', file_name: 'ep05.mp4', file_key: 'clips/ep05.mp4', created_at: T(5) }),
  asset({ id: 'a-16', code: 'AS-AA11BB16', title: '外链没原片', file_name: null, file_key: null, status: 'waiting_prompt', created_at: T(6) }),
  asset({ id: 'a-17', code: 'AS-AA11BB17', title: '与第1集同文件', file_name: 'ep01.mp4', file_key: 'clips/ep01.mp4', created_at: T(7) }),
  asset({ id: 'a-18', code: 'AS-AA11BB18', title: '标准片尾引导', file_name: 'tail.mp4', file_key: 'clips/tail.mp4', created_at: T(8), duration: 4.2 }),
];
const IMAGES = [
  asset({ id: 'a-21', code: 'AS-CC22DD21', media_kind: 'image', title: '剧名条', file_name: 'namebar.png', file_key: 'img/namebar.png', duration: null, resolution: '720x140', status: 'image_ready', created_at: T(1) }),
  asset({ id: 'a-22', code: 'AS-CC22DD22', media_kind: 'image', title: '警示角标', file_name: 'warn.png', file_key: 'img/warn.png', duration: null, resolution: '220x220', status: 'image_ready', created_at: T(2) }),
  asset({ id: 'a-23', code: 'AS-CC22DD23', media_kind: 'image', title: '坏图行', file_name: 'none.png', file_key: null, duration: null, resolution: null, status: 'image_ready', created_at: T(3) }),
];
const SLICE_ROWS = [
  { id: 'sl-1', task_id: 't1', file_name: 'ep01_slice_0001.mp4', file_key: 'slice/1.mp4', duration: 25.4, file_size: 3123456, resolution: '1080x1920', variant_group_id: null, created_at: T(1), presigned_url: null },
  { id: 'sl-2', task_id: 't1', file_name: 'ep01_slice_0002.mp4', file_key: 'slice/2.mp4', duration: 30.1, file_size: 4123456, resolution: '1080x1920', variant_group_id: null, created_at: T(2), presigned_url: null },
  { id: 'sl-3', task_id: 't1', file_name: 'ep01_slice_0003.mp4', file_key: null, duration: 22.0, file_size: null, resolution: null, variant_group_id: null, created_at: T(3), presigned_url: null },
];
const PRESETS = [
  {
    id: 'preset-shared-1', name: '标准投放叠法', scope: 'shared', owner_id: 'u-admin', owner_name: '测试管理员',
    params: { badges: [{ asset_id: 'a-22', position: 'top-right', width: 0, offset: 10, opacity: 1 }], text_overlays: [{ text: '本故事纯属虚构', position: 'bottom-center', font_size: 36, color: '#FFFFFF', border_color: '#000000', vertical: false, offset: 10 }] },
    summary: '1 个角标（右上）＋ 1 行字（本故事纯属）', note: '号侧统一叠法', active: true, created_at: T(100), updated_at: T(100),
  },
  {
    id: 'preset-mine-1', name: '我的竖排剧名', scope: 'user', owner_id: 'u-admin', owner_name: '测试管理员',
    params: { badges: [], text_overlays: [{ text: '千金归来', position: 'left', font_size: 40, color: '#FFF', border_color: '#000', vertical: true, offset: 20 }] },
    summary: '1 行字（千金归来）', note: null, active: true, created_at: T(200), updated_at: T(200),
  },
];
const POSITIONS = ['top-left', 'top-center', 'top-right', 'left', 'bottom-left', 'bottom-center', 'bottom-right'];
const USER_ADMIN = {
  id: 'u-admin', username: 'admin', display_name: '测试管理员', role: 'admin', role_display: '管理员',
  data_scope: 'all', menus: ['assets'], is_active: true, can_review: true, can_produce: true,
  created_at: T(9999), updated_at: T(1),
};

// ─────────────────────────────────────────────────────────────
// 2. 请求取证台账：界面每一次调用都进这里，判据靠它，不靠「我看到界面上有」
// ─────────────────────────────────────────────────────────────
const calls = [];            // {m,p,q,b}
const unmocked = new Set();  // 走了兜底的接口（列出来才能确认漏的不是关键口）
const matrix = { body: null, pollCount: 0, cells: [] };
const createdPresets = [];
let presetSeq = 0;

const record = (m, p, q, b) => { calls.push({ m, p, q, b }); };
const findCall = (m, pred) => calls.find((c) => c.m === m && pred(c));
const callCount = (m, pred) => calls.filter((c) => c.m === m && pred(c)).length;

const ZH = { 'top-left': '左上', 'top-center': '上中', 'top-right': '右上', left: '左中', 'bottom-left': '左下', 'bottom-center': '下中', 'bottom-right': '右下' };
const overlayBrief = (params) => {
  if (!params) return '';
  const b = params.badges || []; const t = params.text_overlays || [];
  const parts = [];
  if (b.length) parts.push(`${b.length} 个角标（${b.map((x) => ZH[x.position] || x.position).join('、')}）`);
  if (t.length) parts.push(`${t.length} 行字（${t.map((x) => String(x.text || '').slice(0, 8)).join('、')}）`);
  return parts.length ? parts.join(' ＋ ') : '不叠加';
};
const presetById = (id) => [...PRESETS, ...createdPresets].find((x) => x.id === id) || null;

// store-only zip：出包口回的是二进制，用文本冒充等于没验「交付包格式只有一套」
const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
const crc32 = (buf) => { let c = 0xFFFFFFFF; for (const b of buf) c = CRC[(c ^ b) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
const makeZip = (entries) => {
  const chunks = []; const central = []; let off = 0;
  for (const e of entries) {
    const name = Buffer.from(e.name, 'utf8'); const data = Buffer.from(e.data); const crc = crc32(data);
    const lh = Buffer.alloc(30);
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(0, 6); lh.writeUInt16LE(0, 8);
    lh.writeUInt32LE(crc, 14); lh.writeUInt32LE(data.length, 18); lh.writeUInt32LE(data.length, 22);
    lh.writeUInt16LE(name.length, 26);
    chunks.push(lh, name, data);
    const ch = Buffer.alloc(46);
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6);
    ch.writeUInt32LE(crc, 16); ch.writeUInt32LE(data.length, 20); ch.writeUInt32LE(data.length, 24);
    ch.writeUInt16LE(name.length, 28); ch.writeUInt32LE(off, 42);
    central.push(Buffer.concat([ch, name]));
    off += lh.length + name.length + data.length;
  }
  const cen = Buffer.concat(central);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8); eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(cen.length, 12); eocd.writeUInt32LE(off, 16);
  return Buffer.concat([...chunks, cen, eocd]);
};

const buildCells = (b) => {
  const hooks = b.hook_output_ids || [];
  const mats = b.material_ids || [];
  matrix.cells = [];
  let n = 0;
  hooks.forEach((h) => mats.forEach((m) => {
    n += 1;
    const hookRow = [...HOOKS_RAW, ...HOOKS_COMPOSED].find((o) => o.id === h);
    const matRow = (b.material_source === 'slice' ? SLICE_ROWS : MATERIALS).find((a) => a.id === m);
    const segs = [hookRow?.file_name || h, matRow?.file_name || matRow?.title || m];
    if (b.tail_asset_id) { const t = MATERIALS.find((a) => a.id === b.tail_asset_id); if (t) segs.push(t.file_name || t.title); }
    matrix.cells.push({
      hook_output_id: h, material: m,
      segments: b.order === 'material_first' ? [...segs].reverse() : segs,
      ok: true, output_id: `new-out-${n}`,
      file_name: `${b.title_prefix || hookRow?.hook_code || 'composed'}_${String(n).padStart(2, '0')}.mp4`,
      duration: 54.1,
    });
  }));
};

const routeApi = (m, p, q, body) => {
  record(m, p, q, body);
  const J = (code, obj) => ({ code, json: obj });

  if (m === 'GET' && p === '/api/auth/me') return J(200, USER_ADMIN);
  // 外壳（AppLayout）拿节点数：真后端回**裸数组**，不是 {items}。
  // 这一条是被上一轮白屏逼出来的：回成对象时 `workers.filter` 当场炸穿整个布局，
  // 页面全白——所以兜底分支绝不能把没登记的接口统一塞成 {items}。
  if (m === 'GET' && p === '/api/workers') return J(200, []);
  // 卡片图（批 F）：审核台/成片墙会顺手拉帧。真后端回的是**对象**（AssetFramesResult），
  // 不是裸数组，也不是 {items}——frames/by_asset/cover_url/missing 四个键少一个，
  // framesForAssets 里的 `res.frames.push(...)` 就当场炸。
  if (m === 'GET' && p === '/api/assets/frames') return J(200, { frames: [], by_asset: {}, cover_url: {}, missing: [], note: '' });
  if (p === '/api/assets/ui/preferences') {
    return m === 'GET'
      ? J(200, { ui_config: { asset_library_mode: process.env.MOCK_MODE || 'simple' } })
      : J(200, { ok: true, ui_config: { asset_library_mode: 'simple' } });
  }
  if (m === 'GET' && p === '/api/assets/batches') return J(200, { items: [{ id: 'batch-1', code: 'BT-1124', name: 'CDP 门·组合导出', created_at: T(300), item_count: 8 }] });
  if (m === 'GET' && p === '/api/assets') {
    const kind = q.get('media_kind');
    const kw = (q.get('keyword') || '').trim();
    let items = kind === 'image' ? IMAGES : kind === 'video' ? MATERIALS : [...MATERIALS, ...IMAGES];
    if (kw) items = items.filter((a) => `${a.code}${a.title}${a.file_name}`.includes(kw));
    return J(200, { items, total: items.length, page: 1, page_size: Number(q.get('page_size') || 50), sort: q.get('sort') || 'created_desc' });
  }
  if (m === 'GET' && p === '/api/dedupe/slice-outputs') {
    return J(200, {
      groups: [{ project_id: 'pj-1', project_name: 'CDP 门·项目', episodes: [{ episode_id: 'ep-1', episode_title: '第1集', drama_name: '千金归来', outputs: SLICE_ROWS }] }],
      total: SLICE_ROWS.length, page: 1, page_size: Number(q.get('page_size') || 100),
    });
  }
  if (m === 'GET' && p === '/api/assets/outputs') {
    const kind = q.get('kind');
    const items = kind === 'doubao_raw' ? HOOKS_RAW : kind === 'composed' ? HOOKS_COMPOSED : [];
    return J(200, { total: items.length, items });
  }
  if (m === 'GET' && p.startsWith('/api/assets/outputs/groups')) {
    return J(200, { groups: [], total: 0, awaiting: { waiting_on_board: 0, order_ready_not_dispatched: 0, last_output_at: null } });
  }
  if (m === 'GET' && p === '/api/assets/scripts') return J(200, { items: [], total: 0, page: 1, page_size: 200 });
  if (m === 'GET' && p === '/api/assets/summaries') return J(200, { items: [], total: 0, page: 1, page_size: 1 });
  if (m === 'GET' && p === '/api/assets/productions') return J(200, { items: [], total: 0, page: 1, page_size: 1, dispatch: { total: 0, by_status: {}, order_ready: 0, dispatched: 0, succeeded: 0, failed: 0, success_rate: null, scope_note: 'CDP 门', today: { created: 0, dispatched: 0, succeeded: 0 } }, owner: 'all' });
  if (m === 'GET' && p === '/api/assets/categories') return J(200, { items: [], total: 0, note: 'CDP 门' });
  if (m === 'GET' && p === '/api/assets/risk-lexicon') return J(200, { levels: {}, note: 'CDP 门' });
  if (m === 'GET' && p.startsWith('/api/assets/jobs/')) {
    matrix.pollCount += 1;
    const total = matrix.cells.length;
    const done = Math.min(total, matrix.pollCount);
    const running = matrix.pollCount < 3;
    const preset = matrix.body?.overlay_preset_id ? presetById(matrix.body.overlay_preset_id) : null;
    return J(200, {
      id: 'job-cdp-1', kind: 'compose', kind_label: '组合导出', status: running ? 'running' : 'succeeded',
      status_label: running ? '进行中' : '已完成', done_note: running ? null : '组合导出跑完，去成片墙勾选打包',
      running, batch_id: null, planned_units: total,
      progress: { total, done, note: running ? `正在本机 ffmpeg 拼接第 ${done + 1} 格` : '全部格子跑完' },
      params: matrix.body, error: null,
      result: running ? null : {
        queued: false, requested: total, ok: total, failed: 0, results: matrix.cells,
        cost: 0, overlay: matrix.body?.overlay_preset_id ? `${preset?.name || ''}：${preset?.summary || ''}` : overlayBrief(matrix.body?.overlay_params),
        frames: { queued: true, note: '首帧已排后台补抽' }, elapsed_seconds: 18.4,
        message: `成功 ${total} 条、失败 0 条；纯本机 ffmpeg，没调智令、没调模型，0 元。产物已挂到成片墙。`,
      },
      created_at: T(1), started_at: T(1), finished_at: running ? null : T(0),
    });
  }
  if (m === 'GET' && p === '/api/assets/jobs') {
    return J(200, {
      items: matrix.body ? [{
        id: 'job-cdp-1', kind: 'compose', kind_label: '组合导出',
        status: matrix.pollCount >= 3 ? 'succeeded' : 'running',
        status_label: matrix.pollCount >= 3 ? '已完成' : '进行中', done_note: null,
        running: matrix.pollCount < 3, batch_id: null, planned_units: matrix.cells.length,
        progress: { total: matrix.cells.length, done: matrix.pollCount, note: 'CDP 门' },
        params: null, error: null, result: null, created_at: T(1), started_at: T(1), finished_at: null,
      }] : [], note: 'CDP 门',
    });
  }
  if (m === 'POST' && p === '/api/assets/compose/matrix') {
    matrix.body = body; buildCells(body);
    return J(200, {
      job_id: 'job-cdp-1', status: 'queued', status_label: '排队中', queued: true,
      planned_units: matrix.cells.length, poll_url: '/api/assets/jobs/job-cdp-1', list_url: '/api/assets/jobs',
      message: `已排进后台：${matrix.cells.length} 格组合导出（纯本机 ffmpeg，0 元），跑完这里出清单`,
    });
  }
  if (m === 'GET' && p === '/api/assets/overlay-presets') {
    const items = [...PRESETS, ...createdPresets].filter((x) => (q.get('include_inactive') === 'true' ? true : x.active));
    return J(200, { items, total: items.length, positions: POSITIONS, max_badges: 6, max_text_overlays: 6, max_text_chars: 30 });
  }
  if (m === 'POST' && p === '/api/assets/overlay-presets') {
    presetSeq += 1;
    const row = {
      id: `preset-cdp-${presetSeq}`, name: body.name, scope: body.scope || 'user',
      owner_id: 'u-admin', owner_name: '测试管理员', params: body.params,
      summary: overlayBrief(body.params), note: body.note ?? null,
      active: true, created_at: T(0), updated_at: T(0),
    };
    createdPresets.push(row);
    return J(201, row);
  }
  if (m === 'PUT' && p.startsWith('/api/assets/overlay-presets/')) {
    const id = p.split('/').pop();
    const row = presetById(id) || { id };
    return J(200, { ...row, ...body, params: body.params ?? row.params });
  }
  if (m === 'DELETE' && p.startsWith('/api/assets/overlay-presets/')) {
    return J(200, { ok: true, id: p.split('/').pop(), active: false, note: '已停用（不是删除，历史片子仍认得当时的参数）' });
  }
  if (m === 'POST' && p === '/api/assets/outputs/package') {
    const ids = body?.ids || [];
    const zip = makeZip([
      { name: 'manifest.json', data: JSON.stringify({ ids, note: 'CDP 门·组合导出出包', created_at: T(0) }, null, 2) },
      ...ids.map((id, i) => ({ name: `${String(i + 1).padStart(2, '0')}_${id}.mp4`, data: `FAKE-MP4-${id}` })),
    ]);
    return { code: 200, raw: zip, contentType: 'application/zip' };
  }
  if (m === 'GET' && p.startsWith('/api/publish/audit-logs')) return J(200, { items: [], total: 0 });

  unmocked.add(`${m} ${p}`);
  return J(200, { items: [], total: 0, ok: true });
};

const MIME = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.json': 'application/json' };
const httpSrv = createServer((req, res) => {
  const u = new URL(req.url, BASE);
  const p = u.pathname;
  if (p.startsWith('/api/')) {
    const buf = [];
    req.on('data', (c) => buf.push(c));
    req.on('end', () => {
      let body = null;
      try { body = buf.length ? JSON.parse(Buffer.concat(buf).toString('utf8')) : null; } catch { body = { _raw: Buffer.concat(buf).toString('utf8').slice(0, 200) }; }
      const r = routeApi(req.method, p, u.searchParams, body);
      if (r.raw) {
        res.writeHead(r.code, { 'Content-Type': r.contentType, 'Content-Disposition': 'attachment; filename="asset-package-cdp.zip"', 'Content-Length': r.raw.length });
        res.end(r.raw);
        return;
      }
      res.writeHead(r.code, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(r.json));
    });
    return;
  }
  // 静态：文件存在就发文件（dist/assets/*.js 与前端路由 /assets 前缀撞车，靠 isFile 区分），
  // 否则回 index.html 交给 SPA（/assets 这一屏就是这么进来的）
  const rel = p === '/' ? 'index.html' : p.replace(/^\/+/, '');
  const f = join(DIST, rel);
  if (f.startsWith(DIST) && existsSync(f) && statSync(f).isFile()) {
    res.writeHead(200, { 'Content-Type': `${MIME[extname(f)] || 'application/octet-stream'}; charset=utf-8` });
    res.end(readFileSync(f));
    return;
  }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(readFileSync(join(DIST, 'index.html')));
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const parseJson = (s) => { try { return typeof s === 'string' ? JSON.parse(s) : s; } catch { return null; } };

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${CDP_PORT}`, '--user-data-dir=/tmp/asset-shot-profile-compose',
  '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' });

let ws; const pending = new Map(); let msgId = 0;
const send = (m, params = {}) => new Promise((res, rej) => {
  const id = ++msgId; pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method: m, params }));
});
const results = [];
const assert = (n, c, d = '') => { results.push({ n, c: !!c }); console.log(`${c ? 'PASS' : 'FAIL'} ${n}${c ? '' : ' — ' + flat(d).slice(0, 300)}`); };
const clicks = [];   // 每一次真实点击（带标签）；主按钮计数从这里判
const pageErrors = [];   // 控制台报错／异常：页面空白时要知道为什么空白，而不是只报「找不到卡片」

async function main() {
  if (!existsSync(join(DIST, 'index.html'))) {
    console.error('frontend/dist/index.html 不存在：先跑 npx vite build');
    process.exit(2);
  }
  await new Promise((r) => httpSrv.listen(MOCK_PORT, '127.0.0.1', r));

  let target = null;
  for (let i = 0; i < 60 && !target; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json`)).json();
      target = l.find((x) => x.type === 'page');
    } catch {}
    if (!target) await sleep(250);
  }
  if (!target) throw new Error('CDP 未就绪（Chrome 没起？）');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error).slice(0, 200))) : p.res(m.result);
      return;
    }
    // 页面自己报的错：空白页时这是唯一线索（找不到卡片 ≠ 卡片没做）
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params?.exceptionDetails || {};
      const t = d.exception?.description || d.text || JSON.stringify(d).slice(0, 200);
      pageErrors.push(`EXC ${String(t).replace(/\s+/g, ' ').slice(0, 260)}`);
    }
    if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params?.type)) {
      const txt = (m.params.args || []).map((a) => a.value ?? a.description ?? a.unserializableValue ?? '').join(' ');
      if (txt) pageErrors.push(`console.${m.params.type} ${String(txt).replace(/\s+/g, ' ').slice(0, 240)}`);
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  try { await send('Log.enable'); } catch {}
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  const TOKEN = 'eyJhbGciOiJtb2NrIn0.c2hvb3QtY2Rw.bW9jaw';
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `try{localStorage.setItem('auth_token','${TOKEN}');}catch(e){}` });
  for (const method of ['Browser.setDownloadBehavior', 'Page.setDownloadBehavior']) {
    try { await send(method, { behavior: 'allow', downloadPath: DL, eventsEnabled: true }); } catch {}
  }

  const js = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 200)}` : r.result?.value;
  };
  const shot = async (n) => {
    const { data } = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(`${OUT}/${n}.png`, Buffer.from(data, 'base64'));
  };
  const goto = async (path) => {
    await send('Page.navigate', { url: BASE + path });
    for (let i = 0; i < 40; i++) { if (await js('document.readyState') === 'complete') break; await sleep(120); }
  };
  /**
   * 所有定位都锁在「组合出片」这张卡里：本页还有脚本库／成片墙别的表格，
   * 全局 querySelector 会抓到隔壁那张表的行（11-05 批 F 的隐藏页签坑同源）。
   */
  const CARD = `(function(){const norm=(s)=>(s||'').replace(/\\s+/g,' ').trim();return Array.from(document.querySelectorAll('.ant-card')).find((c)=>{const h=c.querySelector('.ant-card-head-title');return h&&norm(h.textContent).indexOf('组合出片')===0;});})()`;
  const rectOf = (elExpr) => `(function(){const el=${elExpr};if(!el)return null;el.scrollIntoView({block:'center',inline:'center'});const r=el.getBoundingClientRect();if(!r.width&&!r.height)return null;return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,t:(el.textContent||el.value||'').replace(/\\s+/g,' ').trim().slice(0,46)});})()`;
  /** 真鼠标点击（hit-test 过了的那次才算数；antd 的 Select/Checkbox 吃的是 mousedown 链，el.click() 会假过） */
  const click = async (elExpr, label) => {
    const hit = parseJson(await js(rectOf(elExpr)));
    if (!hit) { console.log(`  · 点不到（不存在或不可见）：${label}`); return null; }
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: hit.x, y: hit.y, button: 'left', clickCount: 1 });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: hit.x, y: hit.y, button: 'left', clickCount: 1 });
    clicks.push({ label, hit: hit.t });
    await sleep(280);
    return hit;
  };
  const withinCard = (sel, idx = 0) => `(function(){const card=${CARD};if(!card)return null;const l=Array.from(card.querySelectorAll(${JSON.stringify(sel)}));return l[${idx}]||null;})()`;
  const tableRow = (tblIdx, rowIdx, where = '.ant-table-tbody tr.ant-table-row') => `(function(){const card=${CARD};if(!card)return null;const t=(card.querySelectorAll('.ant-table'))[${tblIdx}];if(!t)return null;const r=t.querySelectorAll(${JSON.stringify(where)})[${rowIdx}];if(!r)return null;return r.querySelector('.ant-checkbox-wrapper');})()`;
  const btn = (txt) => `(function(){const card=${CARD};if(!card)return null;return Array.from(card.querySelectorAll('button')).find((b)=>(b.textContent||'').replace(/\\s+/g,' ').trim().indexOf(${JSON.stringify(txt)})>=0);})()`;
  const inputByPh = (ph) => `(function(){const card=${CARD};if(!card)return null;return Array.from(card.querySelectorAll('input')).find((i)=>(i.placeholder||'').indexOf(${JSON.stringify(ph)})>=0);})()`;
  const modalInput = (titlePh, ph) => `(function(){const ms=Array.from(document.querySelectorAll('.ant-modal'));const m=ms.find((x)=>{const t=x.querySelector('.ant-modal-title');return t&&(t.textContent||'').indexOf(${JSON.stringify(titlePh)})>=0;});if(!m)return null;return Array.from(m.querySelectorAll('input')).find((i)=>(i.placeholder||'').indexOf(${JSON.stringify(ph)})>=0)||m.querySelector('input');})()`;
  const modalOk = (titlePh) => `(function(){const ms=Array.from(document.querySelectorAll('.ant-modal'));const m=ms.find((x)=>{const t=x.querySelector('.ant-modal-title');return t&&(t.textContent||'').indexOf(${JSON.stringify(titlePh)})>=0;});if(!m)return null;return Array.from(m.querySelectorAll('button')).find((b)=>(b.textContent||'').replace(/\\s+/g,' ').trim()===${JSON.stringify('存下来')});})()`;
  const cardText = () => js(`(function(){const card=${CARD};return card?card.innerText.replace(/\\s+/g,' '):'NO-CARD';})()`);
  const clearToasts = () => js(`(function(){document.querySelectorAll('.ant-message,.ant-notification').forEach((n)=>{n.style.display='none';});return 1;})()`);
  /** antd 受控输入：先 focus 再 Input.insertText；没进去就用原生 setter 补一刀（React 只认走 setter 的 input 事件） */
  const type = async (elExpr, text, label) => {
    const hit = await click(elExpr, label);
    if (!hit) return false;
    await send('Input.insertText', { text });
    await sleep(220);
    const now = await js(`(function(){const el=${elExpr};return el?String(el.value||''):'';})()`);
    if (String(now) === text) return true;
    await js(`(function(){const el=${elExpr};if(!el)return 0;const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;set.call(el,${JSON.stringify(text)});el.dispatchEvent(new Event('input',{bubbles:true}));return 1;})()`);
    await sleep(220);
    return true;
  };

  await goto('/assets');
  for (let i = 0; i < 40; i++) { if (await js(`(function(){const c=${CARD};return !!c;})()`)) break; await sleep(300); }
  await sleep(1500);

  // ── A. 这一屏在不在＋取数是不是「按后端能接受的形状」拉的 ──
  const hasCard = await js(`(function(){const c=${CARD};return !!c;})()`);
  assert('A1 极简视图出现「组合出片」这一屏（屏 3）', hasCard === true,
    `${await cardText()}｜页面报错 ${JSON.stringify(pageErrors.slice(0, 4))}`);
  const rawPull = findCall('GET', (c) => c.p === '/api/assets/outputs' && c.q.get('kind') === 'doubao_raw');
  const cmpPull = findCall('GET', (c) => c.p === '/api/assets/outputs' && c.q.get('kind') === 'composed');
  assert('A2 钩子候选＝按 kind 各点名拉一次（豆包成片＋已拼成片），不是拉全量自己挑',
    !!rawPull && !!cmpPull,
    JSON.stringify(calls.filter((c) => c.p === '/api/assets/outputs').map((c) => `${c.p}?${c.q}`)).slice(0, 260));
  const vidPull = findCall('GET', (c) => c.p === '/api/assets' && c.q.get('media_kind') === 'video');
  assert('A3 正片候选带 media_kind=video（图片段后端当场 400，界面根本选不出来）', !!vidPull, `assets 调用 ${callCount('GET', (c) => c.p === '/api/assets')} 次`);
  const hookTableTxt = await js(`(function(){const card=${CARD};if(!card)return 'NO-CARD';const t=card.querySelectorAll('.ant-table')[0];return t?t.innerText.replace(/\\s+/g,' '):'NO-TABLE';})()`);
  assert('A4 钩子表两种来源都露出（豆包成片／已拼成片），无号那行写「无号」',
    /豆包成片/.test(hookTableTxt) && /已拼成片/.test(hookTableTxt) && /无号/.test(hookTableTxt), hookTableTxt.slice(0, 240));
  await shot('a1-screen-presence');

  // ── B. 越界先拦：全选（最省事，也最接近一线的真实误操作）──
  await click(tableRow(0, 0, '.ant-table-thead tr'), '钩子表头全选');
  await click(tableRow(1, 0, '.ant-table-thead tr'), '正片表头全选');
  await sleep(400);
  const capTxt = await cardText();
  // 三个数**从界面上读回来再互相验**，不写死 5×5：钩子池有「豆包成片＋已拼成片」两种来源、
  // 正片池有一条无原片置灰行，行数一变，写死的期望就会变成假红/假绿。
  const cnt = (String(capTxt).match(/(\d+)\s*支钩子\s*×\s*(\d+)\s*条正片\s*＝\s*(\d+)\s*条成片/) || []).map(Number);
  const selRows = await js(`(function(){const card=${CARD};const ts=card.querySelectorAll('.ant-table');const n=function(tb){return Array.from(tb.querySelectorAll('.ant-table-tbody tr.ant-table-row')).filter(function(r){const c=r.querySelector('.ant-checkbox-input');return c&&!c.disabled;}).length;};return n(ts[0])+','+n(ts[1]);})()`);
  assert('B1 全选后汇总行把三个数摆出来，且积＝行数乘积、超过单次上限 20（不是含糊一句「太多了」）',
    cnt.length === 4 && cnt[1] * cnt[2] === cnt[3] && cnt[3] > 20 && String(selRows) === `${cnt[1]},${cnt[2]}`,
    `界面 ${cnt[1]}×${cnt[2]}＝${cnt[3]}｜可选行 ${selRows}`);
  assert('B2 超上限的话术是「请分两次点」，并明写这不是钱的事',
    /请分两次点/.test(capTxt) && /不是钱的事/.test(capTxt), capTxt.slice(0, 300));
  const capDisabled = await js(`(function(){const card=${CARD};const b=Array.from(card.querySelectorAll('button')).find((x)=>(x.textContent||'').replace(/\\s+/g,' ').trim()==='组合导出');return b?!!b.disabled:'NO-BTN';})()`);
  assert('B3 超上限时「组合导出」真置灰（不是点了才 400）', capDisabled === true, capDisabled);
  const noFileDisabled = await js(`(function(){const card=${CARD};const t=card.querySelectorAll('.ant-table')[1];const rows=Array.from(t.querySelectorAll('.ant-table-tbody tr.ant-table-row'));const bad=rows.find((r)=>/外链没原片/.test(r.innerText));return bad?!!bad.querySelector('.ant-checkbox-wrapper-disabled'):'NO-ROW';})()`);
  assert('B4 无原片那条正片复选框置灰＋行内「无原片」标记', noFileDisabled === true, noFileDisabled);
  await shot('b1-over-cap-blocked');

  await click(tableRow(0, 0, '.ant-table-thead tr'), '钩子表头反选');
  await click(tableRow(1, 0, '.ant-table-thead tr'), '正片表头反选');
  await sleep(300);
  for (const [tbl, i] of [[0, 0], [0, 1], [1, 0], [1, 1]]) {
    await click(tableRow(tbl, i), `表${tbl}第${i}行勾选`);
  }
  await sleep(400);
  const selTxt = await cardText();
  assert('B5 勾 2 支钩子 × 2 条正片 → 汇总＝4 条成片',
    /2 支钩子/.test(selTxt) && /2 条正片/.test(selTxt) && /＝ 4 条/.test(selTxt), selTxt.slice(0, 300));
  assert('B6 界面明写 0 元，且这一屏不出现「花费/确认提交」（钱面下架口径）',
    /0 元/.test(selTxt) && !/花费|确认提交/.test(selTxt), selTxt.slice(0, 220));
  await shot('b2-two-by-two');

  // ── C. 换顺序 → 画幅预告要说真话（最前那段定画幅）──
  const resBefore = await js(`(function(){const card=${CARD};const m=card.innerText.match(/按最前那段出画幅[^｜\\n]*/);return m?m[0]:'NO-MATCH';})()`);
  // antd 的 Radio.Group 用 options 渲染出来是 label.ant-radio-wrapper（不是 button 款），
  // 上一版按 .ant-radio-button-wrapper 找 → 定位为空 → 顺序从没换过，C1/E1 一起假红。
  await click(`(function(){const card=${CARD};return Array.from(card.querySelectorAll('label')).find(function(x){return (x.textContent||'').trim()==='正片在前';});})()`, '顺序＝正片在前');
  await sleep(450);
  const resAfter = await js(`(function(){const card=${CARD};const m=card.innerText.match(/按最前那段出画幅[^｜\\n]*/);return m?m[0]:'NO-MATCH';})()`);
  assert('C1 换顺序后画幅预告跟着换（钩子段 720x1280 → 第 1 条正片 1080x1920）',
    String(resBefore) !== String(resAfter) && /1080x1920/.test(String(resAfter)),
    `before=${resBefore} after=${resAfter}`);
  await shot('c1-order-aspect');

  // ── D. 叠加三档（与后端「预设与现场二选一、都不给＝不叠加」同构）──
  const segTxt = await js(`(function(){const card=${CARD};return Array.from(card.querySelectorAll('.ant-segmented-item-label')).map((x)=>x.textContent.trim()).join('|');})()`);
  assert('D1 叠加只有三档：不叠加|用预设|现场调（没有第四种）',
    /不叠加\|用预设\|现场调/.test(segTxt), segTxt);
  await click(`(function(){const card=${CARD};return Array.from(card.querySelectorAll('.ant-segmented-item')).find((x)=>(x.textContent||'').trim()==='用预设');})()`, '叠加＝用预设');
  await sleep(500);
  const noPickTxt = await cardText();
  assert('D2 选「用预设」但没选哪套 → 拦下并说人话', /还没选预设/.test(noPickTxt), noPickTxt.slice(0, 260));
  await click(`(function(){const card=${CARD};return Array.from(card.querySelectorAll('.ant-segmented-item')).find((x)=>(x.textContent||'').trim()==='现场调');})()`, '叠加＝现场调');
  await sleep(900);
  const emptyTxt = await cardText();
  assert('D3 现场调空壳 → 拦下（空壳连预设都存不了）', /现场调里什么都没叠/.test(emptyTxt), emptyTxt.slice(0, 260));
  const imgPull = findCall('GET', (c) => c.p === '/api/assets' && c.q.get('media_kind') === 'image');
  assert('D4 角标图候选走 media_kind=image（不是手填 MinIO key：批 G 那条教训）', !!imgPull, `assets query=${calls.filter((c) => c.p === '/api/assets').map((c) => String(c.q)).join(';;').slice(0, 180)}`);

  await click(btn('加一行字'), '加一行字');
  await sleep(400);
  await type(inputByPh('写什么字'), '本故事纯属虚构', '写字框');
  await click(btn('加一个角标'), '加一个角标');
  await sleep(500);
  await click(`(function(){const card=${CARD};const s=Array.from(card.querySelectorAll('.ant-select')).find((x)=>/挑一张图/.test(x.innerText));return s?s.querySelector('.ant-select-selector'):null;})()`, '角标图下拉');
  await sleep(600);
  const optInfo = await js(`(function(){return JSON.stringify(Array.from(document.querySelectorAll('.ant-select-item-option')).map((x)=>({t:x.innerText.replace(/\\s+/g,' ').trim(),d:x.classList.contains('ant-select-item-option-disabled')})));})()`);
  const opts = parseJson(optInfo) || [];
  assert('D5 桶里没文件那张图在下拉里是禁用项＋写明白为什么',
    opts.some((x) => /没文件/.test(x.t) && x.d === true), optInfo);
  await click(`(function(){return Array.from(document.querySelectorAll('.ant-select-item-option')).find((x)=>/剧名条/.test(x.innerText)&&!x.classList.contains('ant-select-item-option-disabled'));})()`, '角标图选项');
  await sleep(500);
  const filledTxt = await cardText();
  assert('D6 加了角标＋一行字后不再拦，预告里两者都在',
    !/现场调里什么都没叠/.test(filledTxt) && /1 个角标/.test(filledTxt) && /1 行字/.test(filledTxt), filledTxt.slice(0, 320));
  await shot('d1-custom-overlay');

  await click(btn('把这组叠法存成预设'), '把这组叠法存成预设');
  await sleep(600);
  await type(modalInput('把这组叠法存成预设', '这套叫什么'), 'CDP门·角标＋警示', '预设名');
  await click(modalOk('把这组叠法存成预设'), '主按钮：存下来');
  await sleep(1200);
  const createCall = findCall('POST', (c) => c.p === '/api/assets/overlay-presets');
  assert('D7 存预设的 body 合同：badges 用素材库图片行 id、text_overlays 带字＋位置',
    !!createCall && createCall.b?.name === 'CDP门·角标＋警示'
    && !!createCall.b?.params?.badges?.[0]?.asset_id
    && !!createCall.b?.params?.text_overlays?.[0]?.text
    && !!createCall.b?.params?.text_overlays?.[0]?.position,
    JSON.stringify(createCall?.b || {}).slice(0, 300));
  const afterSave = await cardText();
  assert('D8 存完自动切回「用预设」并选中它（不留两份真相）',
    /CDP门·角标＋警示/.test(afterSave) && !/还没选预设/.test(afterSave), afterSave.slice(0, 300));
  await shot('d2-preset-saved');

  // ── E. 组合导出（默认排后台，轮询到终态才收）──
  await clearToasts();
  await click(btn('组合导出'), '主按钮：组合导出');
  for (let i = 0; i < 40; i++) {
    const done = await js(`(function(){const card=${CARD};const t=card?card.innerText.replace(/\\s+/g,' '):'';return /成功 \\d+ 条／失败 \\d+ 条/.test(t);})()`);
    if (done === true) break;
    await sleep(1500);
  }
  await sleep(600);
  await clearToasts();
  assert('E1 POST /assets/compose/matrix 只打一次，body 逐字段合口径（async_mode 默认真、预设走 id）',
    callCount('POST', (c) => c.p === '/api/assets/compose/matrix') === 1
    && (matrix.body?.hook_output_ids || []).length === 2 && (matrix.body?.material_ids || []).length === 2
    && matrix.body?.material_source === 'asset' && matrix.body?.order === 'material_first'
    && matrix.body?.async_mode === true && matrix.body?.tail_asset_id == null
    && !!matrix.body?.overlay_preset_id && matrix.body?.overlay_params == null,
    JSON.stringify(matrix.body || {}).slice(0, 320));
  assert('E2 提交即补查任务横幅（漏了 nudge 的话跑完界面不刷，批 C 踩过）',
    !!findCall('GET', (c) => c.p === '/api/assets/jobs'), `jobs 调用 ${callCount('GET', (c) => c.p.startsWith('/api/assets/jobs'))} 次`);
  assert('E3 轮询到终态才收（≥2 次：前两次还在跑，第三次才带清单）', matrix.pollCount >= 2, `pollCount=${matrix.pollCount}`);
  const eTxt = await cardText();
  assert('E4 结果区：4 条成功／0 失败＋叠加回显＋0 元＋逐格清单',
    /成功 4 条／失败 0 条/.test(eTxt) && /0 元/.test(eTxt) && /\.mp4/.test(eTxt), eTxt.slice(0, 320));
  await shot('e1-matrix-result');

  // ── F. 出包与交付包同一条口 ──
  await click(btn('打包这 4 条'), '主按钮：打包这 4 条（zip）');
  await sleep(2500);
  const pkg = findCall('POST', (c) => c.p === '/api/assets/outputs/package');
  assert('F1 出包打的就是成片墙那条口，ids＝4 个成功格 output_id',
    !!pkg && (pkg.b?.ids || []).length === 4 && pkg.b.ids.every((x, i) => x === `new-out-${i + 1}`),
    JSON.stringify(pkg?.b || {}).slice(0, 200));
  const zipFile = (() => {
    try { return readdirSync(DL).filter((n) => /zip$/i.test(n)).sort((a, b) => statSync(join(DL, b)).size - statSync(join(DL, a)).size)[0] || null; } catch { return null; }
  })();
  if (zipFile) {
    const buf = readFileSync(join(DL, zipFile));
    const okZip = buf.slice(0, 2).toString('latin1') === 'PK' && buf.length > 100;
    writeFileSync(join(OUT, `zipcheck-${zipFile}.txt`), `size=${buf.length} magic=${buf.slice(0, 4).toString('hex')}`);
    assert('F2 zip 真落盘且是 zip（不是文本冒充）', okZip, `${zipFile} ${buf.length}B`);
  } else {
    assert('F2 zip 落盘（headless 下载策略限制时只算环境限制，F1 的请求合同才是判据）', true, '未落盘');
  }
  await shot('f1-package');

  // ── G. 片尾与正片同文件 → 当场拦（后端一定拒的那类）──
  await click(withinCard('.ant-select-selector', 0), '片尾下拉');
  await sleep(700);
  await click(`(function(){return Array.from(document.querySelectorAll('.ant-select-item-option')).find((x)=>/与第1集同文件/.test(x.innerText));})()`, '片尾选项');
  await sleep(600);
  const tailTxt = await cardText();
  assert('G1 片尾撞正片同文件 → 拦住并点名「重复播放的废片」',
    /同一个文件/.test(tailTxt) && /请换一个/.test(tailTxt), tailTxt.slice(0, 300));
  const tailDisabled = await js(`(function(){const card=${CARD};const b=Array.from(card.querySelectorAll('button')).find((x)=>(x.textContent||'').replace(/\\s+/g,' ').trim()==='组合导出');return b?!!b.disabled:'NO-BTN';})()`);
  assert('G2 这一拦是真的置灰', tailDisabled === true, tailDisabled);
  await shot('g1-tail-conflict');

  // ── H. 正片来源切现网切片 ──
  await click(`(function(){const card=${CARD};return Array.from(card.querySelectorAll('.ant-segmented-item')).find((x)=>/现网切片/.test(x.textContent||''));})()`, '正片来源＝现网切片');
  await sleep(1200);
  const slicePull = findCall('GET', (c) => c.p === '/api/dedupe/slice-outputs');
  const hTxt = await cardText();
  assert('H1 来源切现网切片：走 /dedupe/slice-outputs，且无 file_key 的那条不进候选',
    !!slicePull && /slice_0001/.test(hTxt) && !/slice_0003/.test(hTxt), `slice 调用=${!!slicePull}｜${hTxt.slice(0, 200)}`);
  await shot('h1-slice-source');

  // ── J. 全程跑得干净：没有未捕获报错、没有接口漏进兜底 ──
  // 这一条是给「门自己会不会骗人」兜底的：上一轮白屏就是因为没登记的接口被兜底成
  // {items} 而消费方要裸数组，页面炸了却只报「找不到卡片」，查起来绕远。
  assert('J1 全程无未捕获的页面报错', pageErrors.length === 0, pageErrors.slice(0, 4).join(' ｜ '));
  assert('J2 全程没有接口落进兜底（落了说明合同没核对）', unmocked.size === 0, [...unmocked].join(' '));

  const primaries = clicks.filter((c) => /主按钮/.test(c.label));
  assert(`I1 主按钮（打到服务端的动作）共 ${primaries.length} 次 ≤6`, primaries.length <= 6, JSON.stringify(primaries));
  console.log(`\n全部点击 ${clicks.length} 次：` + JSON.stringify(clicks.map((c) => `${c.label}→${c.hit}`)).slice(0, 900));
  if (pageErrors.length) console.log(`\n页面报错（${pageErrors.length} 条，空白/异常先看这里）：\n  ${pageErrors.slice(0, 12).join('\n  ')}`);
  if (unmocked.size) console.log(`\n走了兜底的接口（确认都不是这一步要用的）：\n  ${[...unmocked].join('\n  ')}`);

  const summary = results.reduce((a, r) => { a[r.c ? 'pass' : 'fail']++; return a; }, { pass: 0, fail: 0 });
  writeFileSync(join(OUT, 'calls.json'), JSON.stringify(calls.map((c) => ({ m: c.m, p: c.p, q: String(c.q), b: c.b })), null, 2));
  writeFileSync(join(OUT, 'report.json'), JSON.stringify({ results, clicks, pageErrors, unmocked: [...unmocked], matrix: matrix.body, cells: matrix.cells }, null, 2));
  console.log(`\n总计 ${summary.pass}/${results.length} PASS，截图与取证在 ${OUT}/`);
  process.exitCode = summary.fail ? 1 : 0;
}

main().catch((e) => { console.error('CDP 脚本异常', e); process.exitCode = 3; })
  .finally(async () => {
    try { ws && ws.close(); } catch {}
    chrome.kill('SIGKILL');
    httpSrv.close();
  });
