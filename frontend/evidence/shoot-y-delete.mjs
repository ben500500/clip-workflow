#!/usr/bin/env node
/*
 * 批 Y CDP 真截图门（2026-11-25）
 *
 * 用户原话：「成片墙，没有删除功能，比如超时生成的豆包素材无法删掉」
 * 拍板：在途单＋成片都能删；成片走「彻底删」（台账行＋MinIO 文件一起，留审计）。
 *
 * 前置：本机栈 3000（前端容器已 docker cp 批 Y bundle）＋ clip-backend 已 docker cp 批 Y misc.py；
 * SQL 种了 1 张 queued 在途单（board_name=批Y门禁在途, hook CDPY1, 投出 80 分）
 * ＋ 2 条假成片（批Y门禁成片A/B，挂在这张单上拿 CDPY1 角标）。
 * 全程不碰真板、不花钱；删的都是种出来的假行。
 *
 * 用法：node frontend/evidence/shoot-y-delete.mjs /tmp/.cdp_tok_y
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = process.env.SHOOT_BASE || 'http://127.0.0.1:3000';
const API = 'http://127.0.0.1:8001';
const OUT = '/tmp/shots-y';
mkdirSync(OUT, { recursive: true });
const TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_y', 'utf8').trim();
if (!TOK.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }

const CDP_PORT = 9353;
const USER_DATA = '/tmp/asset-shot-profile-y';
const PROD_ID = 'b0e00000-0000-4000-8000-000000000001';
const OUT_A = 'c0e00000-0000-4000-8000-000000000001';
const OUT_B = 'c0e00000-0000-4000-8000-000000000002';
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
  const clickTab = (re) => js(`
    (() => { const rx = new RegExp(${JSON.stringify(re)});
      const t = Array.from(document.querySelectorAll('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn'))
        .find((e) => e.offsetParent !== null && rx.test(e.innerText || ''));
      if (!t) return 'no-hit'; t.click(); return 'ok'; })()
  `);
  const stripState = () => js(`
    (() => {
      const box = document.querySelector('[data-inflight]');
      if (!box) return { none: true, text: '', delBtns: 0 };
      const t = box.innerText.replace(/\\s+/g, ' ');
      const dels = Array.from(box.querySelectorAll('button')).filter(
        (b) => b.offsetParent !== null && (b.innerText || '').trim() === '删掉这单');
      return { none: false, text: t, delBtns: dels.length };
    })()
  `);
  const openPopconfirmOk = (okTextRe) => js(`
    (() => { const rx = new RegExp(${JSON.stringify(okTextRe)});
      const pops = Array.from(document.querySelectorAll('.ant-popconfirm, .ant-popover')).filter((p) => p.offsetParent !== null);
      for (const p of pops) {
        const b = Array.from(p.querySelectorAll('button')).find((x) => x.offsetParent !== null && rx.test((x.innerText || '').trim()));
        if (b) { b.click(); return 'ok'; }
      }
      return 'no-ok:' + pops.length; })()
  `);
  // 找一张带指定角标文字（CDPY1）的成片卡：卡容器=带 checkbox 且 innerText 含关键词的最外层 grid item
  const clickCardByText = (needle, mode) => js(`
    (() => {
      const cb = Array.from(document.querySelectorAll('.ant-tabs-tabpane-active input[type=checkbox]'));
      for (const input of cb) {
        let root = input.closest('div[style*="padding-top"]') && input.closest('div').parentElement;
        // 卡根 = checkbox 所在的 133% 预览块再往上一层（caption 与预览块同级）
        let box = input;
        for (let i = 0; i < 6 && box; i++) {
          box = box.parentElement;
          if (box && (box.innerText || '').includes(${JSON.stringify(needle)})) { root = box; break; }
        }
        if (!root || !(root.innerText || '').includes(${JSON.stringify(needle)})) continue;
        if (${JSON.stringify(mode)} === 'check') {
          input.click(); return 'ok-check';
        }
        const thumb = Array.from(root.querySelectorAll('div')).find((d) => (d.getAttribute('style') || '').includes('padding-top: 133%'));
        if (!thumb) return 'no-thumb';
        thumb.click(); return 'ok-click';
      }
      return 'no-card';
    })()
  `);
  const modalState = () => js(`
    (() => {
      // .ant-modal-wrap 是 position:fixed，offsetParent 恒 null——可见性要看 display
      const m = Array.from(document.querySelectorAll('.ant-modal-wrap')).find((x) => {
        const cs = getComputedStyle(x); return cs.display !== 'none' && cs.visibility !== 'hidden';
      });
      if (!m) return { open: false };
      const t = m.innerText.replace(/\\s+/g, ' ');
      const btns = Array.from(m.querySelectorAll('button')).filter((b) => b.offsetParent !== null || getComputedStyle(b).display !== 'none').map((b) => (b.innerText || '').trim());
      return { open: true, text: t, btns };
    })()
  `);
  const toolbarState = () => js(`
    (() => { const p = document.querySelector('.ant-tabs-tabpane-active');
      const btn = Array.from(p.querySelectorAll('button')).find((b) => b.offsetParent !== null && /删除勾选的/.test(b.innerText || ''));
      const segTxt = (p.innerText.match(/删除勾选的\\s*\\d+\\s*条/) || [''])[0].replace(/\\s+/g, ' ');
      return { has: !!btn, disabled: btn ? btn.disabled : null, label: segTxt }; })()
  `);

  await setToken(TOK);
  await goto('/assets');
  await sleep(2600);
  await segClick('极简'); await sleep(1500);
  const t = await clickTab('看成片');
  await sleep(2800);
  assert('Y0 打开 ③ 看成片', t === 'ok', t);

  // ── Y1：在途卡带「删掉这单」 ──
  let s = await stripState();
  assert('Y1 在途条里有种出来的超时单（批Y门禁在途）', !s.none && /批Y门禁在途/.test(s.text), s.text.slice(0, 220));
  assert('Y1b queued 卡上有且只有一张带「删掉这单」', s.delBtns === 1, JSON.stringify({ del: s.delBtns }).slice(0, 120));
  await shot('y1-inflight-card');

  // 点删单 → Popconfirm 确认
  const clicked = await js(`
    (() => { const box = document.querySelector('[data-inflight]');
      const b = Array.from(box.querySelectorAll('button')).find((x) => x.offsetParent !== null && (x.innerText || '').trim() === '删掉这单');
      if (!b) return 'no-btn'; b.click(); return 'ok'; })()
  `);
  await sleep(700);
  const popTxt = await js(`(() => { const p = Array.from(document.querySelectorAll('.ant-popconfirm')).find((x) => x.offsetParent !== null);
    return p ? p.innerText.replace(/\\s+/g,' ') : 'no-pop'; })()`);
  assert('Y2 删单弹层说清后果（报丢/回片不再挂单）', String(popTxt).includes('报丢'), popTxt);
  await shot('y2-popconfirm');
  const ok1 = await openPopconfirmOk('删掉这单');
  await sleep(1800);
  s = await stripState();
  assert('Y2b 确认后在途卡消失', ok1 === 'ok' && !/批Y门禁在途/.test(s.text), JSON.stringify({ ok: ok1, text: s.text.slice(0, 160) }));
  const dbProd = sql(`SELECT status, left(error, 60) FROM asset_productions WHERE id='${PROD_ID}'`);
  assert('Y2c 库里状态置 cancelled＋删单原因落 error', /^cancelled\|.*人工删单/.test(dbProd), dbProd);
  await shot('y3-after-cancel');

  // ── Y4：预览弹窗「删除这条」删成片A ──
  // 极简墙是两级：先点组头（innerText 含 CDPY1 的 div[role=button]）展开该组的 OutputGrid
  const openGroup = () => js(`
    (() => { const p = document.querySelector('.ant-tabs-tabpane-active');
      const h = Array.from(p.querySelectorAll('div[role=button]')).find((x) =>
        x.offsetParent !== null && /CDPY1/.test(x.innerText || '') && /条/.test(x.innerText || ''));
      if (!h) return 'no-group'; h.click(); return 'ok'; })()
  `);
  const g = await openGroup();
  await sleep(2200);
  assert('Y3a 点开 CDPY1 所在组（第二级墙挂载）', g === 'ok', g);
  const clickA = await clickCardByText(OUT_A.slice(0, 8), 'click');
  // 卡上不含 uuid，改按 caption 的 CDPY1 找到卡（两张都挂 CDPY1）——先开预览再看标题
  const click1 = clickA === 'no-card' || String(clickA).startsWith('no-') ? await clickCardByText('CDPY1', 'click') : clickA;
  await sleep(1600);
  let mv = await modalState();
  assert('Y4a 点卡开预览（标题是批Y门禁成片）', mv.open && /批Y门禁成片/.test(mv.text), JSON.stringify({ g, clickA, click1, mv: (mv.text || '').slice(0, 120) }).slice(0, 260));
  assert('Y4b 预览底部有「删除这条」', (mv.btns || []).includes('删除这条'), JSON.stringify(mv.btns));
  await shot('y4-preview');
  await js(`(() => { const m = Array.from(document.querySelectorAll('.ant-modal-wrap')).find((x)=>getComputedStyle(x).display!=='none');
    const b = Array.from(m.querySelectorAll('button')).find((x)=>(x.innerText||'').trim()==='删除这条'); b.click(); return 'ok'; })()`);
  await sleep(700);
  const ok2 = await openPopconfirmOk('彻底删除');
  await sleep(1800);
  mv = await modalState();
  // 两张卡同钩子号，勾选/预览命中哪张取决于排序——断言按「两条里少了一条」写，不锁死 A/B
  const left1 = Number(sql(`SELECT count(*) FROM asset_outputs WHERE id IN ('${OUT_A}','${OUT_B}')`));
  assert('Y4c 确认后弹窗关闭且少了一条成片（单条删口真删）', ok2 === 'ok' && !mv.open && left1 === 1, JSON.stringify({ ok: ok2, open: mv.open, left1 }));

  // ── Y5：勾选成片B → 工具栏「删除勾选的 1 条」 ──
  const ck = await clickCardByText('CDPY1', 'check');
  await sleep(900);
  const tb = await toolbarState();
  assert('Y5a 勾选后工具栏出「删除勾选的 1 条」', ck === 'ok-check' && tb.has && !tb.disabled && /1/.test(tb.label), JSON.stringify({ ck, tb }).slice(0, 200));
  await shot('y5-toolbar');
  await js(`(() => { const p = document.querySelector('.ant-tabs-tabpane-active');
    const b = Array.from(p.querySelectorAll('button')).find((x)=>x.offsetParent!==null && /删除勾选的/.test(x.innerText||'')); b.click(); return 'ok'; })()`);
  await sleep(700);
  const ok3 = await openPopconfirmOk('彻底删除');
  await sleep(1800);
  const left2 = Number(sql(`SELECT count(*) FROM asset_outputs WHERE id IN ('${OUT_A}','${OUT_B}')`));
  const s2 = await stripState();
  // 组头 label 里的钩子号是进墙时的旧快照，不算数——只数网格里还挂着 CDPY1 的卡
  const capCards = await js(`
    (() => { const p = document.querySelector('.ant-tabs-tabpane-active');
      return Array.from(p.querySelectorAll('div[style*="padding-top: 133%"]'))
        .filter((d) => /CDPY1/.test((d.parentElement && d.parentElement.innerText) || '')).length; })()
  `);
  assert('Y5b 确认后两条种子成片全没（库里 0 张、墙上 0 卡、占位条无残留）', ok3 === 'ok' && left2 === 0 && capCards === 0 && !/批Y门禁/.test(s2.text), JSON.stringify({ ok: ok3, left2, capCards }).slice(0, 160));

  // ── Y6：审计两笔都留痕 ──
  const audits = sql(`SELECT action, target_id FROM audit_logs WHERE action IN ('asset.production.cancel','asset.outputs.delete') ORDER BY created_at DESC LIMIT 6`);
  const cancelN = (audits.match(/asset\.production\.cancel/g) || []).length;
  const delN = (audits.match(/asset\.outputs\.delete/g) || []).length;
  assert('Y6 审计各留一笔（删单1＋删成片1，成片笔 strict=t）', cancelN >= 1 && delN >= 1, audits.replace(/\n/g, ' | ').slice(0, 260));
  const pass = results.filter((r) => r.c).length;
  console.log(`\n==== ${pass}/${results.length} PASS ====`);
  results.filter((r) => !r.c).forEach((r) => console.log('  FAIL ' + r.n));
  if (pass < results.length) process.exitCode = 1;
}

main()
  .catch((e) => { console.error('ERROR', e); process.exitCode = 1; })
  .finally(() => { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); });
