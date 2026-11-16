#!/usr/bin/env node
/*
 * 业务区动画推进① · 短剧切片＋批量切片「怎么用」分步动画 · 现网 CDP 实拍（2026-11-15）
 *  姿势照 shoot-panel-guides.mjs：入口用 span 文本匹配、弹层取 .ant-modal 全容器（X46，
 *  标题在 header 不在 body；教程内嵌 <style> 会混 CSS 串，断言前先剥 tg- 样式）。
 *  话术逐字抄真机源码（X44/F72）：Projects.tsx / ProjectDetail.tsx / EpisodeDetail.tsx /
 *  ClipReview.tsx / BatchSlice.tsx。全程零写操作。用法：node shoot-biz-slice-guides.mjs <token 文件>
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = 'http://192.168.1.163';
const OUT = '/tmp/shots-biz-slice';
mkdirSync(OUT, { recursive: true });
const TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_local', 'utf8').trim();
if (!TOK.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }
// /publish 受 RBAC 闸（AuthGuard hasPermission('publish-management')，operator 角色进不去会弹
// 403 ForbiddenPage），回归段必须用带该菜单的角色 token（admin/publisher）。缺省同文件。
let ADMIN_TOK = TOK;
try { ADMIN_TOK = readFileSync('/tmp/.cdp_tok_admin', 'utf8').trim() || TOK; } catch {}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9335', '--user-data-dir=/tmp/asset-shot-profile-biz-slice',
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
    try { const l = await (await fetch('http://127.0.0.1:9335/json')).json(); t = l.find((x) => x.type === 'page'); } catch {}
    if (!t) await sleep(250);
  }
  if (!t) throw new Error('CDP 未就绪');
  ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error('x')) : p.res(m.result); } };
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
  let injectId = null;
  try { injectId = (await send('Page.addScriptToEvaluateOnNewDocument', { source: `try{localStorage.setItem('auth_token', ${JSON.stringify(TOK)})}catch(e){}` })).identifier; } catch {}
  const js = async (e) => { const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true }); return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 150)}` : r.result?.value; };
  const shot = async (n) => { const { data } = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${OUT}/${n}.png`, Buffer.from(data, 'base64')); };
  // X46 姿势：取 .ant-modal 全容器（标题在 header），再剥 tg- 样式串防 CSS 混入正文
  const modalText = async () => {
    await sleep(1200);
    const s = await js(`(() => { const m=document.querySelector('.ant-modal'); return m ? m.textContent : 'NO-MODAL'; })()`);
    return String(s).replace(/\.tg-[^\x22]*?\}/g, '');
  };
  const openGuide = async (label) =>
    js(`(() => { const b=Array.from(document.querySelectorAll('span')).find(x=>x.textContent.includes('${label}')&&x.textContent.includes('怎么用')); if(!b) return 'no-entry'; b.click(); return 'ok'; })()`);
  const nextStep = async () => {
    await js(`(() => { const b=Array.from(document.querySelectorAll('.tg-ctrls button')).find(x=>x.textContent.includes('下一步')); b&&b.click(); })()`);
    await sleep(1300);
  };
  // 无限循环动效实测（c06a129 验收口径）：数 .tg-stage 里持续循环元素
  // （巡航光标 tg-cursor-run／按钮 pulse／角标 blink／步骤条 on pulse／光标 ::after blink），必须 >0
  const loopCount = async () => js(`(() => {
    const st = document.querySelector('.ant-modal .tg-stage');
    if (!st) return -1;
    let n = 0;
    st.querySelectorAll('*').forEach((e) => {
      const cs = getComputedStyle(e);
      if (cs.animationName !== 'none' && cs.animationIterationCount === 'infinite') n++;
      const ca = getComputedStyle(e, '::after');
      if (ca.animationName !== 'none' && ca.animationIterationCount === 'infinite') n++;
    });
    return n;
  })()`);
  const closeGuide = async () => { await js(`(() => { const x=document.querySelector('.ant-modal-close'); x&&x.click(); })()`); await sleep(500); };

  // ── ① 短剧切片（/projects）──
  await send('Page.navigate', { url: `${BASE}/projects` });
  await sleep(4000);
  assert('S-A0 页面渲染（「新建项目」按钮在位）', String(await js(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.includes('新建项目'))`)) === 'true');
  assert('S-A1 入口「❓ 短剧切片怎么用」在位且点开', (await openGuide('短剧切片怎么用')) === 'ok');
  let body = await modalText();
  assert('S-A2 标题+第1步「新建项目」真字面', body.includes('短剧切片怎么用 · 60 秒动画版') && body.includes('新建项目'), body.slice(0, 160));
  assert('S-A2b 第1步无限循环动效>0（巡航光标 3.6s/轮）', Number(await loopCount()) > 0);
  await nextStep();
  body = await modalText();
  assert('S-A3 第2步上传话术逐字「多视频上传（合并成剧集）」', body.includes('多视频上传（合并成剧集）') && body.includes('单个视频也会作为一个剧集；需要合并请在下方使用「多视频上传」'), body.slice(0, 160));
  assert('S-A3b 第2步无限循环动效>0', Number(await loopCount()) > 0);
  await nextStep();
  body = await modalText();
  assert('S-A4 第3步「批量一键切片」+「无候选片段时自动补一轮 AI 选点」', body.includes('批量一键切片') && body.includes('无候选片段时自动补一轮 AI 选点'), body.slice(0, 160));
  assert('S-A4b 第3步无限循环动效>0（步骤条 pulse＋按钮 pulse）', Number(await loopCount()) > 0);
  await nextStep();
  body = await modalText();
  assert('S-A5 第4步审核真字面「启动选点」「一键全部通过」', body.includes('启动选点') && body.includes('一键全部通过'), body.slice(0, 160));
  assert('S-A5b 第4步无限循环动效>0（角标 blink）', Number(await loopCount()) > 0);
  await nextStep();
  body = await modalText();
  assert('S-A6 第5步「成品预览」Tab 长句逐字', body.includes('暂无成品。请先对剧集执行切片（可勾选多个剧集后使用「批量一键切片」），完成后即可在此预览。'), body.slice(0, 160));
  assert('S-A6b 第5步无限循环动效>0', Number(await loopCount()) > 0);
  await shot('slice-guide-step5');
  await closeGuide();

  // ── ② 批量切片（/batch-slice）──
  await send('Page.navigate', { url: `${BASE}/batch-slice` });
  await sleep(4000);
  assert('B-A0 页面渲染（「创建批次并开始处理」按钮在位）', String(await js(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.includes('创建批次并开始处理'))`)) === 'true');
  assert('B-A1 入口「批量切片怎么用」点开', (await openGuide('批量切片怎么用')) === 'ok');
  body = await modalText();
  assert('B-A2 标题+第1步 JSON 字段真话术', body.includes('批量切片怎么用 · 50 秒动画版') && body.includes('drama'), body.slice(0, 160));
  assert('B-A3 tagline 逐字（整页 Alert 真话术）', body.includes('一份 JSON 排几十集，机器按剧名建项目连夜切完'), body.slice(0, 160));
  assert('B-A3b 第1步无限循环动效>0（光标＋textarea 光标 blink）', Number(await loopCount()) > 0);
  await nextStep();
  body = await modalText();
  assert('B-A4 第2步预设共用长句逐字', body.includes('与剧集详情页「一键切片配置」共用，选中后自动套用竖屏转横屏/字幕/打码/水印/去重档位等全部参数'), body.slice(0, 160));
  assert('B-A4b 第2步无限循环动效>0（主按钮 pulse＋状态 blink）', Number(await loopCount()) > 0);
  await nextStep();
  body = await modalText();
  assert('B-A5 第3步六阶段＋失败重试话术', body.includes('AI 选点') && body.includes('删除源视频') && body.includes('已完成项将跳过'), body.slice(0, 160));
  assert('B-A5b 第3步无限循环动效>0（步骤条 pulse）', Number(await loopCount()) > 0);
  await nextStep();
  body = await modalText();
  assert('B-A6 第4步成品 Alert 逐字＋「开始裁剪」', body.includes('每个成品支持「预览」播放，以及「编辑」通过拖动进度条选定时间范围进行简单裁剪（会重新编码生成新片段）。') && body.includes('开始裁剪'), body.slice(0, 160));
  assert('B-A6b 第4步无限循环动效>0', Number(await loopCount()) > 0);
  await shot('batch-slice-guide-step4');
  await closeGuide();

  // ── 回归：发布管理动画仍在（BizGuides 同文件改动零破坏；RBAC 段用 admin/publisher token）──
  // ⚠️ 两层坑叠加（三轮假红的完整根因）：①operator 无 publish-management 菜单，AuthGuard 弹
  // ForbiddenPage，必须换 admin/publisher token；②`addScriptToEvaluateOnNewDocument` 是**持久
  // 注入钩子**，每次新文档都会把旧的 operator token **覆盖回去**——只写 localStorage＋reload 没用。
  // 正解＝先 removeScriptToEvaluateOnNewDocument 撤钩子，再换 token、reload。
  if (injectId) { await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: injectId }); }
  await js(`try{localStorage.setItem('auth_token', ${JSON.stringify(ADMIN_TOK)})}catch(e){}`);
  await send('Page.navigate', { url: `${BASE}/publish` });
  await sleep(4500);
  assert('R-A1 回归：发布流程动画版入口仍在', String(await js(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent.includes('发布流程动画版'))`)) === 'true');
  await js(`(() => { const b=Array.from(document.querySelectorAll('button')).find(x=>x.textContent.includes('发布流程动画版')); b&&b.click(); })()`);
  body = await modalText();
  assert('R-A2 回归：PublishFlowGuide 标题活着', body.includes('发布流程怎么用 · 60 秒动画版'), body.slice(0, 160));
  await shot('publish-regression');

  chrome.kill();
  const failed = results.filter((r) => !r.c).length;
  console.log(`=== ${results.length - failed} passed / ${failed} failed · ${OUT}/ ===`);
  process.exit(failed ? 1 : 0);
}
main().catch((e) => { console.error(e.message); chrome.kill(); process.exit(2); });
