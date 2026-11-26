#!/usr/bin/env node
/*
 * 批 V CDP 真截图门（2026-11-25）
 *
 * 用户原话：
 *   「第一个投了豆包之后，豆包界面上的那些记录就可以清除了，比如说上传的三视图，或者选的文案等。
 *    第二个，投了豆包之后，在豆包返回之前，素材墙（即看成片的地方）最好也能把这个任务先显示出来，
 *    并标注一个状态（比如"豆包正在生成中"），要不然不知道目前是什么情况」
 * 追问后定型的形状：①清的是**我们这套投板弹窗/开单屏**的输入；②占位＝**灰卡按单一张**，
 * 而且「失败/超时也要标出来」。
 *
 * 本机栈跑（vite dev 5199 → 代理 127.0.0.1:8001），数据是 SQL 种的四条假单：
 *   正常在途 6 分 / 超时 70 分（>45）/ 最近失败 20 分 / 3 天前的失败（只进 failed_older 计数）
 * W 段拦 POST /api/assets/scripts/produce，**不发到真板**（不占号池、不花钱）。
 *
 * 用法（两步，桩中间件必须一起起，否则 W 段会打到真板）：
 *   cd frontend && npx vite build --config evidence/vite.config.cdp.mjs
 *   npx vite preview --config evidence/vite.config.cdp.mjs      # 127.0.0.1:5199
 *   node frontend/evidence/shoot-v-wall.mjs <admin-token-file>
 * 桩开关在 /tmp/produce-mode.txt（off=放行真后端 / ok=回执投出 / blocked=400 一条没投出去），
 * 命中计数在 /tmp/produce-hits.log；本门只在 off 档之外跑，真板一次都不会被碰到。
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = process.env.SHOOT_BASE || 'http://127.0.0.1:5199';
const OUT = '/tmp/shots-v';
mkdirSync(OUT, { recursive: true });
const TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_v', 'utf8').trim();
if (!TOK.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }

const CDP_PORT = 9345;
const USER_DATA = '/tmp/asset-shot-profile-v';
const MODE = '/tmp/produce-mode.txt';
const HITS = '/tmp/produce-hits.log';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
// 投豆包这一枪由 vite preview 的桩中间件接管（vite.config.cdp.mjs）：
// 模式写文件（off=放行真后端 / ok=回执投出 / blocked=按真后端口径 400），命中数数日志行数。
// 早前想用 CDP Fetch.fulfillRequest 拦，Chrome 这边 fulfill 出来的 body 恒空，故换这条。
const setProduceMode = (m) => writeFileSync(MODE, m);
const resetHits = () => writeFileSync(HITS, '');
const hitCount = () => (existsSync(HITS) ? readFileSync(HITS, 'utf8').split('\n').filter(Boolean).length : 0);
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
      return;
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
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
  // 只取最外层活动面板（antd 隐藏页签留在 DOM 里，全局 querySelector 会点到隐藏面板）
  const activeText = () => js(`
    (() => {
      const p = document.querySelector('.ant-tabs-tabpane-active');
      return (p || document.body).innerText.replace(/\\s+/g,' ').trim();
    })()
  `);
  const clickByRe = async (sel, re) => js(`
    (() => {
      const rx = new RegExp(${JSON.stringify(re)});
      const list = Array.from(document.querySelectorAll(${JSON.stringify(sel)}))
        .filter((e) => e.offsetParent !== null && rx.test((e.innerText || e.textContent || '')));
      if (!list.length) return 'no-hit:' + ${JSON.stringify(sel)};
      list[0].click();
      return 'ok';
    })()
  `);
  const clickTab = async (re) => {
    const hit = await clickByRe('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn', re);
    return hit === 'ok' ? hit : clickByRe('.ant-tabs .ant-tabs-nav .ant-tabs-tab', re);
  };
  const segClick = (label) => js(`
    (() => { const el = Array.from(document.querySelectorAll('.ant-segmented-item'))
        .find((x) => x.textContent.trim() === ${JSON.stringify(label)} && x.offsetParent !== null);
      if (!el) return 'no-seg'; el.click(); return 'ok'; })()
  `);
  // 占位卡：只认虚线容器里的那批，别把墙上的真成片卡数进来
  const stripCards = () => js(`
    (() => {
      const box = document.querySelector('[data-inflight]');
      if (!box) return { none: true, gen: 0, fail: 0, text: '' };
      const t = box.innerText.replace(/\s+/g, ' ');
      // 按单一张＝每张卡**有且只有一个**右下角黑底时长角标（标题栏图标与正文里的话都不算）
      const badges = Array.from(box.querySelectorAll('div'))
        .filter((d) => (d.getAttribute('style') || '').includes('rgba(0, 0, 0, 0.55)'));
      const gen = badges.filter((d) => /^投出 /.test(d.textContent.trim())).length;
      const fail = badges.filter((d) => /^失败 /.test(d.textContent.trim())).length;
      return { none: false, gen, fail, text: t, badges: badges.length };
    })()
  `);

  const chipCount = () => js(`document.querySelectorAll('button[aria-label="往前挪"]').length`);
  const setVersion = (n) => js(`
    (() => {
      const inp = Array.from(document.querySelectorAll('.ant-tabs-tabpane-active .ant-input-number input')).find((e) => e.offsetParent !== null);
      if (!inp) return 'no-input';
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(inp, ${JSON.stringify(String(n))});
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      inp.blur();
      return 'ok';
    })()
  `);
  // 挑一张还没挑上的卡（多选 Select 要点开才渲染，且已选中的项要点第 2 张才看得出变化）
  const dropOpen = () => js(`!!document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')`);
  const toggleSel = () => js(`
    (() => { const t = Array.from(document.querySelectorAll('.ant-tabs-tabpane-active .ant-select-selector')).find((e) => e.offsetParent !== null);
      if (!t) return 'no-select';
      ['mousedown','mouseup','click'].forEach((k) => t.dispatchEvent(new MouseEvent(k, { bubbles: true, cancelable: true, view: window })));
      return 'ok'; })()
  `);
  // 多选 Select 选完不关面板 → 上一批留下的面板可能本就是开着的，再点一下反而是「关掉」。
  // 所以先判开合，只在没开时点开；开完仍没选项就再补一次。
  const pickCard = async () => {
    const before = await chipCount();
    if (!(await dropOpen())) await toggleSel();
    await sleep(900);
    let open = await dropOpen();
    if (!open) { await toggleSel(); await sleep(1100); open = await dropOpen(); }
    const opt = await js(`
      (() => { const on = (el, k) => el.dispatchEvent(new MouseEvent(k, { bubbles: true, cancelable: true, view: window }));
        const o = Array.from(document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')).find((e) => e.offsetParent !== null);
        if (!o) return 'no-option';
        ['mousedown','mouseup','click'].forEach((k) => on(o, k));
        return 'ok:' + (o.textContent || '').trim().slice(0, 18); })()
    `);
    await sleep(900);
    let dbg = '';
    if (!String(opt).startsWith('ok')) {
      dbg = await js(`(() => {
        const dd = Array.from(document.querySelectorAll('.ant-select-dropdown'));
        return JSON.stringify({
          drops: dd.length,
          cls: dd.map((d) => (d.className || '').replace(/\s+/g, ' ').slice(0, 90) + '|vis=' + (d.offsetParent !== null) + '|op=' + getComputedStyle(d).opacity),
          items: document.querySelectorAll('.ant-select-item').length,
          opts: document.querySelectorAll('.ant-select-item-option').length,
          empty: document.querySelectorAll('.ant-empty').length,
          openCls: Array.from(document.querySelectorAll('.ant-select')).map((x) => x.className.includes('open')).join(','),
        });
      })()`);
    }
    return { before, open: open ? 'ok' : 'closed', opt, after: await chipCount(), dbg };
  };

  await setToken(TOK);
  await goto('/assets');
  await sleep(2500);
  const boot = await js("document.body.innerText.replace(/\\s+/g,' ').trim().slice(0,300)");
  const url = await js("location.href");
  console.log(`DEBUG url=${url} text=${String(boot).slice(0,220)}`);
  await shot('v0-boot');
  // 极简三步页签里 ③ 看成片就是墙；先确保在极简
  const seg0 = await segClick('极简');
  await sleep(1800);
  const tabList0 = await js(`Array.from(document.querySelectorAll('.ant-tabs-tab')).map((x)=>x.textContent.replace(/\s+/g,' ').trim()).join('｜')`);
  const t0 = await clickTab('看成片');
  assert('V0 极简三步页签在（③ 看成片 可点）', t0 === 'ok', `seg=${seg0} tabs=${tabList0} click=${t0}`);
  await sleep(2500);

  // ── V：占位条 ──
  let s = await stripCards();
  assert('V1 墙顶有虚线占位条', s && !s.none, JSON.stringify(s).slice(0, 200));
  assert('V2 生成中恰 2 张占位卡（按单一张）', s.gen === 2, `gen=${s.gen} ${s.text.slice(0, 160)}`);
  assert('V3 失败恰 1 张红卡（3 天前那张不进卡）', s.fail === 1, `fail=${s.fail} ${s.text.slice(0, 160)}`);
  assert('V4 标题写「豆包正在生成中（2 张）」', /豆包正在生成中（2 张）/.test(s.text), s.text.slice(0, 200));
  assert('V5 超时那张标「比平时久，还没回片」', /比平时久，还没回片/.test(s.text), s.text.slice(0, 300));
  assert('V6 正常那张标「出片中」', /出片中/.test(s.text), s.text.slice(0, 300));
  assert('V7 角标说的是「投出多久」（未超时的按分、超时的按时）', /投出 \d+ 分/.test(s.text) && /投出 \d+\.\d 时/.test(s.text), s.text.match(/投出 [^ ]+ ?[时分]/g));
  assert('V8 多版单标「×2 版」', /×2 版/.test(s.text), s.text.slice(0, 400));
  assert('V9 重试次数标在（重试 1 次）', /重试 1 次/.test(s.text), s.text.slice(0, 400));
  assert('V10 失败栏带成因原文', /内容审核未通过/.test(s.text), s.text.slice(0, 400));
  assert('V11 失败栏写「共 2 张」并数出更早的 1 张', /板面失败待处理（1 张，共 2 张）/.test(s.text) && /另有 1 张更早的失败/.test(s.text), s.text.slice(0, 400));
  assert('V12 失败卡带「失败多久」角标', /失败 \d+ 分/.test(s.text), s.text.match(/失败 [^ ]+ ?[时分]?/g));
  assert('V13 生成中卡上不含失败成因（负向）', (s.text.match(/内容审核未通过/g) || []).length === 1, s.text.slice(0, 200));
  assert('V14 归属人显示「投：admin」（owner_name 真落到位）', /投：admin/.test(s.text), s.text.slice(0, 300));
  await shot('v1-wall-strip');
  // 占位条不许挤掉真成片：墙上仍有卡片
  const wallCtl = await js(`
    (() => { const p = document.querySelector('.ant-tabs-tabpane-active');
      const seg = Array.from(p.querySelectorAll('.ant-segmented-item')).map((x) => x.textContent.trim()).join('｜');
      return { seg, hasWall: /按素材（钩子）/.test(seg), stripAbove: !!p.querySelector('[data-inflight]') }; })()
  `);
  assert('V15 墙本身照常渲染（占位条只加不减：分组开关还在、且排在墙内）', wallCtl.hasWall && wallCtl.stripAbove, JSON.stringify(wallCtl));
  assert('V16 失败栏不再提供「去生产单处理」跳转', !/去生产单处理/.test(s.text), s.text.slice(0, 200));

  // ── W：投完把这一屏擦干净 ──
  await segClick('极简'); await sleep(1200);
  const w0 = await clickTab('投豆包');
  assert('W0 切到 ② 投豆包', w0 === 'ok', `click=${w0} tabs=${await js(`Array.from(document.querySelectorAll('.ant-tabs-tab')).map((x)=>x.textContent.replace(/\s+/g,' ').trim()).join('｜')`)}`);
  await sleep(1500);
  // 回 ① 勾一条 ready 的脚本
  await clickTab('脚本库'); await sleep(2000);
  const dbgRows = await js(`
    (() => Array.from(document.querySelectorAll('.ant-tabs-tabpane-active .ant-table-row')).slice(0,3).map((r)=>{
      const cb=r.querySelector('input[type=checkbox]');
      return 'vis='+(r.offsetParent!==null)+' cb='+(cb?('dis='+cb.disabled+' cls='+cb.closest('.ant-checkbox').className):'NONE')+' txt='+(r.innerText||'').replace(/\s+/g,' ').slice(0,26);
    }).join(' || ') || 'NO-ROW-IN-PANE:' + document.querySelectorAll('.ant-table-row').length)()
  `);
  console.log('DEBUG rows: ' + dbgRows);
  const picked = await js(`
    (() => {
      const rows = Array.from(document.querySelectorAll('.ant-tabs-tabpane-active .ant-table-row'))
        .filter((r) => r.offsetParent !== null);
      for (const r of rows) {
        const cb = r.querySelector('input[type=checkbox]');
        if (cb && !cb.disabled && !cb.checked) {
          cb.click();
          return (cb.checked ? 'ok:' : 'clicked-but-unchecked:') + (r.innerText || '').replace(/\s+/g, ' ').slice(0, 46);
        }
      }
      return 'no-row:' + rows.length;
    })()
  `);
  assert('W1 勾到一条脚本', String(picked).startsWith('ok'), picked);
  await sleep(800);
  await clickByRe('button', '下一步：投豆包');
  await sleep(1500);
  // 版数改成 3
  const setNum = await setVersion(3);
  assert('W2 版数填成 3', setNum === 'ok', setNum);
  await sleep(600);
  const pick = await pickCard();
  assert('W3 挑到一张三视图卡（Select 点开＋选中，卡数 +1）',
    setNum === 'ok' && pick.open === 'ok' && String(pick.opt).startsWith('ok') && pick.after === pick.before + 1,
    JSON.stringify(pick));
  await shot('w1-before-produce');

  // 拦一个「投出去了」的回执
  setProduceMode('ok'); resetHits();
  const btn = await clickByRe('.ant-tabs-tabpane-active button', '投豆包|投出去|投产');
  await sleep(3500);
  assert('W4 点了主按钮且请求被拦下（没打到真板）', btn === 'ok' && hitCount() === 1, `btn=${btn} hits=${hitCount()}`);
  const afterTab = await js(`
    (() => { const t = Array.from(document.querySelectorAll('.ant-tabs-tab-active'))
      .filter((e) => { const n = e.closest('.ant-tabs'); return n && !(n.parentElement && n.parentElement.closest('.ant-tabs')); });
      return t.map((x) => x.innerText.replace(/\\s+/g,' ').trim()).join('｜'); })()
  `);
  assert('W5 投出去后自动跳到 ③ 看成片', /看成片/.test(afterTab), afterTab);
  await sleep(2000);
  const stripAfter = await stripCards();
  assert('W6 跳过去的正是带占位卡的墙（两件事接上）', stripAfter && !stripAfter.none && stripAfter.gen >= 1, JSON.stringify(stripAfter).slice(0, 200));
  await shot('w2-after-produce-outputs');

  // 回 ② 核输入是否擦干净
  await clickTab('投豆包'); await sleep(1800);
  const cleared = await js(`
    (() => {
      const pane = document.querySelector('.ant-tabs-tabpane-active');
      const inp = Array.from(pane.querySelectorAll('input[role=spinbutton], .ant-input-number input')).find((e) => e.offsetParent !== null);
      return {
        chips: pane.querySelectorAll('button[aria-label="往前挪"]').length,
        total: inp ? inp.value : 'no-input',
        head: (pane.innerText.match(/这次要投的脚本（\\d+）/) || [''])[0],
      };
    })()
  `);
  assert('W7 三视图卡清空了', cleared.chips === 0, JSON.stringify(cleared));
  assert('W8 版数回到 1（不是停在上一批的 3）', cleared.total === '1', JSON.stringify(cleared));
  assert('W9 勾选的脚本也不再挂着', /这次要投的脚本（0）/.test(cleared.head), cleared.head);
  await shot('w3-produce-pane-cleared');

  // 负向：一张都没投出去 → 卡和号必须留着（改完重投靠它们）
  await clickTab('脚本库'); await sleep(1800);
  await js(`
    (() => { const r = Array.from(document.querySelectorAll('.ant-table-row')).filter((x) => x.offsetParent !== null);
      if (r[0]) { const cb = r[0].querySelector('input[type=checkbox]'); if (cb && !cb.disabled) cb.click(); } })()
  `);
  await sleep(800);
  await clickByRe('button', '下一步：投豆包'); await sleep(1500);
  const setNum2 = await setVersion(2);
  const pick2 = await pickCard();
  assert('W13 负向批也真挑上了卡（否则 W12 是空断）', setNum2 === 'ok' && pick2.after === pick2.before + 1, JSON.stringify({ setNum2, pick2 }).slice(0, 500));
  setProduceMode('blocked'); resetHits();
  await clickByRe('.ant-tabs-tabpane-active button', '投豆包|投出去|投产');
  await sleep(3000);
  assert('W10 负向请求也走拦截（真后端口径＝400）', hitCount() === 1, `hits=${hitCount()}`);
  const kept = await js(`
    (() => {
      const pane = document.querySelector('.ant-tabs-tabpane-active');
      const inp = Array.from(pane.querySelectorAll('.ant-input-number input')).find((e) => e.offsetParent !== null);
      const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab-active'))
        .filter((e) => { const n = e.closest('.ant-tabs'); return n && !(n.parentElement && n.parentElement.closest('.ant-tabs')); })
        .map((x) => x.innerText.replace(/\\s+/g, ' ').trim()).join('｜');
      return { chips: pane.querySelectorAll('button[aria-label="往前挪"]').length, total: inp ? inp.value : '?', tabs };
    })()
  `);
  assert('W11 全挡下时仍停在 ②（没跳 ③）', /投豆包/.test(kept.tabs), kept.tabs);
  assert('W12 全挡下时卡与版数留着', kept.chips >= 1 && kept.total === '2', JSON.stringify(kept));
  await shot('w4-produce-blocked-kept');

  setProduceMode('off');
  const pass = results.filter((r) => r.c).length;
  console.log(`\n==== ${pass}/${results.length} PASS ====`);
  results.filter((r) => !r.c).forEach((r) => console.log('  FAIL ' + r.n));
}

main()
  .catch((e) => { console.error('ERROR', e); process.exitCode = 1; })
  .finally(() => { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); });
