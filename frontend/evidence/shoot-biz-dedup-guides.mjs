#!/usr/bin/env node
/*
 * 业务区动画推进② · 去重处理＋变体矩阵＋资源下载「怎么用」分步动画 · 现网 CDP 实拍（2026-11-16）
 *  姿势照 shoot-biz-slice-guides.mjs：入口用 span 文本匹配、弹层取 .ant-modal 全容器（X46，
 *  标题在 header 不在 body；教程内嵌 <style> 会混 CSS 串，断言前先剥 tg- 样式）。
 *  话术逐字抄真机源码（X44/F72）：DedupeProcessing.tsx / VariantMatrix.tsx / ResourceDownload.tsx。
 *  帧模式（11-16 用户口径「改成一帧一帧的图片」）：loopCount 探针改为「img 双快照 src 变化」检测。
 *
 *  token 注入坑（11-16 实测）：addScriptToEvaluateOnNewDocument 在当前 Chrome 版本下不可靠，
 *  页面被重定向到 /login。改用「navigate→setItem→reload」三步注入，每页独立导航。
 *
 *  全程零写操作。用法：node shoot-biz-dedup-guides.mjs <token 文件>
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = 'http://192.168.1.163';
const OUT = '/tmp/shots-biz-dedup';
mkdirSync(OUT, { recursive: true });
const TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_adm', 'utf8').trim();
if (!TOK.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9336', '--user-data-dir=/tmp/asset-shot-profile-biz-dedup',
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
    try { const l = await (await fetch('http://127.0.0.1:9336/json')).json(); t = l.find((x) => x.type === 'page'); } catch {}
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

  // 可靠 token 注入：navigate→setItem→reload（11-16 实测 addScript 方式不可靠）
  const gotoAuthed = async (path) => {
    await send('Page.navigate', { url: `${BASE}${path}` });
    await sleep(3000);
    await js(`try{localStorage.setItem('auth_token', ${JSON.stringify(TOK)})}catch(e){}`);
    await send('Page.navigate', { url: `${BASE}${path}` });
    await sleep(4500);
  };

  // X46 姿势：取 .ant-modal 全容器（标题在 header），再剥 tg- 样式串防 CSS 混入正文
  const modalText = async () => {
    await sleep(1200);
    const s = await js(`(() => { const m=document.querySelector('.ant-modal'); return m ? m.textContent : 'NO-MODAL'; })()`);
    return String(s).replace(/\.tg-[^\x22]*?\}/g, '');
  };
  const openGuide = async (label) =>
    js(`(() => { const b=Array.from(document.querySelectorAll('span')).find(x=>x.textContent.includes('${label}')&&x.textContent.includes('怎么用')); if(!b) return 'no-entry'; b.click(); return 'ok'; })()`);
  // 推进步骤：优先点对应步骤圆点（比「下一步」按钮更可靠——变体矩阵页有 Collapse 等
  // 交互元素可能遮挡 ctrls 按钮，点 dot 直接 setStep 不受遮挡影响）
  const gotoStepDot = async (i) => {
    await js(`(() => { const d=document.querySelectorAll('.tg-dot')[${i}]; d&&d.click(); })()`);
    await sleep(2000);
  };
  // 帧模式实测（11-16 用户口径「改成一帧一帧的图片」）：① .tg-stage 内是 <img> 播放器；
  // ② 多快照 src 必须真的在变（逐帧切换活着）；③ 帧数=12。
  // 11-16 实测：nextStep 后 img 重新挂载有延迟，首次采样可能拿到空——先等挂载再采 3 次，
  // 任一相邻快照变化即算 PASS（避免单点采样时机问题假红）。
  const loopCount = async () => {
    await sleep(600);
    const imgs = Number(await js(`(() => { const st=document.querySelector('.ant-modal .tg-stage'); return st?st.querySelectorAll('img').length:-1; })()`));
    if (imgs <= 0) return 0;
    const srcs = [];
    for (let i = 0; i < 3; i++) {
      srcs.push(String(await js(`document.querySelector('.ant-modal .tg-stage img')?.getAttribute('src') || ''`)));
      await sleep(900);
    }
    const changed = srcs.some((s, i) => i > 0 && s !== srcs[i - 1]);
    return (changed ? imgs * 2 : 0);
  };
  const closeGuide = async () => { await js(`(() => { const x=document.querySelector('.ant-modal-close'); x&&x.click(); })()`); await sleep(500); };

  // ── ① 去重处理（/dedupe）──
  await gotoAuthed('/dedupe');
  assert('D-A0 页面渲染（「去重处理」标题在位）', String(await js(`Array.from(document.querySelectorAll('h4,.ant-card-head')).some(b=>b.textContent.includes('去重处理'))`)) === 'true');
  assert('D-A1 入口「❓ 去重处理怎么用」在位且点开', (await openGuide('去重处理怎么用')) === 'ok');
  let body = await modalText();
  assert('D-A2 标题+第1步「从已切片任务选择」真话术', body.includes('去重处理怎么用 · 60 秒动画版') && body.includes('从已切片任务选择'), body.slice(0, 160));
  assert('D-A2b 第1步帧播放器在逐帧切换（12 帧×0.36s）', Number(await loopCount()) > 0);
  await gotoStepDot(1);
  body = await modalText();
  assert('D-A3 第2步「去重配置（档位 + 变体数量 + 手动手段）」逐字', body.includes('去重配置（档位 + 变体数量 + 手动手段）'), body.slice(0, 160));
  assert('D-A3b 第2步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(2);
  body = await modalText();
  assert('D-A4 第3步「提交生成」+「上传去重」真字面', body.includes('提交生成') && body.includes('上传去重'), body.slice(0, 160));
  assert('D-A4b 第3步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(3);
  body = await modalText();
  assert('D-A5 第4步「查看变体矩阵」+「已生成」真话术', body.includes('查看变体矩阵') && body.includes('已生成'), body.slice(0, 160));
  assert('D-A5b 第4步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await shot('dedup-step4');
  await closeGuide();

  // ── ② 变体矩阵（/variant-matrix）──
  await gotoAuthed('/variant-matrix');
  assert('V-A0 页面渲染（「变体矩阵看板」标题在位）', String(await js(`Array.from(document.querySelectorAll('h4,.ant-card-head')).some(b=>b.textContent.includes('变体矩阵看板'))`)) === 'true');
  assert('V-A1 入口「❓ 变体矩阵怎么用」在位且点开', (await openGuide('变体矩阵怎么用')) === 'ok');
  body = await modalText();
  assert('V-A2 标题+第1步「变体矩阵看板（多视频号素材去重）」逐字', body.includes('变体矩阵怎么用 · 60 秒动画版') && body.includes('变体矩阵看板（多视频号素材去重）'), body.slice(0, 160));
  assert('V-A2b 第1步帧播放器在逐帧切换', Number(await loopCount()) > 0);
  await gotoStepDot(1);
  body = await modalText();
  assert('V-A3 第2步「撞车判定阈值（运营可调）」+「复核」逐字', body.includes('撞车判定阈值（运营可调）') && body.includes('复核'), body.slice(0, 160));
  assert('V-A3b 第2步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(2);
  body = await modalText();
  assert('V-A4 第3步「一个视频号账号只能绑定一个变体」长句逐字', body.includes('一个视频号账号只能绑定一个变体'), body.slice(0, 160));
  assert('V-A4b 第3步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(3);
  body = await modalText();
  assert('V-A5 第4步「一键下载全部」+「删除整组」真字面', body.includes('一键下载全部') && body.includes('删除整组'), body.slice(0, 160));
  assert('V-A5b 第4步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await shot('variant-step4');
  await closeGuide();

  // ── ③ 资源下载（/resource-download）──
  await gotoAuthed('/resource-download');
  assert('R-A0 页面渲染（「资源下载」标题在位）', String(await js(`Array.from(document.querySelectorAll('h4')).some(b=>b.textContent.includes('资源下载'))`)) === 'true');
  assert('R-A1 入口「❓ 资源下载怎么用」在位且点开', (await openGuide('资源下载怎么用')) === 'ok');
  body = await modalText();
  assert('R-A2 标题+第1步「导入视频素材（URL 直链）」逐字', body.includes('资源下载怎么用 · 60 秒动画版') && body.includes('导入视频素材（URL 直链）'), body.slice(0, 160));
  assert('R-A2b 第1步帧播放器在逐帧切换', Number(await loopCount()) > 0);
  await gotoStepDot(1);
  body = await modalText();
  assert('R-A3 第2步「下载任务」+「下载中」真话术', body.includes('下载任务') && body.includes('下载中'), body.slice(0, 160));
  assert('R-A3b 第2步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(2);
  body = await modalText();
  assert('R-A4 第3步「视频反推提示词（AI 提示词提取）」+「开始反推」逐字', body.includes('视频反推提示词（AI 提示词提取）') && body.includes('开始反推'), body.slice(0, 160));
  assert('R-A4b 第3步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(3);
  body = await modalText();
  assert('R-A5 第4步「一键导入切片」+「确认导入」真字面', body.includes('一键导入切片') && body.includes('确认导入'), body.slice(0, 160));
  assert('R-A5b 第4步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await gotoStepDot(4);
  body = await modalText();
  assert('R-A6 第5步「重试」+失败话术逐字', body.includes('重试'), body.slice(0, 160));
  assert('R-A6b 第5步帧模式（img 双快照切换）', Number(await loopCount()) > 0);
  await shot('resource-step5');
  await closeGuide();

  // ── 汇总 ──
  const pass = results.filter((r) => r.c).length;
  const fail = results.length - pass;
  console.log(`\n=== 结果: ${pass} passed / ${fail} failed · ${OUT} ===`);
  chrome.kill();
  process.exit(fail > 0 ? 1 : 0);
}

main().catch((e) => { console.error(e.message); chrome.kill(); process.exit(2); });
