#!/usr/bin/env node
/*
 * 极简模式（S1+S2）· CDP 真截图门（2026-11-23 收尾方案 §4）
 *
 * 覆盖判据：
 *   A. 极简主路径 UI：Segmented 极简|完整 存在、切到极简后零页签；关键四颗按钮
 *      （导入钩子视频并反推 / 上传脚本文件 / 手写脚本 / 投豆包）在 DOM 上都能定位。
 *   B. 偏好接口 pending 超时兜底（新补丁 52e61ee 要防的空白页）：拦截
 *      GET /assets/ui/preferences 让它挂 15s，页面应在 ≤3.5s 内出现五环 Tab
 *      （2.5s 定值兜底落 'full'）——不是永远空白/Spin。
 *   C. material 角色（无 canReview）：主按钮文案是「投豆包」而不是
 *      「轻量过审并投豆包」；默认极简（后端按角色映射）。
 *   D. 旧五环回归（6 个 Tab 全在）：admin 默认 full，六个 Tab 的 label 逐字对
 *      「① 导入」「② 素材与文案」「③ 文案审核」「④ 生产与投板」「⑤ 成片墙」「后台任务」。
 *
 * 全程只读（不点「定稿」「投豆包」真花钱），零写操作。
 * 用法：node shoot-simple.mjs <admin-token-file> <material-token-file>
 *   默认 /tmp/.cdp_tok_local + /tmp/.cdp_tok_material
 *   跑之前请清一次 user_preferences（`DELETE FROM user_preferences`）以便 admin
 *   从「未存偏好 → 后端按角色默认＝full」起步。
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
// 本机 clip 栈（frontend 127.0.0.1:3000）；端口避开 9223（用户隧道口）与 9341（capture-guide-frames）
const BASE = process.env.SHOOT_BASE || 'http://127.0.0.1:3000';  // 现网复验传 SHOOT_BASE=http://192.168.1.163
const OUT = '/tmp/shots-simple';
mkdirSync(OUT, { recursive: true });
const ADMIN_TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_local', 'utf8').trim();
let MAT_TOK = '';
try { MAT_TOK = readFileSync(process.argv[3] || '/tmp/.cdp_tok_material', 'utf8').trim(); } catch {}
if (!ADMIN_TOK.startsWith('ey')) { console.error('admin token 文件不对'); process.exit(2); }

const CDP_PORT = 9343;
const USER_DATA = '/tmp/asset-shot-profile-simple';

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
const assert = (n, c, d = '') => { results.push({ n, c: !!c }); console.log(`${c ? 'PASS' : 'FAIL'} ${n}${c ? '' : ' — ' + flat(d).slice(0, 220)}`); };

let hangUntil = 0;   // 时间戳：命中的 preferences 请求挂起到该时刻
let hungCount = 0;   // 本轮实际挂起了几个请求（0＝拦截没生效，判据不成立）
const HANG_URL = '/api/assets/ui/preferences';

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
    if (m.method === 'Fetch.requestPaused') {
      const url = m.params.request.url;
      const shouldHang = Date.now() < hangUntil && url.includes(HANG_URL);
      if (shouldHang) hungCount++;
      // 挂起＝什么都不回（continue 也不发），fetch 会永远 pending
      if (!shouldHang) {
        send('Fetch.continueRequest', { requestId: m.params.requestId }).catch(() => {});
      }
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' + HANG_URL, requestStage: 'Request' }] });

  const js = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 150)}` : r.result?.value;
  };
  const shot = async (n) => {
    const { data } = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(`${OUT}/${n}.png`, Buffer.from(data, 'base64'));
  };
  // 每次换 token 要先把 addScriptToEvaluateOnNewDocument 撤钩再重挂（旧页的 token 会盖新页）
  let injectId = null;
  const setToken = async (tok) => {
    if (injectId) { try { await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: injectId }); } catch {} injectId = null; }
    try {
      const { identifier } = await send('Page.addScriptToEvaluateOnNewDocument', {
        source: `try{localStorage.setItem('auth_token', ${JSON.stringify(tok)})}catch(e){}`,
      });
      injectId = identifier;
    } catch {}
  };
  const goto = async (path) => {
    await send('Page.navigate', { url: BASE + path });
    for (let i = 0; i < 40; i++) {
      const rs = await js('document.readyState');
      if (rs === 'complete') break;
      await sleep(120);
    }
  };
  // 浏览器端不能用 Node 的 flat()，全部走内联 replace
  const grabTabs = async () => js(`
    (() => Array.from(document.querySelectorAll('.ant-tabs-tab')).map(x => x.textContent.replace(/\\s+/g, ' ').trim()).join('｜'))()
  `);
  const grabCards = async () => js(`
    (() => Array.from(document.querySelectorAll('.ant-card-head-title')).map(x => x.textContent.replace(/\\s+/g, ' ').trim()).join('｜'))()
  `);
  const grabButtons = async () => js(`
    (() => {
      const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
      const bs = Array.from(document.querySelectorAll('button')).map(x => ({ t: norm(x.textContent), d: !!x.disabled }));
      return JSON.stringify({
        importHook: bs.find(b => b.t === '导入钩子视频并反推') || null,
        uploadScript: bs.find(b => b.t.includes('上传脚本文件')) || null,
        writeScript: bs.find(b => b.t === '手写脚本') || null,
        dispatch: bs.filter(b => b.t.includes('投豆包')).map(b => ({ t: b.t, d: b.d })),
        anyTabs: document.querySelectorAll('.ant-tabs').length,
      });
    })()
  `);
  const parseJson = (s) => { try { return typeof s === 'string' ? JSON.parse(s) : s; } catch { return null; } };

  // ───────────────────────────────────────────────────────────
  // A + D. admin 默认 full：Segmented 存在、六 Tab 齐、点极简后零页签＋卡片＋按钮
  // ───────────────────────────────────────────────────────────
  await setToken(ADMIN_TOK);
  await goto('/assets');
  await sleep(2000);
  const seg = await js(`(() => {
    const s = document.querySelector('.ant-segmented');
    if (!s) return 'NO-SEGMENTED';
    return Array.from(s.querySelectorAll('.ant-segmented-item-label')).map(x=>x.textContent.trim()).join('|');
  })()`);
  assert('A1 Segmented 极简|完整 存在', seg === '极简|完整', seg);
  const tabsBefore = await grabTabs();
  const wantTabs = ['① 导入', '② 素材与文案', '③ 文案审核', '④ 生产与投板', '⑤ 成片墙', '后台任务'];
  const missing = wantTabs.filter((w) => !String(tabsBefore).includes(w));
  assert('D1 admin 默认 full：旧五环 6 Tab 全在（回归）', missing.length === 0, `tabs=${tabsBefore}`);
  shot('a1-admin-full-default');

  // 点 Segmented 里的「极简」→ 切到极简视图
  const click = await js(`(() => {
    const items = Array.from(document.querySelectorAll('.ant-segmented-item'));
    const hit = items.find(x => x.textContent.trim() === '极简');
    if (!hit) return 'no-item';
    hit.click();
    return 'ok';
  })()`);
  assert('A2 Segmented 「极简」点击成功', click === 'ok', click);
  await sleep(2500);   // 等 saveUiPreferences 落库＋React 重渲染
  const cards = await grabCards();
  const btns = parseJson(await grabButtons());
  assert('A3 切到极简后 .ant-tabs = 0（零页签）', btns && btns.anyTabs === 0, `anyTabs=${btns && btns.anyTabs}`);
  assert('A4 极简视图含「脚本库」卡', /脚本库/.test(cards), cards);
  assert('A5 极简视图含「投豆包」卡', /投豆包/.test(cards), cards);
  assert('A6 极简主按钮四颗齐全（导入钩子／上传脚本／手写／投豆包）',
    !!(btns && btns.importHook && btns.uploadScript && btns.writeScript && btns.dispatch && btns.dispatch.length > 0),
    JSON.stringify(btns));
  shot('a2-admin-simple');

  // ───────────────────────────────────────────────────────────
  // C. material 角色：无 canReview → 「轻量过审并投豆包」看不到；默认极简
  // ───────────────────────────────────────────────────────────
  if (MAT_TOK) {
    await setToken(MAT_TOK);
    await goto('/assets');
    await sleep(3500);   // 等偏好接口回；material 默认＝极简（后端给）
    const matMode = await js(`(() => {
      const seg = document.querySelector('.ant-segmented-item-selected');
      return seg ? seg.textContent.trim() : 'NO-SEL';
    })()`);
    assert('C1 material 默认极简（后端角色映射）', matMode === '极简', matMode);
    const mBtns = parseJson(await grabButtons());
    assert('C2 material 看不到「轻量过审并投豆包」（无审核职能）',
      !!(mBtns && mBtns.dispatch && !mBtns.dispatch.some(b => b.t.includes('轻量过审'))),
      JSON.stringify(mBtns && mBtns.dispatch));
    assert('C3 material 主按钮文案含「投豆包」',
      !!(mBtns && mBtns.dispatch && mBtns.dispatch.some(b => b.t.includes('投豆包'))),
      JSON.stringify(mBtns && mBtns.dispatch));
    shot('c-material-role');
  } else {
    assert('C0 material token 缺（跳过 C 段）', true);
  }

  // ───────────────────────────────────────────────────────────
  // B. 偏好 pending 超时兜底：拦截 /api/assets/ui/preferences 让它挂 15s
  //    期望页面在 ≤3.5s 内出现五环 Tab（2.5s 定值兜底），不是永远 Spin/空白
  // ───────────────────────────────────────────────────────────
  await setToken(ADMIN_TOK);
  hangUntil = Date.now() + 15000;
  hungCount = 0;
  const t0 = Date.now();
  await goto('/assets');
  let tabsSeenAt = -1;
  let lastDiag = '未采样';
  for (let i = 0; i < 45; i++) {   // 最多轮 9s
    const n = await js(`document.querySelectorAll('.ant-tabs-tab').length`);
    if (typeof n === 'number' && n >= 6) { tabsSeenAt = Date.now() - t0; break; }
    lastDiag = await js(`(() => {
      const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
      const seg = document.querySelector('.ant-segmented-item-selected');
      const spin = /正在读取你的界面偏好/.test(document.body.innerText);
      return JSON.stringify({url: location.pathname, seg: seg ? norm(seg.textContent) : '-',
        spin, tabs: document.querySelectorAll('.ant-tabs-tab').length, ready: document.readyState});
    })()`) || lastDiag;
    await sleep(200);
  }
  const elapsed = Date.now() - t0;
  hangUntil = 0;   // 解除挂起，剩下请求放行
  assert('B1 偏好 pending 时 ≤3.5s 内出五环（不空白）',
    tabsSeenAt >= 0 && tabsSeenAt <= 3500,
    `耗时=${tabsSeenAt}ms 总耗时=${elapsed}ms 挂起命中=${hungCount} 末帧=${JSON.stringify(lastDiag)}`);
  shot('b1-timeout-fallback');

  const summary = results.reduce((a, r) => { a[r.c ? 'pass' : 'fail']++; return a; }, { pass: 0, fail: 0 });
  console.log(`\n总计 ${summary.pass}/${results.length} PASS，截图在 ${OUT}/`);
  writeFileSync(`${OUT}/report.json`, JSON.stringify(results, null, 2));
  process.exitCode = summary.fail ? 1 : 0;
}

main().catch((e) => { console.error('CDP 脚本异常', e); process.exitCode = 3; })
  .finally(async () => { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); });
