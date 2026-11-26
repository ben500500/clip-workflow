#!/usr/bin/env node
/* 失败删单竞态/权限/错误矩阵专项 CDP；只访问 5199 mock 与 9346 独立 Chrome。 */
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = process.env.SHOOT_BASE || 'http://127.0.0.1:5199';
const VARIANT = process.env.FD_VARIANT || 'current';
const OUT = `/tmp/shots-failed-delete-race${VARIANT === 'head' ? '-head' : ''}`;
const TOK = readFileSync(process.argv.slice(2).find((arg) => !arg.startsWith('--')) || '/tmp/asset-ui-token', 'utf8').trim();
const PORT = 9346;
const PROFILE = '/tmp/asset-shot-profile-failed-delete-race';
const KEY_ONLY = process.argv.includes('--key');
const SKIP_TIMEOUT = process.argv.includes('--skip-timeout');
mkdirSync(OUT, { recursive: true });
if (!TOK.startsWith('ey')) throw new Error('token 文件不对');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const flat = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();
let chrome;
try { await fetch(`http://127.0.0.1:${PORT}/json/version`); } catch {
  chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--window-size=1440,900', 'about:blank'], { stdio: 'ignore' });
}
let ws;
const pending = new Map();
const results = [];
const browserErrors = [];
let msgId = 0;
const assert = (name, condition, detail = '') => {
  const item = { name, pass: !!condition, detail: flat(detail).slice(0, 500) };
  results.push(item);
  console.log(`${item.pass ? 'PASS' : 'FAIL'} ${name}${item.pass ? '' : ` — ${item.detail}`}`);
};
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++msgId;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
const reset = async (scenario = 'default') => {
  const response = await fetch(`${BASE}/__fd/reset`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario }) });
  if (!response.ok) throw new Error(`reset ${response.status}`);
};
const control = async (patch) => {
  const response = await fetch(`${BASE}/__fd/control`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
  if (!response.ok) throw new Error(`control ${response.status}`);
};
const hits = () => { try { return readFileSync('/tmp/failed-delete-hits.log', 'utf8').trim().split('\n').filter(Boolean); } catch { return []; } };
const events = () => { try { return readFileSync('/tmp/failed-delete-events.jsonl', 'utf8').trim().split('\n').filter(Boolean).map((line) => JSON.parse(line)); } catch { return []; } };

async function main() {
  let target;
  for (let i = 0; i < 80 && !target; i++) {
    try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find((item) => item.type === 'page'); } catch {}
    if (!target) await sleep(200);
  }
  if (!target) throw new Error('CDP 未就绪');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve) => { ws.onopen = resolve; });
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const job = pending.get(message.id);
      pending.delete(message.id);
      message.error ? job.reject(new Error(JSON.stringify(message.error))) : job.resolve(message.result);
      return;
    }
    if (message.method === 'Runtime.exceptionThrown') browserErrors.push(message.params.exceptionDetails?.text || 'Runtime.exceptionThrown');
    if (message.method === 'Runtime.consoleAPICalled') {
      const text = (message.params.args || []).map((arg) => arg.value ?? arg.description ?? '').join(' ');
      if (/unmounted|Cannot update|not wrapped in act/i.test(text) || (/state update/i.test(text) && /React Router Future Flag/.test(text) === false)) browserErrors.push(text);
      if (message.params.type === 'error') console.log('BROWSER', text.slice(0, 500));
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
  const js = async (expression) => {
    const response = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (response.exceptionDetails) throw new Error(`JS ${JSON.stringify(response.exceptionDetails).slice(0, 300)}`);
    return response.result?.value;
  };
  const waitFor = async (expression, label, timeout = 15000) => {
    for (let i = 0; i < timeout / 150; i++) {
      if (await js(expression)) return true;
      await sleep(150);
    }
    console.log(`WAIT ${label}`);
    return false;
  };
  const waitHits = async (count, timeout = 10000) => {
    for (let i = 0; i < timeout / 100; i++) { if (hits().length >= count) return true; await sleep(100); }
    return false;
  };
  const waitGetStart = async (count) => {
    for (let i = 0; i < 100; i++) { if (events().filter((event) => event.kind === 'get-start').length >= count) return true; await sleep(100); }
    return false;
  };
  const shot = async (name) => {
    const { data } = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(`${OUT}/${VARIANT}-${name}.png`, Buffer.from(data, 'base64'));
  };
  const clickTestId = async (id) => js(`(() => { const e=document.querySelector('[data-testid="${id}"]'); if(!e||e.offsetParent===null)return false; e.click(); return true; })()`);
  const clickText = async (selector, text) => js(`(() => { const e=Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(x=>x.offsetParent!==null&&(x.innerText||x.textContent||'').replace(/\\s+/g,' ').trim()===${JSON.stringify(text)}); if(!e)return false; e.click(); return true; })()`);
  const cardExpr = (needle) => `!!Array.from(document.querySelectorAll('[data-inflight] div')).find(e=>e.offsetParent!==null&&(e.getAttribute('style')||'').includes('border: 1px solid')&&e.innerText.includes(${JSON.stringify(needle)}))`;
  const card = (needle) => js(cardExpr(needle));
  const wallText = () => js(`document.querySelector('[data-inflight]')?.innerText || ''`);
  const modalExpr = `!!Array.from(document.querySelectorAll('.ant-popconfirm')).find(e=>e.offsetParent!==null)`;
  const open = async (needle, label) => js(`(() => { const b=Array.from(document.querySelectorAll('button')).find(e=>{ if(e.offsetParent===null||(e.innerText||'').replace(/\\s+/g,' ').trim()!==${JSON.stringify(label)})return false; for(let p=e;p&&p!==document.body;p=p.parentElement){if((p.getAttribute('style')||'').includes('border: 1px solid')&&p.innerText.includes(${JSON.stringify(needle)}))return true;} return false;}); if(!b)return false; b.click(); return true; })()`);
  const confirm = async (label) => clickText('.ant-popconfirm button', label);
  const gotoHarness = async (needle = '内容审核未通过：角色卡不符') => {
    await send('Page.navigate', { url: `${BASE}/__fd/harness` });
    return waitFor(cardExpr(needle), 'harness card');
  };
  const gotoAssets = async () => {
    await send('Page.addScriptToEvaluateOnNewDocument', { source: `try{localStorage.setItem('auth_token',${JSON.stringify(TOK)})}catch{}` });
    await send('Page.navigate', { url: `${BASE}/assets` });
    await waitFor(`document.readyState==='complete'`, 'assets document');
    if (await js(`location.pathname==='/dashboard'`)) {
      await clickText('.ant-menu-item, .ant-menu-submenu-title, .ant-menu-title-content', '素材库');
      await waitFor(`location.pathname==='/assets'`, 'assets route');
    }
    await waitFor(`!!document.querySelector('.ant-segmented-item')`, 'view mode ready');
    await clickText('.ant-segmented-item', '极简');
    await waitFor(`Array.from(document.querySelectorAll('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn')).some(e=>e.innerText.includes('③ 看成片'))`, 'simple tabs ready');
    await clickText('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn', '③ 看成片');
    return waitFor(cardExpr('内容审核未通过：角色卡不符'), 'asset failed cards', 20000);
  };
  const reloadHarness = async (needle = '内容审核未通过：角色卡不符') => {
    await send('Page.reload', { ignoreCache: true });
    return waitFor(cardExpr(needle), 'harness reload');
  };

  // 关键 A/B：旧组件没有 removedRef，stale success 会让已删在途卡复活。
  await reset('mixed');
  await control({ gets: [{ snapshot: 'mixed', delay: 500 }], posts: [{ mode: 'ok' }] });
  await gotoHarness('ZZ902');
  assert('AB1 可打开真实在途删单确认', await open('ZZ902', '删掉这单') && await waitFor(modalExpr, 'generating confirm'));
  assert('AB2 确认在途删单', await confirm('删掉这单'));
  await sleep(1300);
  assert('AB3 stale success 不复活已删在途卡', !(await card('ZZ902')) && await card('ZZ901'), await wallText());
  await shot('ab-stale-generating');

  if (!KEY_ONLY) {
    // 删单前发出的慢 GET 与 limit 外快照。
    await reset();
    await gotoHarness();
    await control({ gets: [{ snapshot: 'capture', omit: ['00000000-0000-4000-8000-000000000001'], limit: 1, delay: 1300 }] });
    assert('R1 触发删单前慢 GET', await clickTestId('fd-reload') && await waitGetStart(2));
    assert('R2 慢 GET 在途时删第一张', await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, 'first confirm') && await confirm('删掉失败单'));
    await sleep(1700);
    const textAfterLimit = await wallText();
    assert('R3 已删 ID 在 limit 外时 failed_total 仍精确为 1', !(await card('内容审核未通过：角色卡不符')) && await card('生成失败：隔离验收错误路径') && !textAfterLimit.includes('共 2 张'), textAfterLimit);
    await shot('limit-outside-count');

    await reset('twoGenerating');
    await gotoHarness('ZZ901');
    await control({ gets: [{ snapshot: 'capture', omit: ['00000000-0000-4000-8000-000000000001'], limit: 1, delay: 1300 }] });
    await clickTestId('fd-reload');
    await waitGetStart(2);
    assert('R4 删两张在途中的第一张', await open('ZZ901', '删掉这单') && await waitFor(modalExpr, 'generating A confirm') && await confirm('删掉这单'));
    await sleep(1700);
    const generatingText = await wallText();
    assert('R5 已删 ID 在 limit 外时 inflight_total 仍精确为 1', !(await card('ZZ901')) && await card('ZZ902') && generatingText.includes('（1 张）'), generatingText);
    await shot('limit-outside-inflight');

    // 极端真实快照：删完后 GET 仍持续返回该 ID。
    await reset();
    await gotoHarness();
    await control({ gets: [{ snapshot: 'seed' }, { snapshot: 'seed' }] });
    assert('R6 删除第一张失败单', await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, 'extreme confirm') && await confirm('删掉失败单'));
    await sleep(500);
    assert('R7 删后 GET 仍返回已删 ID 也不复活', !(await card('内容审核未通过：角色卡不符')) && await card('生成失败：隔离验收错误路径'), await wallText());
    await shot('extreme-stale-snapshot');

    // 双击确认：延迟 POST 只能有一个请求。
    await reset();
    await gotoHarness();
    await control({ posts: [{ mode: 'ok', delay: 800 }] });
    assert('R8 双击确认弹窗', await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, 'double confirm') && js(`(() => { const b=Array.from(document.querySelectorAll('.ant-popconfirm button')).find(e=>e.innerText.trim()==='删掉失败单'); if(!b)return false; b.click(); b.click(); return true; })()`));
    await sleep(1600);
    assert('R9 双击/延迟 POST 只发一次', hits().filter((line) => line.startsWith('00000000-0000-4000-8000-000000000001 ')).length === 1 && !(await card('内容审核未通过：角色卡不符')), hits().join('|'));
    await shot('double-confirm');

    // 连续删两种卡，响应乱序。
    await reset('mixed');
    await gotoHarness('内容审核未通过：角色卡不符');
    await control({ posts: [{ mode: 'ok', delay: 650 }, { mode: 'ok', delay: 120 }] });
    assert('R10 连续删失败卡', await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, 'mixed failed confirm') && await confirm('删掉失败单') && await waitHits(1));
    assert('R11 再删在途卡', await open('ZZ902', '删掉这单') && await waitFor(modalExpr, 'mixed generating confirm') && await confirm('删掉这单') && await waitHits(2));
    await sleep(1400);
    const mixedText = await wallText();
    assert('R12 乱序完成后两类卡与计数归零', !(await card('内容审核未通过：角色卡不符')) && !(await card('ZZ902')) && !mixedText.includes('豆包正在生成中') && !mixedText.includes('板面失败待处理'), mixedText);
    await shot('consecutive-delete');

    // 403/404/409/500：保留卡片、显示后端原文、人工重试安全。
    for (const [mode, detail] of [['forbidden', '无投产权限'], ['missing', '生产单不存在'], ['conflict', '状态已变化'], ['server', '服务暂时不可用']]) {
      await reset();
      await reloadHarness();
      await control({ posts: [{ mode }] });
      assert(`E-${mode} 确认删单`, await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, `${mode} confirm`) && await confirm('删掉失败单'));
      const shown = await waitFor(`document.body.innerText.includes(${JSON.stringify(detail)})`, `${mode} error`);
      assert(`E-${mode} 卡片保留且错误提示明确`, shown && await card('内容审核未通过：角色卡不符') && hits().length === 1, await js(`document.body.innerText.replace(/\\s+/g,' ').trim().slice(-500)`));
      if (mode === 'forbidden') await shot('error-403');
      await control({ posts: [{ mode: 'ok' }] });
      assert(`E-${mode} 人工重试`, await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, `${mode} retry`) && await confirm('删掉失败单') && await waitHits(2));
      await sleep(500);
      assert(`E-${mode} 重试只补发一次且成功移除`, hits().length === 2 && hits().every((line) => line.startsWith('00000000-0000-4000-8000-000000000001 ')) && !(await card('内容审核未通过：角色卡不符')), hits().join('|'));
    }

    if (!SKIP_TIMEOUT) {
      await reset();
      await reloadHarness();
      await control({ posts: [{ mode: 'ok', delay: 62000 }, { mode: 'conflict', delay: 1500 }] });
      assert('E-timeout 发出删单请求', await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, 'timeout confirm') && await confirm('删掉失败单'));
      const timedOut = await waitFor(`document.body.innerText.includes('请求超时，请稍后重试')`, 'real axios timeout', 66000);
      assert('E-timeout 60s 超时后卡片保留且不自动重发', timedOut && await card('内容审核未通过：角色卡不符') && hits().length === 1, hits().join('|'));
      await shot('error-timeout');
      await control({ posts: [{ mode: 'conflict', delay: 1500 }] });
      assert('E-timeout 人工重试', await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, 'timeout retry') && await confirm('删掉失败单') && await waitHits(2));
      await sleep(2500);
      await clickTestId('fd-reload');
      await waitFor(`!(${cardExpr('内容审核未通过：角色卡不符')})`, 'timeout server reconciliation');
      assert('E-timeout 重试无第三次自动请求并以真实 GET 对账', hits().length === 2 && !(await card('内容审核未通过：角色卡不符')), hits().join('|'));
    }

    // material 无投产职能：权限来自 /auth/me，不是卡片状态。
    await reset();
    await control({ role: 'material', can_produce: false, can_review: false });
    await gotoAssets();
    const materialButtons = await js(`Array.from(document.querySelectorAll('button')).filter(b=>b.offsetParent!==null&&b.innerText.replace(/\\s+/g,' ').trim()==='删掉失败单').length`);
    assert('P1 material/can_produce=false 不显示可点击删单口', materialButtons === 0 && await card('内容审核未通过：角色卡不符'), `buttons=${materialButtons}`);
    await shot('material-no-delete');
    await control({ role: 'material', can_produce: true, can_review: false });
    await gotoAssets();
    const materialProduceButtons = await js(`Array.from(document.querySelectorAll('button')).filter(b=>b.offsetParent!==null&&b.innerText.replace(/\\s+/g,' ').trim()==='删掉失败单').length`);
    assert('P2 material 即使可投产也无审核删单权', materialProduceButtons === 0 && await card('内容审核未通过：角色卡不符'), `buttons=${materialProduceButtons}`);

    // 键盘与焦点。
    await reset();
    await gotoHarness();
    const focused = await js(`(() => { const b=Array.from(document.querySelectorAll('button')).find(e=>e.offsetParent!==null&&e.innerText.trim()==='删掉失败单'); b.focus(); b.click(); return true; })()`);
    await waitFor(modalExpr, 'keyboard confirm');
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await waitFor(`!(${modalExpr})`, 'escape close');
    const activeText = await js(`document.activeElement?.innerText || ''`);
    assert('K1 Escape 关闭且焦点回到触发按钮', focused && hits().length === 0 && await card('内容审核未通过：角色卡不符') && activeText.includes('删掉失败单'), `active=${activeText}`);
    await open('内容审核未通过：角色卡不符', '删掉失败单');
    await waitFor(modalExpr, 'enter confirm');
    await js(`Array.from(document.querySelectorAll('.ant-popconfirm button')).find(e=>e.innerText.trim()==='保留失败').focus()`);
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', text: '\r', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await sleep(400);
    assert('K2 Enter 激活取消不误删', hits().length === 0 && await card('内容审核未通过：角色卡不符'));
    await open('内容审核未通过：角色卡不符', '删掉失败单');
    await waitFor(modalExpr, 'enter ok confirm');
    await js(`Array.from(document.querySelectorAll('.ant-popconfirm button')).find(e=>e.innerText.trim()==='删掉失败单').focus()`);
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', text: '\r', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await sleep(600);
    assert('K3 Enter 激活确认且弹窗关闭', hits().length === 1 && !(await card('内容审核未通过：角色卡不符')) && !(await js(modalExpr)), hits().join('|'));
    await shot('keyboard-confirm');

    // 未确认时切页签/remount/卸载与迟到 GET。
    await reset();
    await gotoHarness();
    assert('L1 未确认切页签', await open('内容审核未通过：角色卡不符', '删掉失败单') && await waitFor(modalExpr, 'tab confirm') && await clickTestId('fd-tab-other'));
    await waitFor(`!(${modalExpr})`, 'tab closes confirm');
    await clickTestId('fd-tab-wall');
    await waitFor(cardExpr('内容审核未通过：角色卡不符'), 'wall remounted by tab');
    assert('L2 页签往返不误删', hits().length === 0 && await card('内容审核未通过：角色卡不符'));
    await open('内容审核未通过：角色卡不符', '删掉失败单');
    await waitFor(modalExpr, 'remount confirm');
    await clickTestId('fd-remount');
    await sleep(500);
    assert('L3 未确认 remount 不误删', hits().length === 0 && await card('内容审核未通过：角色卡不符') && !(await js(modalExpr)));
    await control({ gets: [{ snapshot: 'capture', delay: 1400 }] });
    const getsBeforeUnmount = events().filter((event) => event.kind === 'get-start').length;
    await clickTestId('fd-reload');
    await waitGetStart(getsBeforeUnmount + 1);
    await clickTestId('fd-unmount');
    await sleep(1800);
    assert('L4 组件卸载后迟到 GET 不更新/误删', await js(`document.querySelector('[data-testid="fd-mounted"]').dataset.value`) === '0' && hits().length === 0, browserErrors.join('|'));
    await clickTestId('fd-mount');
    await waitFor(cardExpr('内容审核未通过：角色卡不符'), 'mount after late get');
    assert('L5 重新挂载读取真实状态', await card('内容审核未通过：角色卡不符') && await card('生成失败：隔离验收错误路径'));

    await reset();
    await gotoAssets();
    await open('内容审核未通过：角色卡不符', '删掉失败单');
    await waitFor(modalExpr, 'browser back confirm');
    await send('Page.navigate', { url: `${BASE}/dashboard` });
    await waitFor(`location.pathname==='/dashboard'`, 'dashboard route');
    await js(`history.back()`);
    await waitFor(`location.pathname==='/assets' || location.pathname==='/dashboard'`, 'back history route');
    await sleep(800);
    if (await js(`location.pathname==='/dashboard'`)) {
      await clickText('.ant-menu-item, .ant-menu-submenu-title, .ant-menu-title-content', '素材库');
      await waitFor(`location.pathname==='/assets'`, 'assets after browser back');
    }
    if (!(await card('内容审核未通过：角色卡不符'))) {
      await clickText('.ant-segmented-item', '极简');
      await sleep(400);
      await clickText('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn', '③ 看成片');
      await waitFor(cardExpr('内容审核未通过：角色卡不符'), 'outputs after browser back');
    }
    assert('L6 未确认浏览器返回不误删', hits().length === 0 && await card('内容审核未通过：角色卡不符'), hits().join('|'));
    await open('内容审核未通过：角色卡不符', '删掉失败单');
    await waitFor(modalExpr, 'simple tab confirm');
    await clickText('.ant-tabs .ant-tabs-nav .ant-tabs-tab-btn', '① 脚本库');
    await sleep(500);
    assert('L7a 真实极简页签切换本身不误删', hits().length === 0 && await js(`document.body.innerText.includes('① 脚本库')`), hits().join('|'));
    assert('L7b 真实极简页签切换关闭未确认弹窗', !(await js(modalExpr)), '切到①脚本库后删单 Popconfirm 仍悬浮显示');
    await shot('unconfirmed-tab-safe');
    assert('L8 无卸载迟到状态更新/运行时异常', browserErrors.length === 0, browserErrors.join('|'));
  }

  const failed = results.filter((result) => !result.pass);
  const summary = { variant: VARIANT, keyOnly: KEY_ONLY, pass: results.length - failed.length, total: results.length, results, browserErrors, screenshots: OUT };
  writeFileSync(`${OUT}/${VARIANT}-results.json`, JSON.stringify(summary, null, 2));
  console.log(`RESULT ${summary.pass}/${summary.total}`);
  if (failed.length) process.exitCode = 1;
}

main().catch((error) => { console.error(error); process.exitCode = 1; }).finally(() => {
  try { ws?.close(); } catch {}
  if (chrome) try { chrome.kill('SIGTERM'); } catch {}
});
