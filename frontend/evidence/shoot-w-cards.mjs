#!/usr/bin/env node
/*
 * 批 W CDP 门（2026-11-25）：角色卡独立成库
 * 打法：本机栈 3000（backend 容器需带批 W 代码——docker cp 热补丁或镜像重建），
 * 数据已真迁（asset_cards 10 行、素材表 0 图行）。W1-W9 打界面，W11b 用 curl 直打
 * 后端口验指路（antd Upload 塞文件在 headless 下不稳定，别再试）。
 * 1) 顶栏「角色卡」抽屉：开得了、10 张卡带缩略图、改名/删除按钮在
 * 2) ② 素材与文案：类型筛选已撤、列表里没有角色卡行
 * 3) 投产弹窗挑卡器：选项来自卡库（AS-DC3422DC 等卡码出现在下拉里）
 * 4) 导入屏拒图：上传一张 png → failed 指路「角色卡」
 * 本机栈 3000 → 真后端 8001（数据已真迁：asset_cards 10 行）。全程只读+一次真传图（不入素材表）。
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = process.env.SHOOT_BASE || 'http://127.0.0.1:3000';
const OUT = '/tmp/shots-w';
mkdirSync(OUT, { recursive: true });
const TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_w', 'utf8').trim();
if (!TOK.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }

const CDP_PORT = 9349;
const USER_DATA = '/tmp/asset-shot-profile-w';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${USER_DATA}`,
  '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' });

let ws; const pending = new Map(); let msgId = 0;
const send = (m, p = {}) => new Promise((res, rej) => {
  const id = ++msgId; pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method: m, params: p }));
});
const results = [];
const assert = (n, c, d = '') => {
  results.push({ n, c: !!c });
  console.log(`${c ? 'PASS' : 'FAIL'} ${n}${c ? '' : ' — ' + flat(d).slice(0, 240)}`);
};
const js = async (e) => {
  const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
  return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 180)}` : r.result?.value;
};
const shot = async (n) => {
  try {
    const { data } = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(`${OUT}/${n}.png`, Buffer.from(data, 'base64'));
  } catch (e) { console.log(`WARN 截图 ${n} 失败：${String(e.message || e).slice(0, 120)}`); }
};
let injectId = null;
const setToken = async (tok) => {
  if (injectId) { try { await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: injectId }); } catch {} injectId = null; }
  const { identifier } = await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `try{localStorage.setItem('auth_token', ${JSON.stringify(tok)})}catch(e){}`,
  });
  injectId = identifier;
};
const goto = async (path) => {
  await send('Page.navigate', { url: BASE + path });
  for (let i = 0; i < 50; i++) { if ((await js('document.readyState')) === 'complete') break; await sleep(140); }
};
const segClick = (label) => js(`
  (() => { const el = Array.from(document.querySelectorAll('.ant-segmented-item'))
      .find((x) => x.textContent.trim() === ${JSON.stringify(label)} && x.offsetParent !== null);
    if (!el) return 'no-seg'; el.click(); return 'ok'; })()
`);
const clickTab = async (re) => {
  const hit = await js(`
    (() => { const rx = new RegExp(${JSON.stringify(re)});
      const list = Array.from(document.querySelectorAll('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn'))
        .filter((e) => e.offsetParent !== null && rx.test(e.innerText || ''));
      if (!list.length) return 'no-hit'; list[0].click(); return 'ok'; })()
  `);
  return hit;
};
const clickByRe = async (sel, re) => js(`
  (() => { const rx = new RegExp(${JSON.stringify(re)});
    const list = Array.from(document.querySelectorAll(${JSON.stringify(sel)}))
      .filter((e) => e.offsetParent !== null && rx.test(e.innerText || e.textContent || ''));
    if (!list.length) return 'no-hit:' + ${JSON.stringify(sel)};
    list[0].click(); return 'ok'; })()
`);

async function main() {
  let target = null;
  for (let i = 0; i < 60 && !target; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json`)).json();
      target = l.find((x) => x.type === 'page');
    } catch {}
    if (!target) await sleep(250);
  }
  if (!target) throw new Error('CDP 未就绪');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error).slice(0, 200))) : p.res(m.result);
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });

  await setToken(TOK);
  await goto('/assets');
  await sleep(2500);
  const boot = await js("document.body.innerText.replace(/\\s+/g,' ').trim().slice(0,200)");
  console.log('DEBUG boot=' + String(boot).slice(0, 160));

  // ── ① 顶栏角色卡抽屉 ──
  await segClick('完整'); await sleep(1500);
  const btn = await clickByRe('button', '^\\s*角色卡\\s*$');
  await sleep(1500);
  const drawer = await js(`
    (() => {
      const d = document.querySelector('.ant-drawer-open');
      if (!d) return { none: true };
      const t = d.innerText.replace(/\\s+/g, ' ');
      const imgs = Array.from(d.querySelectorAll('img')).filter((i) => i.naturalWidth > 0).length;
      return { none: false, title: (t.match(/角色卡库/) || [''])[0], total: (t.match(/共 (\\d+) 张/) || [])[1] || '?',
               imgs, renames: Array.from(d.querySelectorAll('button')).filter((b) => (b.innerText || '').trim() === '改名').length,
               rename: /改名/.test(t), del: /删/.test(t), upload: /拖图片进来或点击上传/.test(t) };
    })()
  `);
  assert('W1 顶栏「角色卡」按钮开得了抽屉', drawer && !drawer.none, JSON.stringify(drawer).slice(0, 200));
  assert('W2 抽屉标题「角色卡库」＋「共 10 张」', drawer && drawer.title === '角色卡库' && drawer.total === '10', `total=${drawer && drawer.total}`);
  // 老测试用 mock 传的图桶里没字节，真图只有 4~5 张；卡的总数按「改名」按钮数（每卡恰好一个）
  assert('W3 抽屉 10 张卡全部渲染（改名钮=10）＋真图 ≥4', drawer && drawer.renames === 10 && Number(drawer.imgs) >= 4, JSON.stringify(drawer).slice(0, 200));
  assert('W4 抽屉有改名/删除/上传入口', drawer && drawer.rename && drawer.del && drawer.upload, JSON.stringify(drawer).slice(0, 200));
  await shot('w1-drawer');

  // 抽屉里搜「奶爸」：q 过滤走真后端
  const search = await js(`
    (async () => {
      const d = document.querySelector('.ant-drawer-open');
      const inp = d.querySelector('input');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(inp, '奶爸');
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      await new Promise((r) => setTimeout(r, 1600));
      const cards = d.querySelectorAll('img').length;
      const t = d.innerText.replace(/\\s+/g, ' ');
      return { cards, total: (t.match(/共 (\\d+) 张/) || [])[1] || '?' };
    })()
  `);
  assert('W5 搜「奶爸」只剩 2 张（q 过滤走真后端）', search && Number(search.total) === 2 && Number(search.cards) === 2, JSON.stringify(search));
  const clearBtn = await js(`
    (() => { const d = document.querySelector('.ant-drawer-open');
      const c = d.querySelector('.ant-input-clear-icon'); if (c) c.click();
      return 'ok'; })()
  `);
  await sleep(1200);

  // ── ② 素材与文案 ──
  await js(`(() => { const c = document.querySelector('.ant-drawer-open .ant-drawer-close'); if (c) c.click(); return 'ok'; })()`);
  await sleep(1200);
  const t2 = await clickTab('素材与文案');
  await sleep(2200);
  const listState = await js(`
    (() => {
      const pane = document.querySelector('.ant-tabs-tabpane-active') || document.body;
      const t = pane.innerText.replace(/\\s+/g, ' ');
      const selects = Array.from(pane.querySelectorAll('.ant-select')).filter((x) => x.offsetParent !== null);
      const hasTypeFilter = selects.some((x) => (x.innerText || '').includes('类型'));
      const placeholders = selects.map((x) => x.getAttribute('aria-label') || '').join(',');
      const rows = pane.querySelectorAll('.ant-table-row').length;
      const cardRows = Array.from(pane.querySelectorAll('.ant-table-row')).filter((r) => /角色卡-|当角色卡用/.test(r.innerText || '')).length;
      const purple = pane.querySelectorAll('.ant-tag-purple').length;
      return { rows, cardRows, purple, hasTypeFilter, t: t.slice(0, 100) };
    })()
  `);
  assert('W6 ② 列表不再有「类型＝图片」筛选', listState && listState.hasTypeFilter === false, JSON.stringify(listState).slice(0, 160));
  assert('W7 ② 列表行里没有角色卡行', listState && Number(listState.cardRows) === 0, JSON.stringify(listState).slice(0, 160));
  await shot('w2-list');

  // ── ③ 极简 ② 投豆包：挑卡器选项来自卡库 ──
  // （完整模式 ② 勾素材先开「挑选弹窗」，勾的素材没过审文案时根本到不了投产弹窗；
  //   极简 ② 的挑卡器无条件渲染，直达）
  await segClick('极简'); await sleep(1800);
  await clickTab('投豆包'); await sleep(1500);
  let opened = 'init';
  for (let i = 0; i < 8 && opened !== 'ok'; i++) {
    opened = await js(`
      (() => { const sels = Array.from(document.querySelectorAll('.ant-select')).filter((x) => x.offsetParent !== null);
        const sel = sels.find((x) => /挑卡|角色卡/.test(x.innerText || ''));
        if (!sel) return 'no-select:' + sels.length;
        const inner = sel.querySelector('.ant-select-selector') || sel;
        ['mousedown','mouseup','click'].forEach((k) => inner.dispatchEvent(new MouseEvent(k, { bubbles: true, cancelable: true, view: window })));
        return 'ok'; })()
    `);
    if (opened !== 'ok') await sleep(800);
  }
  assert('W8 极简 ② 找得到挑卡 Select', opened === 'ok', opened);
  await sleep(1000);
  const optState = await js(`
    (() => {
      const dd = document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
      if (!dd) return { open: false };
      const t = dd.innerText.replace(/\\s+/g, ' ');
      const opts = dd.querySelectorAll('.ant-select-item-option').length;
      return { open: true, opts, sample: t.slice(0, 90), fromCards: /角色卡|奶爸|萌宝/.test(t) };
    })()
  `);
  console.log('DEBUG w9 opt=' + JSON.stringify(optState).slice(0, 160));
  assert('W9 挑卡下拉选项来自卡库（卡名出现在选项里）', optState && optState.open && Number(optState.opts) >= 4 && optState.fromCards, JSON.stringify(optState).slice(0, 200));
  await shot('w3-picker');
  // 收起下拉（Esc）
  await js(`(() => { document.activeElement && document.activeElement.blur(); return 'ok'; })()`);
  await sleep(600);

  // ── ④ 导入屏拒图 ──
  await segClick('完整'); await sleep(1500);
  await clickTab('导入'); await sleep(1500);
  await sleep(1500);
  const up = await js(`
    (async () => {
      const pane = document.querySelector('.ant-tabs-tabpane-active');
      const inp = pane.querySelector('input[type=file]');
      if (!inp) return 'no-file-input';
      return 'has-input';
    })()
  `);
  assert('W10 导入屏有上传口', up === 'has-input', up);
  // UI 只验两件静态事实：accept 只收视频 + 提示文案指路「角色卡」
  await clickByRe('.ant-tabs-tabpane-active .ant-radio-button-wrapper, .ant-tabs-tabpane-active button', '文件上传');
  await sleep(1200);
  const uiHint = await js(`
    (() => { const pane = document.querySelector('.ant-tabs-tabpane-active');
      const inp = Array.from(pane.querySelectorAll('input[type=file]')).find((x) => (x.getAttribute('accept') || '').startsWith('video'));
      const t = pane.innerText.replace(/\\s+/g, ' ');
      return { accept: inp ? (inp.getAttribute('accept') || '') : '?',
               hint: /图片不再进素材库/.test(t) && /角色卡/.test(t) }; })()
  `);
  assert('W11a 导入屏 accept 只收视频＋提示指路角色卡', uiHint && String(uiHint.accept).startsWith('video') && uiHint.hint === true, JSON.stringify(uiHint));
  // 后端口径 curl 直打：图片进 upload/batch 必须落在 failed 且带指路（batch 不留空壳）
  const { execSync } = await import('node:child_process');
  const pngB64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  const tmpPng = '/tmp/w-gate-test.png';
  writeFileSync(tmpPng, Buffer.from(pngB64, 'base64'));
  const apiResp = JSON.parse(execSync(
    `curl -s -X POST http://127.0.0.1:8001/api/assets/upload/batch -H "Authorization: Bearer ${TOK}" -F "files=@${tmpPng};type=image/png"`,
    { encoding: 'utf8' },
  ));
  const redirectEntry = (apiResp.failed || []).find((f) => /图片不入素材库/.test(f.error || '') && /角色卡/.test(f.error || ''));
  assert('W11b 后端口收图→failed 指路角色卡（batch 不留空壳）',
    apiResp.items && apiResp.items.length === 0 && !!redirectEntry && apiResp.batch === null,
    JSON.stringify({ items: apiResp.items && apiResp.items.length, failed: apiResp.failed, batch: apiResp.batch }).slice(0, 220));
  await shot('w4-import-redirect');

  const pass = results.filter((r) => r.c).length;
  console.log(`\\n==== ${pass}/${results.length} PASS ====`);
  results.filter((r) => !r.c).forEach((r) => console.log('  FAIL ' + r.n));
}

main()
  .catch((e) => { console.error('ERROR', e); process.exitCode = 1; })
  .finally(() => { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); });
