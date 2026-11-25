#!/usr/bin/env node
/*
 * 批 AB-2 CDP 真截图门（2026-11-25）
 *
 * 用户原话：「素材库增加批量删除」→ 落在极简① 脚本库：勾选（含草稿）→「删除（N）」＝批量下架。
 *
 * 前置：vite 5199（evidence/vite.config.cdp.mjs，/api→127.0.0.1:8001 热补丁 backend）；
 * 种子 4 条：material 的 我的稿A/我的稿B（draft）、我的定稿C（ready）、admin 的 别人的稿D（draft）。
 * 全程不碰真板、不花钱；删的都是种出来的假行。
 *
 * 用法：node frontend/evidence/shoot-ab-delete.mjs   （token 读 /tmp/toks_ab.txt：行1=admin 行2=material）
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = process.env.SHOOT_BASE || 'http://127.0.0.1:5199';
const OUT = '/tmp/shots-ab';
mkdirSync(OUT, { recursive: true });
const lines = readFileSync('/tmp/toks_ab.txt', 'utf8').split('\n').map((x) => x.trim()).filter(Boolean);
const ADM = lines[0];
const MAT = lines[1];
if (!ADM?.startsWith('ey') || !MAT?.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }

const CDP_PORT = 9354;
const USER_DATA = '/tmp/asset-shot-profile-ab';
const IDS = {
  A: 'c68d7cba-1f63-406c-aab0-9583f932f495',
  B: '44e0eea3-6096-4bcf-97db-40350dfcd0d8',
  C: '5a3622fd-c6ca-479a-abe0-f3a1caa5073e',
  D: 'ca4e9a6c-43c7-4975-9c7e-b012cd264299',
};
const state = (id) => sql(`SELECT state FROM asset_scripts WHERE id='${id}'`);
const sql = (q) => execSync(`docker exec clip-postgres psql -U clipworkflow -d clipworkflow -tA -v ON_ERROR_STOP=1 -c ${JSON.stringify(q)}`, { encoding: 'utf8' }).trim();

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
  console.log(`${c ? 'PASS' : 'FAIL'} ${n}${c ? '' : ' — ' + flat(d).slice(0, 260)}`);
};

async function main() {
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
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });

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
  // 等① 脚本库表格真渲染（admin 默认完整模式，切极简后要留给数据加载的时间）
  const waitForPane = async () => {
    for (let i = 0; i < 60; i++) {
      const ok = await js(`(() => { const p = document.querySelector('.ant-tabs-tabpane-active');
        return !!(p && p.querySelector('.ant-table-tbody tr')); })()`);
      if (ok === true) return true;
      await sleep(400);
    }
    return false;
  };
  // 清 toast 只能藏不能删（批 H 坑：remove 会让后续 Modal 动画卡死）
  const clearToasts = () => js(`
    (() => { document.querySelectorAll('.ant-message').forEach((x) => { x.style.display = 'none'; }); return 'ok'; })()
  `);
  /** 表格里按行文本找勾选框：返回 {found, disabled, checked} 或按 mode='check' 点一下 */
  const rowCb = (needle, mode) => js(`
    (() => { const p = document.querySelector('.ant-tabs-tabpane-active');
      const tr = Array.from(p.querySelectorAll('.ant-table-tbody tr')).find((r) => (r.innerText || '').includes(${JSON.stringify(needle)}));
      if (!tr) return { found: false };
      const cb = tr.querySelector('input[type=checkbox]');
      if (!cb) return { found: true, noCb: true };
      if (${JSON.stringify(mode)} === 'check' && !cb.checked) cb.click();
      return { found: true, disabled: cb.disabled, checked: cb.checked }; })()
  `);
  const delBtn = () => js(`
    (() => { const p = document.querySelector('.ant-tabs-tabpane-active');
      const b = Array.from(p.querySelectorAll('button')).find((x) => x.offsetParent !== null && /^删除（\\d+）/.test((x.innerText || '').replace(/\\s+/g, '')));
      return b ? { label: (b.innerText || '').replace(/\\s+/g, ''), disabled: b.disabled } : null; })()
  `);
  const modalState = () => js(`
    (() => {
      const ms = Array.from(document.querySelectorAll('.ant-modal-wrap')).filter((x) => {
        const cs = getComputedStyle(x); return cs.display !== 'none' && cs.visibility !== 'hidden';
      });
      if (!ms.length) return { open: false };
      const m = ms[ms.length - 1];
      const t = m.innerText.replace(/\\s+/g, ' ');
      const btns = Array.from(m.querySelectorAll('button')).map((b) => (b.innerText || '').replace(/\\s+/g, ''));
      return { open: true, text: t, btns };
    })()
  `);
  const modalClick = (re) => js(`
    (() => { const rx = new RegExp(${JSON.stringify(re)});
      const ms = Array.from(document.querySelectorAll('.ant-modal-wrap')).filter((x) => getComputedStyle(x).display !== 'none');
      for (const m of ms) {
        const b = Array.from(m.querySelectorAll('button')).find((x) => rx.test((x.innerText || '').replace(/\\s+/g, '')));
        if (b) { b.click(); return 'ok'; }
      }
      return 'no-btn'; })()
  `);

  // AuthGuard 会偶发把深链 /assets 弹回 /dashboard（本机记忆坑）：弹了就走侧边栏「素材库」进
  const openAssets = async () => {
    await goto('/assets');
    await sleep(2600);
    const where = await js('location.pathname');
    if (where !== '/assets') {
      const mk = await js(`(() => { const el = Array.from(document.querySelectorAll('.ant-menu-item, li[role="menuitem"]'))
          .find((x) => (x.innerText || '').trim() === '素材库');
        if (!el) return 'no-menu'; el.click(); return 'ok'; })()`);
      if (mk !== 'ok') throw new Error(`/assets 被弹回且侧边栏点不到素材库（${where}/${mk}）`);
      await sleep(2000);
    }
    await segClick('极简'); await sleep(1200);
    return waitForPane();
  };

  // ══ 第一轮：material 删自己的 2 条＋够不着别人的 1 条 ══
  await setToken(MAT);
  const paneReady1 = await openAssets();
  assert('AB0 极简① 脚本库打开（表格已渲染）', paneReady1 === true, String(paneReady1));

  const ra = await rowCb('AB门禁·我的稿A');
  assert('AB1 草稿行的勾选框可选（改动前 ready 才可勾）', ra.found && !ra.disabled, JSON.stringify(ra));
  const btn0 = await delBtn();
  assert('AB1b 未勾选时「删除（0）」禁用', !!btn0 && btn0.disabled && /（0）/.test(btn0.label), JSON.stringify(btn0));

  await rowCb('AB门禁·我的稿A', 'check');
  await rowCb('AB门禁·我的稿B', 'check');
  await rowCb('AB门禁·别人的稿D', 'check');
  await sleep(600);
  const btn1 = await delBtn();
  assert('AB2 勾 3 条（含草稿＋他人）后按钮＝删除（3）可点', !!btn1 && !btn1.disabled && btn1.label === '删除（3）', JSON.stringify(btn1));
  await shot('ab2-checked3');

  await js(`(() => { const p = document.querySelector('.ant-tabs-tabpane-active');
    const b = Array.from(p.querySelectorAll('button')).find((x) => (x.innerText || '').replace(/\\s+/g, '').startsWith('删除（3）'));
    b.click(); return 'ok'; })()`);
  await sleep(900);
  let mv = await modalState();
  assert('AB3 确认弹窗说清后果（下架＝不硬删＋别人的删不动）', mv.open && mv.text.includes('删除＝下架') && mv.text.includes('别人写的脚本删不动'), JSON.stringify(mv).slice(0, 240));
  await shot('ab3-confirm');
  assert('AB3b 按钮是「删除/算了」危险色确认', (mv.btns || []).some((x) => /^删除$/.test(x)) && (mv.btns || []).some((x) => x === '算了'), JSON.stringify(mv.btns));

  await modalClick('^删除$');
  await sleep(2600);
  mv = await modalState();
  assert('AB4 部分失败弹「1 条删除没成（其余 2 条已成功）」', mv.open && mv.text.includes('1 条删除没成（其余 2 条已成功）'), JSON.stringify(mv).slice(0, 240));
  assert('AB4b 逐条点名到 D＋白话原因', mv.open && mv.text.includes('AB门禁·别人的稿D') && mv.text.includes('不是你的'), (mv.text || '').slice(0, 240));
  await shot('ab4-verdict');
  await modalClick('^确定$|^OK$|^知道了$');
  await sleep(2000);

  assert('AB5 库里 A/B 已下架，C/D 原样', state(IDS.A) === 'retired' && state(IDS.B) === 'retired' && state(IDS.C) !== 'retired' && state(IDS.D) !== 'retired',
    `A=${state(IDS.A)} B=${state(IDS.B)} C=${state(IDS.C)} D=${state(IDS.D)}`);
  const gone = await js(`(() => { const p = document.querySelector('.ant-tabs-tabpane-active'); const t = p.innerText;
    return { a: t.includes('我的稿A'), b: t.includes('我的稿B'), d: t.includes('别人的稿D'), c: t.includes('我的定稿C') }; })()`);
  assert('AB5b 列表刷新：下架的两条消失，没成的还在', !gone.a && !gone.b && gone.d && gone.c, JSON.stringify(gone));

  // ══ 第二轮：admin 删 C＋D（换 token＝整页重载，顺带甩掉弹窗/toast 残留） ══
  await clearToasts();
  await setToken(ADM);
  const paneReady2 = await openAssets();
  assert('AB6a admin 侧同样进了极简① 脚本库', paneReady2 === true, String(paneReady2));
  const rc = await rowCb('AB门禁·我的定稿C', 'check');
  const rd = await rowCb('AB门禁·别人的稿D', 'check');
  await sleep(600);
  const btn2 = await delBtn();
  assert('AB6 admin 勾 2 条（含他人稿）→删除（2）', rc.found && rd.found && !!btn2 && !btn2.disabled && btn2.label === '删除（2）', JSON.stringify({ rc, rd, btn2 }).slice(0, 200));
  await js(`(() => { const p = document.querySelector('.ant-tabs-tabpane-active');
    const b = Array.from(p.querySelectorAll('button')).find((x) => (x.innerText || '').replace(/\\s+/g, '').startsWith('删除（2）'));
    b.click(); return 'ok'; })()`);
  await sleep(900);
  await modalClick('^删除$');
  await sleep(2600);
  await shot('ab7-admin-done');
  assert('AB8 admin 全成：C/D 库里已下架', state(IDS.C) === 'retired' && state(IDS.D) === 'retired',
    `C=${state(IDS.C)} D=${state(IDS.D)}`);

  const audits = sql(`SELECT count(*) FROM audit_logs WHERE action='asset.script.retire' AND target_id IN ('${IDS.A}','${IDS.B}','${IDS.C}','${IDS.D}')`);
  const batchFlags = sql(`SELECT count(*) FROM audit_logs WHERE action='asset.script.retire' AND after::text LIKE '%batch%' AND target_id IN ('${IDS.A}','${IDS.B}','${IDS.C}','${IDS.D}')`);
  assert('AB9 审计四条齐＋batch 标记在位', Number(audits) >= 4 && Number(batchFlags) >= 4, `audits=${audits} batch=${batchFlags}`);

  const pass = results.filter((r) => r.c).length;
  console.log(`\n==== ${pass}/${results.length} PASS ====`);
  results.filter((r) => !r.c).forEach((r) => console.log('  FAIL ' + r.n));
  if (pass < results.length) process.exitCode = 1;
}

main()
  .catch((e) => { console.error('ERROR', e); process.exitCode = 1; })
  .finally(() => { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); });
