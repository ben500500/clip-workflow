#!/usr/bin/env node
/*
 * 批 X CDP 门（2026-11-25）：文案写入面打通
 * X1 UI 贴文案导入 → X2 极简脚本库出现「候选」标镜像行
 * X3 ③ 审核台把候选过审 → 镜像脚本进 carrier_status=approved（可投）
 * X4 极简送审的壳在 ③ 显形打「脚本稿」标且过得掉 → 过审后脚本可投
 * X5 壳在默认口径仍被藏（挑选器/② 安全）
 * 前置：backend 容器带批 X 代码（docker cp 热补丁）；本机栈 3000。全程 0 元不碰真板。
 * 前置：backend 容器带批 X 代码（docker cp 热补丁或镜像重建）＋前端容器带批 X bundle；
 * 本机栈 3000。全程 0 元不碰真板。⚠️ 本机栈是共享移动靶：并行会话重建容器会冲掉热补丁，
 * 跑门前先确认（grep is_shell /app/app/api/assets/misc.py）。
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = process.env.SHOOT_BASE || 'http://127.0.0.1:3000';
const OUT = '/tmp/shots-x';
mkdirSync(OUT, { recursive: true });
const TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_x', 'utf8').trim();
if (!TOK.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }
const STAMP = String(Date.now()).slice(-6);
const TX1 = `批X门禁钩子${STAMP}：他推门而入，全场回头。`;
const TX2 = `批X壳稿钩子${STAMP}：她撕了婚书，转身上了出租车。`;

const CDP_PORT = 9351;
const USER_DATA = '/tmp/asset-shot-profile-x';
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
  return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 200)}` : r.result?.value;
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
const clickTab = async (re) => js(`
  (() => { const rx = new RegExp(${JSON.stringify(re)});
    const list = Array.from(document.querySelectorAll('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn'))
      .filter((e) => e.offsetParent !== null && rx.test(e.innerText || ''));
    if (!list.length) return 'no-hit'; list[0].click(); return 'ok'; })()
`);
const clickByRe = async (sel, re) => js(`
  (() => { const rx = new RegExp(${JSON.stringify(re)});
    const list = Array.from(document.querySelectorAll(${JSON.stringify(sel)}))
      .filter((e) => e.offsetParent !== null && rx.test(e.innerText || e.textContent || ''));
    if (!list.length) return 'no-hit:' + ${JSON.stringify(sel)};
    list[0].click(); return 'ok'; })()
`);
const setVal = (sel, v) => js(`
  (() => { const el = Array.from(document.querySelectorAll(${JSON.stringify(sel)}))
      .find((e) => e.offsetParent !== null);
    if (!el) return 'no-el:' + ${JSON.stringify(sel)};
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(v)});
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return 'ok'; })()
`);
const api = (path) => js(`
  (async () => {
    const r = await fetch('${'http://127.0.0.1:3000'}${path}', { headers: { Authorization: 'Bearer ' + localStorage.getItem('auth_token') } });
    return { status: r.status, body: await r.json() };
  })()
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
  const netLog = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error).slice(0, 200))) : p.res(m.result);
      return;
    }
    if (m.method === 'Network.responseReceived') {
      const u = m.params.response.url || '';
      if (u.includes('/api/assets/summaries')) {
        netLog.push({ u: u.replace('http://127.0.0.1:3000', ''), st: m.params.response.status });
      }
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });

  // 前置：用 API 造一个极简壳（手写→定稿→送审），给 X4/X5 用
  const mk = await api('/api/assets/scripts', 'POST');
  const pre = await api('/api/assets/scripts', 'POST');
  // 上面两个 GET 会 405——真正创建走下面 curl
  execSync(`curl -s -X POST http://127.0.0.1:8001/api/assets/scripts -H "Authorization: Bearer ${TOK}" -H 'Content-Type: application/json' -d '{"name":"X门禁壳稿${STAMP}","body":"${TX2}","source_kind":"manual"}' > /tmp/x-shell.json`);
  const shell = JSON.parse(readFileSync('/tmp/x-shell.json', 'utf8'));
  assert('X0 前置：手写壳稿建成', !!shell.id, JSON.stringify(shell).slice(0, 140));
  const fin = JSON.parse(execSync(`curl -s -X POST http://127.0.0.1:8001/api/assets/scripts/${shell.id}/finalize -H "Authorization: Bearer ${TOK}" -H 'Content-Type: application/json' -d '{}'`, { encoding: 'utf8' }));
  assert('X0b 壳稿定稿 ready', fin.state === 'ready', JSON.stringify(fin).slice(0, 120));
  const sub = JSON.parse(execSync(`curl -s -X POST http://127.0.0.1:8001/api/assets/scripts/submit -H "Authorization: Bearer ${TOK}" -H 'Content-Type: application/json' -d '{"script_ids":["${shell.id}"]}'`, { encoding: 'utf8' }));
  assert('X0c 壳稿送审（造壳）', (sub.results || [{}])[0].ok !== false, JSON.stringify(sub).slice(0, 160));

  await setToken(TOK);
  await goto('/assets');
  await sleep(2500);
  await segClick('完整'); await sleep(1200);

  // ── X4（提前）：极简送审的壳在 ③ 显形打「脚本稿」标且过得掉 ──
  // 放在 X1 贴文案导入**之前**：导入会新建批次并把页面批次上下文切过去，壳按设计
  // 不挂批次，会被批次筛选正确地滤掉（产品行为没错）。此时还没动过任何批次。
  await clickTab('文案审核'); await sleep(2200);
  await setVal('.ant-tabs-tabpane-active input[placeholder="搜正文/素材码"]', TX2.slice(0, 12));
  await sleep(2000);
  const shellCard = await js(`
    (() => { const pane = document.querySelector('.ant-tabs-tabpane-active') || document.body;
      const node = Array.from(pane.querySelectorAll('div,span')).find((e) => (e.innerText || '').includes('${TX2}') && e.children.length <= 2);
      if (!node) return 'no-card';
      let root = node;
      for (let i = 0; i < 10 && root; i++) { if (root.querySelector('.ant-tag-purple')) break; root = root.parentElement; }
      const tag = root && Array.from(root.querySelectorAll('.ant-tag-purple')).find((x) => x.textContent.trim() === '脚本稿');
      if (!tag) return 'no-shell-tag';
      const btn = Array.from(root.querySelectorAll('button')).find((b) => (b.innerText || '').trim() === '过');
      if (!btn) return 'no-approve-btn';
      btn.click(); return 'ok'; })()
  `);
  await sleep(2200);
  const shellAp = await api(`/api/assets/scripts?owner=all&carrier_status=approved&page_size=100`);
  const shellNow = (shellAp.body.items || []).find((x) => x.id === shell.id);
  assert('X4 壳显形打「脚本稿」标且过得掉、脚本立即可投',
    String(shellCard) === 'ok' && !!shellNow, JSON.stringify({ card: shellCard, ok: !!shellNow }).slice(0, 180));
  await shot('x4-shell');

  // ── X5（提前）：壳在默认口径仍被藏 ──
  const hidden = await api(`/api/assets/summaries?page_size=300&q=${encodeURIComponent(TX2.slice(0, 12))}`);
  const shown = await api(`/api/assets/summaries?page_size=300&include_carriers=true&q=${encodeURIComponent(TX2.slice(0, 12))}`);
  const hItems = (hidden.body.items || []).filter((x) => (x.text || '').includes(TX2));
  const sItems = (shown.body.items || []).filter((x) => (x.text || '').includes(TX2));
  assert('X5 壳默认藏、include_carriers=true 显形', hItems.length === 0 && sItems.length === 1 && sItems[0].is_shell === true,
    JSON.stringify({ h: hItems.length, s: sItems.length }).slice(0, 140));

  // 清掉壳稿关键词，恢复完整列表给后续步骤
  await setVal('.ant-tabs-tabpane-active input[placeholder="搜正文/素材码"]', '');
  await sleep(1500);
  await clickTab('导入'); await sleep(1800);

  // ── X1 UI 贴文案导入 ──
  await setVal('.ant-tabs-tabpane-active textarea', TX1);
  await sleep(400);
  const imp = await clickByRe('.ant-tabs-tabpane-active button', '导入进审核队列');
  assert('X1a 点了「导入进审核队列」', imp === 'ok', imp);
  // 落库可能比点击慢（自动预取号会跑子进程），轮询别死等
  let items = [];
  for (let i = 0; i < 10 && !items.length; i++) {
    await sleep(1500);
    const after = await api(`/api/assets/summaries?page_size=300`);
    items = (after.body.items || []).filter((x) => (x.text || '').includes(TX1));
  }
  assert('X1 UI 贴文案导入成功且候选落库', items.length === 1 && items[0].is_shell === false,
    JSON.stringify({ n: items.length }).slice(0, 160));
  const sid1 = items[0] && items[0].id;
  await shot('x1-imported');

  // ── X2 极简脚本库出现「候选」标镜像行 ──
  await segClick('极简'); await sleep(1500);
  // 脚本库默认页签
  const lst = await api(`/api/assets/scripts?owner=all&page_size=200`);
  const mirror = (lst.body.items || []).find((x) => x.source_kind === 'mirror' && (x.name || '').includes(STAMP));
  assert('X2 镜像脚本落库（ready/mirror/候选名）', !!mirror && mirror.state === 'ready',
    JSON.stringify({ n: (lst.body.items || []).length, found: !!mirror }).slice(0, 140));
  const tagState = await js(`
    (() => { const pane = document.querySelector('.ant-tabs-tabpane-active') || document.body;
      const t = pane.innerText;
      const purple = Array.from(pane.querySelectorAll('.ant-tag-purple')).some((x) => x.textContent.trim() === '候选');
      return { nameSeen: t.includes('候选·'), purple }; })()
  `);
  assert('X2b 脚本库列表渲染「候选」紫标', tagState && tagState.nameSeen && tagState.purple, JSON.stringify(tagState));
  await shot('x2-mirror');

  // ── X3 ③ 审核台过审候选 → 镜像可投 ──
  await segClick('完整'); await sleep(1200);
  await clickTab('文案审核'); await sleep(2200);
  // 用审核台自己的搜索把目标卡收进第一页（列表按素材聚合排序，新卡不一定在第一页）。
  // ⚠️ 不能选 pane 第一个 input——那是「审核状态」下拉的 combobox，按 placeholder 定位搜索框
  await setVal('.ant-tabs-tabpane-active input[placeholder="搜正文/素材码"]', TX1.slice(0, 12));
  await sleep(2000);
  const card = await js(`
    (() => { const pane = document.querySelector('.ant-tabs-tabpane-active') || document.body;
      const node = Array.from(pane.querySelectorAll('div,span')).find((e) => (e.innerText || '').includes('${TX1}') && e.children.length <= 2);
      if (!node) return 'no-card';
      let root = node;
      for (let i = 0; i < 10 && root; i++) { if (root.querySelector('button') && /过/.test(root.innerText)) break; root = root.parentElement; }
      const btn = root && Array.from(root.querySelectorAll('button')).find((b) => (b.innerText || '').trim() === '过');
      if (!btn) return 'no-approve-btn';
      btn.click(); return 'ok'; })()
  `);
  await sleep(2200);
  const afterAp = await api(`/api/assets/summaries?page_size=50&ids=${sid1}`);
  const apRow = (afterAp.body.items || [])[0] || {};
  assert('X3 ③ 点「过」候选过审', apRow.audit_status === 'approved', JSON.stringify({ card: card, st: apRow.audit_status }).slice(0, 180));
  const apScripts = await api(`/api/assets/scripts?owner=all&carrier_status=approved&page_size=100`);
  const mirrorNow = (apScripts.body.items || []).find((x) => x.source_kind === 'mirror' && (x.name || '').includes(STAMP));
  assert('X3b 过审后镜像进「载体已过审」桶（可投）', !!mirrorNow, JSON.stringify({ n: (apScripts.body.items || []).length }).slice(0, 120));
  await shot('x3-approved');

  // ── X4 壳在 ③ 显形打「脚本稿」标且过得掉 ──
  await js(`(() => { window.scrollTo(0,0); return 'ok'; })()`);
  const pass = results.filter((r) => r.c).length;
  console.log(`\n==== ${pass}/${results.length} PASS ====`);
  results.filter((r) => !r.c).forEach((r) => console.log('  FAIL ' + r.n));
}

main()
  .catch((e) => { console.error('ERROR', e); process.exitCode = 1; })
  .finally(() => { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); });
