#!/usr/bin/env node
/* 失败豆包生产单删单：独立 CDP 交互门（不写本地/生产数据库） */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = process.env.SHOOT_BASE || 'http://127.0.0.1:5199';
const OUT = '/tmp/shots-failed-delete';
const TOK = readFileSync(process.argv[2] || '/tmp/asset-ui-token', 'utf8').trim();
const CDP_PORT = 9346;
const USER_DATA = '/tmp/asset-shot-profile-failed-delete';
const MODE = '/tmp/failed-delete-mode.txt';
const REFRESH_MODE = '/tmp/failed-delete-refresh-mode.txt';
const HITS = '/tmp/failed-delete-hits.log';
mkdirSync(OUT, { recursive: true });
if (!TOK.startsWith('ey')) throw new Error('token 文件不对');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${USER_DATA}`,
  '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' });

let ws;
const pending = new Map();
let msgId = 0;
const results = [];
const assert = (n, c, d = '') => {
  results.push({ n, c: !!c });
  console.log(`${c ? 'PASS' : 'FAIL'} ${n}${c ? '' : ' — ' + flat(d).slice(0, 260)}`);
};
const send = (m, p = {}) => new Promise((res, rej) => {
  const id = ++msgId;
  pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method: m, params: p }));
});

async function main() {
  let target = null;
  for (let i = 0; i < 60 && !target; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json`)).json();
      target = list.find((x) => x.type === 'page');
    } catch {}
    if (!target) await sleep(250);
  }
  if (!target) throw new Error('CDP 未就绪');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error).slice(0, 200))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.consoleAPICalled') {
      const text = (m.params.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
      if (text.startsWith('NAVTRACE') || m.params.type === 'error') console.log('BROWSER', m.params.type, text.slice(0, 300));
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });

  const js = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(`JS: ${JSON.stringify(r.exceptionDetails).slice(0, 240)}`);
    return r.result?.value;
  };
  const waitFor = async (expr, label, timeout = 12000) => {
    for (let i = 0; i < timeout / 200; i++) {
      if (await js(expr)) return true;
      await sleep(200);
    }
    console.log(`WAIT ${label}`);
    return false;
  };
  const shot = async (n) => {
    const { data } = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(`${OUT}/${n}.png`, Buffer.from(data, 'base64'));
  };
  const setToken = (tok) => send('Page.addScriptToEvaluateOnNewDocument', {
    source: `try{localStorage.setItem('auth_token', ${JSON.stringify(tok)})}catch(e){}`,
  });
  const goto = async (path) => {
    await send('Page.navigate', { url: BASE + path });
    await waitFor(`document.readyState === 'complete'`, 'document complete');
  };
  const clickByText = (sel, text) => js(`
    (() => {
      const wanted = ${JSON.stringify(text)};
      const el = Array.from(document.querySelectorAll(${JSON.stringify(sel)}))
        .find((e) => e.offsetParent !== null && (e.innerText || e.textContent || '').replace(/\\s+/g,' ').trim() === wanted);
      if (!el) return false;
      el.click(); return true;
    })()
  `);
  const clickTab = async (text) => {
    if (await clickByText('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn', text)) return true;
    return clickByText('.ant-tabs .ant-tabs-nav .ant-tabs-tab', text);
  };
  const cardButton = (needle) => js(`
    (() => {
      const b = Array.from(document.querySelectorAll('button')).find((e) => {
        if (e.offsetParent === null || (e.innerText || e.textContent || '').replace(/\\s+/g,' ').trim() !== '删掉失败单') return false;
        for (let p = e; p && p !== document.body; p = p.parentElement) {
          if ((p.getAttribute('style') || '').includes('border: 1px solid rgb(255, 204, 199)')) {
            return p.innerText.includes(${JSON.stringify(needle)});
          }
        }
        return false;
      });
      if (!b) return false;
      b.click(); return true;
    })()
  `);
  const cardExistsExpr = (needle) => `
    (() => Array.from(document.querySelectorAll('[data-inflight] div')).some((e) =>
      e.offsetParent !== null && (e.getAttribute('style') || '').includes('border: 1px solid rgb(255, 204, 199)') &&
      e.innerText.includes(${JSON.stringify(needle)})))()
  `;
  const cardExists = (needle) => js(cardExistsExpr(needle));
  const modalVisibleExpr = `!!Array.from(document.querySelectorAll('.ant-popconfirm')).find((e) => e.offsetParent !== null && e.innerText.includes('只把这张失败卡从墙上移除'))`;

  await fetch(BASE + '/__fd/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  await setToken(TOK);
  await goto('/assets');
  await js(`localStorage.setItem('auth_token', ${JSON.stringify(TOK)})`);
  await send('Page.reload', { ignoreCache: true });
  await waitFor(`document.readyState === 'complete'`, 'authenticated reload');
  await goto('/assets');
  await sleep(2200);
  console.log('DEBUG after-goto', await js('location.href'));
  if (await js(`location.pathname === '/dashboard'`)) {
    const entered = await clickByText('.ant-menu-item, .ant-menu-submenu-title, .ant-menu-title-content', '素材库');
    console.log('DEBUG click-sidebar-assets', entered);
    await waitFor(`location.pathname === '/assets'`, 'sidebar assets route');
    await sleep(1200);
  }
  await clickByText('.ant-segmented-item', '极简');
  await sleep(1200);
  console.log('DEBUG after-simple', await js('location.href'));
  await clickTab('③ 看成片');
  console.log('DEBUG after-tab', await js('location.href'));
  const wallReady = await waitFor(`document.querySelector('[data-inflight]') && Array.from(document.querySelectorAll('button')).some((b) => b.offsetParent !== null && b.innerText.replace(/\\s+/g,' ').trim() === '删掉失败单')`, 'failed delete buttons');
  assert('FD1 失败卡显示「删掉失败单」', wallReady, await js(`document.body.innerText.replace(/\\s+/g,' ').trim().slice(-1200)`));
  const buttons = await js(`Array.from(document.querySelectorAll('button')).filter((b) => b.offsetParent !== null && b.innerText.replace(/\\s+/g,' ').trim() === '删掉失败单').length`);
  assert('FD2 两张失败卡各有独立删单口', buttons === 2, `buttons=${buttons}`);
  await shot('fd1-two-failed-cards');

  assert('FD3 点「保留失败」不提交删除', await cardButton('内容审核未通过：角色卡不符'));
  assert('FD4 删除确认说明保留成因/审计/号池', await waitFor(modalVisibleExpr, 'confirm explanation'));
  assert('FD5 取消确认后失败卡仍在', await clickByText('.ant-popconfirm button', '保留失败') && await waitFor(`!(${modalVisibleExpr})`, 'confirm closed') && await cardExists('内容审核未通过：角色卡不符'));
  const hitsAfterCancel = existsSync(HITS) ? readFileSync(HITS, 'utf8').split('\n').filter(Boolean).length : 0;
  assert('FD6 取消确认没有调用删单接口', hitsAfterCancel === 0, `hits=${hitsAfterCancel}`);

  writeFileSync(MODE, 'error');
  assert('FD7 第二张卡可进入删单确认', await cardButton('生成失败：隔离验收错误路径'));
  await waitFor(modalVisibleExpr, 'error confirm');
  assert('FD8 确认删除触发接口', await clickByText('.ant-popconfirm button', '删掉失败单'));
  const errorShown = await waitFor(`document.body.innerText.includes('删单失败：隔离验收错误路径')`, 'error toast');
  assert('FD9 接口报错时卡片不消失且提示错误', errorShown && await cardExists('生成失败：隔离验收错误路径'));

  writeFileSync(MODE, 'ok');
  // stale＝删单后的刷新故意返回删单前旧快照；已删 ID 必须被 removedRef 永久过滤。
  writeFileSync(REFRESH_MODE, 'stale');
  assert('FD10 第一张卡再次进入删单确认', await cardButton('内容审核未通过：角色卡不符'));
  await waitFor(modalVisibleExpr, 'success confirm');
  await shot('fd2-delete-confirm');
  assert('FD11 确认删除第一张失败单', await clickByText('.ant-popconfirm button', '删掉失败单'));
  const gone = await waitFor(`!(${cardExistsExpr('内容审核未通过：角色卡不符')})`, 'first failed card gone');
  assert('FD12 对应失败卡立即消失', gone);
  assert('FD13 另一张失败卡不受影响', await cardExists('生成失败：隔离验收错误路径'));
  const successShown = await waitFor(`document.body.innerText.includes('已删单：失败卡从墙上消失，台账仍可审计')`, 'success toast');
  assert('FD14 显示删单成功说明', successShown);
  const remaining = await js(`Array.from(document.querySelectorAll('button')).filter((b) => b.offsetParent !== null && b.innerText.replace(/\\s+/g,' ').trim() === '删掉失败单').length`);
  assert('FD15 删除后只剩另一张失败卡', remaining === 1, `remaining=${remaining}`);
  await sleep(800);
  assert('FD15A 删单前发出的旧 GET 成功响应没有让卡片复活', !(await cardExists('内容审核未通过：角色卡不符')) && await cardExists('生成失败：隔离验收错误路径'));
  writeFileSync(REFRESH_MODE, 'ok');
  const hits = existsSync(HITS) ? readFileSync(HITS, 'utf8').split('\n').filter(Boolean) : [];
  assert('FD16 只发生一次成功删除与一次失败删除', hits.length === 2 && hits[0].endsWith(' error') && hits[1].endsWith(' ok'), hits.join('|'));
  await shot('fd3-one-failed-card-left');

  // P1 回归：删单已经成功，但紧接着的 GET 刷新失败时，也必须就地消失且不能复活。
  writeFileSync(REFRESH_MODE, 'error');
  assert('FD17 刷新失败模式下仍可删除最后一张失败单', await cardButton('生成失败：隔离验收错误路径'));
  await waitFor(modalVisibleExpr, 'refresh-error confirm');
  assert('FD18 确认最后一张失败单', await clickByText('.ant-popconfirm button', '删掉失败单'));
  const goneDespiteRefresh = await waitFor(`!(${cardExistsExpr('生成失败：隔离验收错误路径')})`, 'last card gone despite refresh error');
  assert('FD19 删单成功但刷新失败，卡片仍立即消失', goneDespiteRefresh);
  const refreshWarning = await waitFor(`document.body.innerText.includes('已删单不会复活')`, 'stale warning');
  assert('FD20 明确提示刷新失败且已删单不会复活', refreshWarning);
  await sleep(800);
  assert('FD21 等待后旧卡没有复活', !(await cardExists('生成失败：隔离验收错误路径')));
  const finalHits = existsSync(HITS) ? readFileSync(HITS, 'utf8').split('\n').filter(Boolean) : [];
  assert('FD22 刷新失败没有诱发重复删单请求', finalHits.length === 3 && finalHits[0].endsWith(' error') && finalHits[1].endsWith(' ok') && finalHits[2].endsWith(' ok'), finalHits.join('|'));
  await shot('fd4-refresh-failed-card-stays-gone');
  writeFileSync(REFRESH_MODE, 'ok');

  const failed = results.filter((r) => !r.c);
  console.log(`RESULT ${results.length - failed.length}/${results.length}`);
  if (failed.length) process.exitCode = 1;
}

main().catch((e) => { console.error(e); process.exitCode = 1; }).finally(() => {
  try { ws?.close(); } catch {}
  try { chrome.kill('SIGTERM'); } catch {}
});
