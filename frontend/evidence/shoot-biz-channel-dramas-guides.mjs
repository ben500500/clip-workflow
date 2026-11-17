#!/usr/bin/env node
/*
 * 业务区动画推进③ · 视频号列表＋剧目库「怎么用」分步动画 · 现网 CDP 实拍（2026-11-17）
 *  姿势照 shoot-biz-dedup-guides.mjs：入口 span 文本匹配、弹层取 .ant-modal 全容器（X46）、
 *  剥 tg- 样式后断言；话术逐字抄 ChannelAccounts.tsx / DramaLibrary.tsx（X44/F72）。
 *  帧模式：loopCount 探针＝「img 双快照 src 变化」检测。
 *  token 注入用 navigate→setItem→reload 三步（X53）。
 *
 *  全程零写操作。用法：node shoot-biz-channel-dramas-guides.mjs <token 文件>
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = 'http://192.168.1.163';
const OUT = '/tmp/shots-biz-channel-dramas';
mkdirSync(OUT, { recursive: true });
const TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_adm', 'utf8').trim();
if (!TOK.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9342', '--user-data-dir=/tmp/asset-shot-profile-ch-dramas',
  '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' });

let ws; const pending = new Map(); let msgId = 0;
const send = (m, p = {}) => new Promise((res, rej) => { const id = ++msgId; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method: m, params: p })); });
const results = [];
const assert = (n, c, d = '') => { results.push({ n, c: !!c }); console.log(`${c ? 'PASS' : 'FAIL'} ${n}${c ? '' : ' — ' + flat(d).slice(0, 200)}`); };

async function main() {
  let t = null;
  for (let i = 0; i < 60 && !t; i++) {
    try { const l = await (await fetch('http://127.0.0.1:9342/json')).json(); t = l.find((x) => x.type === 'page'); } catch {}
    if (!t) await sleep(250);
  }
  if (!t) throw new Error('CDP 未就绪');
  ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error('x')) : p.res(m.result); } };
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
  const js = async (e) => { const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 150)}` : r.result?.value; };
  const shot = async (n) => { const { data } = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${OUT}/${n}.png`, Buffer.from(data, 'base64')); };

  const gotoAuthed = async (path) => {
    await send('Page.navigate', { url: `${BASE}${path}` });
    await sleep(3000);
    await js(`try{localStorage.setItem('auth_token', ${JSON.stringify(TOK)})}catch(e){}`);
    await send('Page.navigate', { url: `${BASE}${path}` });
    await sleep(4500);
  };
  const body = async () => {
    const t = String(await js(`document.querySelector('.ant-modal')?.innerText || ''`));
    return flat(t.replace(/<style>[\s\S]*?<\/style>/g, ''));
  };
  const openGuide = async (label) =>
    js(`(() => { const b=Array.from(document.querySelectorAll('span')).find(x=>x.textContent.includes('${label}')&&x.textContent.includes('怎么用')); if(!b) return 'no-entry'; b.click(); return 'ok'; })()`);
  const gotoStepDot = async (i) => {
    for (let k = 0; k < 4; k++) {
      await js(`(() => { const d=document.querySelectorAll('.ant-modal .tg-dots button')[${i}]; d&&d.click(); })()`);
      await sleep(1200);
      const onIdx = Number(await js(`[...document.querySelectorAll('.ant-modal .tg-dots button')].findIndex(b=>b.className.includes('on'))+1`));
      if (onIdx === i + 1) return;
    }
  };
  const loopCount = async () => {
    const a = await js(`(() => { const m=document.querySelector('.ant-modal'); const i=[...m.querySelectorAll('.tg-stage img')].map(x=>x.src); return JSON.stringify(i); })()`);
    await sleep(500);
    const b = await js(`(() => { const m=document.querySelector('.ant-modal'); const i=[...m.querySelectorAll('.tg-stage img')].map(x=>x.src); return JSON.stringify(i); })()`);
    return a !== b ? 1 : 0;
  };
  const closeGuide = async () => { await js(`(() => { const x=document.querySelector('.ant-modal-close'); x&&x.click(); })()`); await sleep(500); };

  // ═══ C 组 · 视频号列表（/channel-accounts · ChannelAccountsGuide · biz-channel） ═══
  await gotoAuthed('/channel-accounts');
  assert('C-A0 页面渲染（「视频号列表」标题在位）', String(await js(`Array.from(document.querySelectorAll('h4,.ant-card-head')).some(b=>b.textContent.includes('视频号列表'))`)) === 'true');
  assert('C-A1 入口「❓ 视频号列表怎么用」在位且点开', (await openGuide('视频号列表怎么用')) === 'ok');
  await sleep(1500);
  shot('C-open');
  const cBody = await body();
  assert('C-A2 标题+第1步「先建剧场」真话术', cBody.includes('视频号列表怎么用 · 60 秒动画版') && cBody.includes('先建剧场'), cBody.slice(0, 160));
  assert('C-A2b 第1步帧播放器在逐帧切换（12 帧×0.36s）', Number(await loopCount()) > 0);
  await gotoStepDot(1); await sleep(800); shot('C-step2');
  assert('C-A3 第2步「新增视频号列表」+「平台侧唯一标识（选填）」逐字', (await body()).includes('新增视频号列表') && (await body()).includes('平台侧唯一标识（选填）'), (await body()).slice(0, 160));
  assert('C-A3b 第2步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(2); await sleep(800); shot('C-step3');
  assert('C-A4 第3步「数据分析」+「确认删除该视频号列表？」真字面', (await body()).includes('数据分析') && (await body()).includes('确认删除该视频号列表？'), (await body()).slice(0, 160));
  assert('C-A4b 第3步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await closeGuide();

  // ═══ D 组 · 剧目库（/dramas · DramasGuide · biz-dramas） ═══
  await gotoAuthed('/dramas');
  assert('D-A0 页面渲染（「剧目库」标题在位）', String(await js(`Array.from(document.querySelectorAll('h4,.ant-card-head')).some(b=>b.textContent.includes('剧目库'))`)) === 'true');
  assert('D-A1 入口「❓ 剧目库怎么用」在位且点开', (await openGuide('剧目库怎么用')) === 'ok');
  await sleep(1500);
  shot('D-open');
  const dBody = await body();
  assert('D-A2 标题+第1步「三种录入口」真话术', dBody.includes('剧目库怎么用 · 60 秒动画版') && dBody.includes('三种录入口'), dBody.slice(0, 160));
  assert('D-A2b 第1步帧播放器在逐帧切换', Number(await loopCount()) > 0);
  await gotoStepDot(1); await sleep(800); shot('D-step2');
  assert('D-A3 第2步「新增剧目」+「话题大方向」逐字', (await body()).includes('新增剧目') && (await body()).includes('话题大方向'), (await body()).slice(0, 160));
  assert('D-A3b 第2步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(2); await sleep(800); shot('D-step3');
  assert('D-A4 第3步「搜索名称/ID」+「删除「剧名」？」真字面', (await body()).includes('搜索名称/ID') && (await body()).includes('删除「剧名」？'), (await body()).slice(0, 160));
  assert('D-A4b 第3步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await closeGuide();

  const pass = results.filter((r) => r.c).length;
  console.log(`\\n=== ${pass}/${results.length} PASS ===`);
  if (pass !== results.length) process.exit(1);
}

main().then(() => { try { ws.close(); } catch {} process.exit(0); }).catch((e) => { console.error('FATAL', e); process.exit(1); });
