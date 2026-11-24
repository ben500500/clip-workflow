#!/usr/bin/env node
/*
 * 极简模式 CDP 真截图门（2026-11-24 改版）
 *
 * 为什么改判据——用户 11-24 原话：
 *   「你这个直接不是过度简化吗？**原来的 tab 形式还是要保留的，这样能分清步骤**。
 *    然后你的什么组合出片、什么行列写在那里，谁看得懂？**素材也没有预览**。
 *    我要的那个拼接是最后一步，你可以先不做……」
 * 所以本门不再验「极简＝零页签」（那是上一版的判据，已被这条推翻），改成验：
 *   ① 极简是**四步页签**（① 导稿／② 脚本库／③ 投豆包／④ 看成片），顶层恰 4 个；
 *   ② 每屏有**素材预览**（缩略图＝该脚本出处那条片子的首帧，点一下真播得出画面）；
 *   ③ **组合出片那屏从界面撤下**（后端 compose/matrix 不动，界面不摆行列矩阵）；
 *   ④ 旧五环（完整模式）没被带坏；
 *   ⑤ 偏好接口 pending 时不空白（52e61ee 的兜底）；
 *   ⑥ material 角色（无审核职能）看到的按钮文案说真话；
 *   ⑦ 批 T（11-24）素材隔离：顶栏「仅看自己」开关默认关＝看全部、开了跟着账号存，
 *      脚本库的 ⭐ 收藏能把**同事的**稿子拉进「我的」（只改可见范围，不改归属）。
 *      用户原话：「默认是要能看到全部的，但是可以加入一个开关或者复选框，仅看自己。
 *      这个仅看自己，不是说仅仅是自己导入的文案也可以在已有的脚本库里面勾选，然后收藏起来。」
 *
 * 全程不点「投豆包」（花钱），只做勾选/切页签/点开预览这类只读动作。
 *
 * 11-24 踩坑：shot() 不 await 会抢下一跳的页面——p3 那张截成了 ④ 的内容，
 * p4/c 两张干脆没落盘（进程退出前 capture 还没回）。所有截图一律 await。
 * 跑之前请清一次偏好，让 admin 从「未存偏好 → 后端按角色默认＝full」起步：
 *   docker exec clip-postgres psql -U clipworkflow -d clipworkflow -c 'delete from user_preferences'
 *   （163 上库名/用户都是 clip，本机是 clipworkflow）
 * T 段还需要一条**属于同事（materialtest）**的脚本，本机栈种子（用 material 的 token 建，
 * 归属才会真是 materialtest；「谁的」列与收藏判据都靠它）：
 *   curl -s -X POST http://127.0.0.1:3000/api/assets/scripts \
 *     -H "Authorization: Bearer $(cat /tmp/.cdp_tok_material)" -H 'Content-Type: application/json' \
 *     -d '{"name":"CDP门·同事的稿","body":"（门禁用）这条属于 materialtest，用来验收藏只改可见范围不改归属。"}'
 * 跑完 T 段会把收藏关系和「仅看自己」开关都还原，这条脚本留着不删（下次继续用）。
 * 预览段需要本机栈有一条「定稿脚本 + 出处素材有帧 + 帧对象真在桶里」的数据，
 * 种子做法见本次会话记录（/api/assets/upload/batch 传两个小 mp4 → 自动抽帧 →
 * POST /api/assets/scripts 绑 origin_asset_id → finalize 一条）。
 *
 * 用法：node shoot-simple.mjs <admin-token-file> <material-token-file>
 *   默认 /tmp/.cdp_tok_local + /tmp/.cdp_tok_material
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
// T9 用：把经过的 /api/assets 请求 URL 记下来，判「仅看自己」这颗开关有没有真的传到底层查询。
// 只看界面文字判不了这件事——四个面板各自都有「我的/全部」，本地数据又全属于 admin，
// 收不收在屏幕上看不出区别，只有请求参数骗不了人。
const netLog = [];
let netOn = false;

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
      if (netOn && url.includes('/api/assets')) { netLog.push(url); if (netLog.length > 400) netLog.shift(); }
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
  await send('Fetch.enable', {
    patterns: [
      { urlPattern: '*' + HANG_URL, requestStage: 'Request' },
      { urlPattern: '*/api/assets*', requestStage: 'Request' },
    ],
  });

  const js = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 150)}` : r.result?.value;
  };
  const shot = async (n) => {
    try {
      const { data } = await send('Page.captureScreenshot', { format: 'png' });
      writeFileSync(`${OUT}/${n}.png`, Buffer.from(data, 'base64'));
    } catch (e) {
      console.log(`WARN 截图 ${n} 失败：${String(e.message || e).slice(0, 120)}`);
    }
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
  // 只取**最外层**页签：④ 看成片里成片墙自带页签，混进来会把「恰 4 个」判成假红
  const grabTabs = async () => js(`
    (() => Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .filter((t) => {
        const nav = t.closest('.ant-tabs');
        return nav && !(nav.parentElement && nav.parentElement.closest('.ant-tabs'));
      })
      .map(x => x.textContent.replace(/\\s+/g, ' ').trim()).join('｜'))()
  `);
  const grabCards = async () => js(`
    (() => Array.from(document.querySelectorAll('.ant-card-head-title')).map(x => x.textContent.replace(/\\s+/g, ' ').trim()).join('｜'))()
  `);
  // 只认**最外层活动面板**：antd 把访问过的面板留在 DOM 里（只是 display:none），
  // 用全局 querySelector 会把「藏在别的页签里」判成「这一屏看得见」——11-24 就栽过一次
  const ACTIVE = `(() => {
    const p = Array.from(document.querySelectorAll('.ant-tabs-tabpane-active'))
      .filter(x => !(x.parentElement && x.parentElement.closest('.ant-tabs-tabpane')));
    return p[0] || document.body;
  })()`;
  const grabButtons = async () => js(`
    (() => {
      const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
      const bs = Array.from(document.querySelectorAll('button')).map(x => ({ t: norm(x.textContent), d: !!x.disabled }));
      return JSON.stringify({
        importHook: bs.find(b => b.t === '导入钩子视频并反推') || null,
        uploadScript: bs.find(b => b.t.includes('上传脚本文件')) || null,
        writeScript: bs.find(b => b.t === '手写脚本') || null,
        dispatch: bs.filter(b => b.t.includes('投豆包')).map(b => ({ t: b.t, d: b.d })),
      });
    })()
  `);
  const clickTab = async (kw) => js(`(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const hit = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .filter((t) => { const nav = t.closest('.ant-tabs'); return nav && !(nav.parentElement && nav.parentElement.closest('.ant-tabs')); })
      .find(x => norm(x.textContent).includes(${JSON.stringify(kw)}));
    if (!hit) return 'no-tab';
    (hit.querySelector('.ant-tabs-tab-btn') || hit).click();
    return 'ok';
  })()`);
  const parseJson = (s) => { try { return typeof s === 'string' ? JSON.parse(s) : s; } catch { return null; } };

  // ───────────────────────────────────────────────────────────
  // D. 旧五环回归 + Segmented 在位（admin 未存偏好 → 默认 full）
  // ───────────────────────────────────────────────────────────
  await setToken(ADMIN_TOK);
  await goto('/assets');
  await sleep(2000);
  const seg = await js(`(() => {
    const s = document.querySelector('.ant-segmented');
    if (!s) return 'NO-SEGMENTED';
    return Array.from(s.querySelectorAll('.ant-segmented-item-label')).map(x=>x.textContent.trim()).join('|');
  })()`);
  assert('D1 Segmented 极简|完整 存在', seg === '极简|完整', seg);
  const tabsFull = await grabTabs();
  const wantFull = ['① 导入', '② 素材与文案', '③ 文案审核', '④ 生产与投板', '⑤ 成片墙', '后台任务'];
  const missing = wantFull.filter((w) => !String(tabsFull).includes(w));
  assert('D2 admin 默认 full：旧五环 6 Tab 全在（回归）', missing.length === 0, `tabs=${tabsFull}`);
  await shot('d1-admin-full-default');

  // ───────────────────────────────────────────────────────────
  // B. 偏好 pending 超时兜底：拦截 /api/assets/ui/preferences 挂 15s
  //    期望页面在 ≤3.5s 内出五环（2.5s 定值兜底落 'full'），不是永远 Spin/空白
  // ───────────────────────────────────────────────────────────
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
      const sel = document.querySelector('.ant-segmented-item-selected');
      const spin = /正在读取你的界面偏好/.test(document.body.innerText);
      return JSON.stringify({url: location.pathname, seg: sel ? norm(sel.textContent) : '-',
        spin, tabs: document.querySelectorAll('.ant-tabs-tab').length, ready: document.readyState});
    })()`) || lastDiag;
    await sleep(200);
  }
  const elapsed = Date.now() - t0;
  hangUntil = 0;   // 解除挂起，剩下请求放行
  assert('B1 偏好 pending 时 ≤3.5s 内出五环（不空白）',
    tabsSeenAt >= 0 && tabsSeenAt <= 3500,
    `耗时=${tabsSeenAt}ms 总耗时=${elapsed}ms 挂起命中=${hungCount} 末帧=${JSON.stringify(lastDiag)}`);
  await shot('b1-timeout-fallback');

  // ───────────────────────────────────────────────────────────
  // A. 点「极简」→ 四步页签（11-24 用户：原来的 tab 形式要保留，好分清步骤）
  // ───────────────────────────────────────────────────────────
  const clickSeg = await js(`(() => {
    const items = Array.from(document.querySelectorAll('.ant-segmented-item'));
    const hit = items.find(x => x.textContent.trim() === '极简');
    if (!hit) return 'no-item';
    hit.click();
    return 'ok';
  })()`);
  assert('A1 Segmented 「极简」点击成功', clickSeg === 'ok', clickSeg);
  await sleep(2500);   // 等 saveUiPreferences 落库＋React 重渲染
  const tabsSimple = await grabTabs();
  const wantSimple = ['① 导稿', '② 脚本库', '③ 投豆包', '④ 看成片'];
  const missSimple = wantSimple.filter((w) => !String(tabsSimple).includes(w));
  const tabCount = String(tabsSimple).split('｜').filter(Boolean).length;
  assert('A2 极简＝四步页签齐（导稿/脚本库/投豆包/看成片）', missSimple.length === 0, `tabs=${tabsSimple}`);
  assert('A3 顶层页签恰 4 个（旧「零页签」判据作废）', tabCount === 4, `tabs=${tabsSimple}`);
  const cards = await grabCards();
  assert('A4 ① 导稿屏有「1. 先弄到稿」卡', /1\. 先弄到稿/.test(cards), cards);
  const btns = parseJson(await grabButtons());
  assert('A5 ① 屏主按钮齐全（导入钩子／上传脚本／手写）',
    !!(btns && btns.importHook && btns.uploadScript && btns.writeScript),
    JSON.stringify(btns));
  assert('A6 组合出片矩阵卡已从界面撤下（无「组合/矩阵/叠加预设」标题）',
    !/组合|矩阵|叠加预设/.test(cards), cards);
  await shot('a1-simple-grab');

  // ───────────────────────────────────────────────────────────
  // P. 素材预览（11-24 用户：「素材也没有预览」）
  // ───────────────────────────────────────────────────────────
  assert('P0 切到 ② 脚本库', (await clickTab('脚本库')) === 'ok');
  await sleep(2500);   // 等 scripts 列表 + /assets/frames 首帧回来
  const heads = await js(`
    (() => Array.from((${ACTIVE}).querySelectorAll('.ant-table-thead th')).map(x=>x.textContent.replace(/\\s+/g,' ').trim()).join('｜'))()
  `);
  assert('P1 ② 表格有「预览」列', /预览/.test(String(heads)), heads);
  // 硬判据＝naturalWidth>0（图真从桶里取回来了），不是「有 img 标签」
  let pic = { loaded: 0, sample: '' };
  for (let i = 0; i < 20; i++) {
    const p = parseJson(await js(`(() => {
      const img = Array.from((${ACTIVE}).querySelectorAll('.ant-table-tbody img'));
      const ok = img.filter(x => x.naturalWidth > 0);
      return JSON.stringify({ total: img.length, loaded: ok.length, sample: (ok[0] || {}).currentSrc || '' });
    })()`)) || pic;
    pic = p;
    if (p.loaded >= 2) break;
    await sleep(400);
  }
  assert('P2 预览格是真图（naturalWidth>0 至少 2 张）', pic.loaded >= 2, JSON.stringify(pic));
  await shot('p1-scripts-with-covers');

  const openPlay = await js(`(() => {
    const img = Array.from((${ACTIVE}).querySelectorAll('.ant-table-tbody img')).find(x => x.naturalWidth > 0);
    if (!img) return 'no-img';
    img.click();
    return 'ok';
  })()`);
  assert('P3 点缩略图弹出播放窗', openPlay === 'ok', openPlay);
  let vid = { videoWidth: 0, has: false, srcHead: '' };
  for (let i = 0; i < 25; i++) {
    const v = parseJson(await js(`(() => {
      const m = document.querySelector('.ant-modal');
      const vd = m ? m.querySelector('video') : null;
      if (!vd) return JSON.stringify({ has: false, videoWidth: 0, srcHead: '',
        note: m ? (m.innerText || '').replace(/\\s+/g,' ').slice(0,80) : 'NO-MODAL' });
      return JSON.stringify({ has: true, videoWidth: vd.videoWidth, videoHeight: vd.videoHeight,
        srcHead: (vd.currentSrc || vd.src || '').slice(0, 70) });
    })()`)) || vid;
    vid = v;
    if (v.videoWidth > 0) break;
    await sleep(400);
  }
  assert('P4 点开真播得出画面（videoWidth>0，不是黑框）', vid.videoWidth > 0, JSON.stringify(vid));
  await shot('p2-modal-playing');
  // 关掉：点遮罩不行（Modal maskClosable 默认开但动画期吃掉点击），直接点关闭叉
  await js(`(() => {
    const x = document.querySelector('.ant-modal-close');
    if (x) x.click();
    return 1;
  })()`);
  await sleep(1200);
  assert('P5 关窗后无残留 Modal', (await js(`document.querySelectorAll('.ant-modal-wrap:not([style*="display: none"])').length`)) <= 1);

  // 只有定稿的能勾——预览这次改版没动这条闸门
  // 注意：加了「预览」列后名字格不是 nth-child(2) 了，一律按整行 innerText 认行
  const cb = parseJson(await js(`(() => {
    const rows = Array.from((${ACTIVE}).querySelectorAll('.ant-table-tbody tr'));
    const box = rows.filter(r => r.innerText.includes('CDP门')).map(r => ({
      name: r.innerText.replace(/\\s+/g, ' ').trim().slice(0, 24),
      disabled: !!(r.querySelector('input[type=checkbox]') || {}).disabled,
    }));
    return JSON.stringify(box);
  })()`)) || [];
  assert('P6 未定稿不可勾、定稿可勾（闸门没被带坏）',
    Array.isArray(cb) && cb.some(x => x.disabled) && cb.some(x => !x.disabled),
    JSON.stringify(cb));
  const picked = await js(`(() => {
    const rows = Array.from((${ACTIVE}).querySelectorAll('.ant-table-tbody tr'));
    const hit = rows.find(r => {
      const c = r.querySelector('input[type=checkbox]');
      return c && !c.disabled && r.innerText.includes('CDP门');
    });
    if (!hit) return 'no-row';
    const c = hit.querySelector('input[type=checkbox]');
    c.click();
    return 'ok';
  })()`);
  assert('P7 勾上那条定稿脚本', picked === 'ok', picked);
  await sleep(800);

  // ③ 投豆包：勾选的稿子要带图看得见（不是只有一行列文字）
  assert('P8 切到 ③ 投豆包', (await clickTab('投豆包')) === 'ok');
  await sleep(1800);
  const chip = parseJson(await js(`(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const scope = ${ACTIVE};
    const card = Array.from(scope.querySelectorAll('.ant-card')).find(c =>
      norm((c.querySelector('.ant-card-head-title') || {}).textContent).includes('这次要投的脚本'));
    if (!card) return JSON.stringify({ card: false, scopeText: norm(scope.innerText).slice(0, 60) });
    const imgs = Array.from(card.querySelectorAll('img')).filter(x => x.naturalWidth > 0);
    return JSON.stringify({ card: true, title: norm((card.querySelector('.ant-card-head-title') || {}).textContent),
      hasName: (card.innerText || '').includes('CDP门'), thumb: imgs.length });
  })()`)) || {};
  assert('P9 ③ 活动面板里就摆着「这次要投的脚本」，列出勾中那条且带预览图',
    !!(chip.card && chip.hasName && chip.thumb >= 1), JSON.stringify(chip));
  const pBtns = parseJson(await grabButtons());
  assert('P10 ③ 主按钮按已勾条数说真话（含「投豆包（1）」/「轻量过审并投豆包（1）」）',
    !!(pBtns && pBtns.dispatch && pBtns.dispatch.some(b => /（1）/.test(b.t))),
    JSON.stringify(pBtns && pBtns.dispatch));
  await shot('p3-produce-chips');

  // ④ 看成片：成片墙 + 拼接去短剧切片的指引
  assert('P11 切到 ④ 看成片', (await clickTab('看成片')) === 'ok');
  await sleep(2000);
  const outNote = await js(`(() => {
    const scope = ${ACTIVE};
    return scope.innerText.replace(/\\s+/g, ' ').includes('短剧切片');
  })()`);
  assert('P12 ④ 活动面板说明「要拼接先去短剧切片」（不摆看不懂的矩阵）', outNote === true, outNote);
  const wall = await js(`(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const scope = ${ACTIVE};
    const t = scope.innerText;
    return JSON.stringify({ hasEmpty: !!scope.querySelector('.ant-empty'), hasWallWord: /成片|产物/.test(norm(t)) });
  })()`);
  const wallInfo = parseJson(wall) || {};
  assert('P13 ④ 成片墙渲染（有墙/空态，不是白屏）', !!(wallInfo.hasWallWord || wallInfo.hasEmpty), wall);
  await shot('p4-outputs-wall');

  // ───────────────────────────────────────────────────────────
  // T. 批 T（11-24）素材隔离：「仅看自己」开关 ＋ 脚本库 ⭐ 收藏
  //    两只手分开验：开关＝全局可见范围（默认关＝看全部，选择按人存后端）；
  //    收藏＝把别人的稿子挪进「我的」清单，**不改归属**（写口仍只认 owner_id）。
  //    ② 这一屏有两张表（待过审 ＋ 改稿·定稿），所以一切查找锁到「改稿」那张卡里，
  //    否则会把待过审的行也算进来（它们没有星标）。
  //    全程只点开关/星标/页签，不投产、不花钱；结尾把收藏关系和开关都还原。
  // ───────────────────────────────────────────────────────────
  const SCOPE = `(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const pane = document.querySelector('.ant-tabs-tabpane-active') || document.body;
    const card = Array.from(pane.querySelectorAll('.ant-card')).find(c =>
      norm((c.querySelector('.ant-card-head-title') || {}).textContent).includes('改稿'));
    return card || pane;
  })()`;
  const OWN_SEG = `(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const scope = ${SCOPE};
    return Array.from(scope.querySelectorAll('.ant-segmented')).find(x =>
      /我的/.test(norm(x.innerText)) && /全部/.test(norm(x.innerText))) || null;
  })()`;
  const SW_FIND = `(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    return Array.from(document.querySelectorAll('.ant-switch')).find((x) => {
      const box = x.closest('.ant-space');
      return box && norm(box.innerText).includes('仅看自己');
    }) || null;
  })()`;
  const readSwitch = async () => parseJson(await js(`(() => {
    const hit = ${SW_FIND};
    if (!hit) return JSON.stringify({ found: false, total: document.querySelectorAll('.ant-switch').length });
    return JSON.stringify({ found: true, on: hit.className.includes('ant-switch-checked') });
  })()`)) || {};
  const clickSwitch = async () => js(`(() => {
    const hit = ${SW_FIND};
    if (!hit) return 'no-switch';
    hit.click();
    return 'ok';
  })()`);
  const segPick = async (label) => js(`(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const seg = ${OWN_SEG};
    if (!seg) return 'NO-SEG';
    const hit = Array.from(seg.querySelectorAll('.ant-segmented-item')).find(x => norm(x.textContent) === ${JSON.stringify(label)});
    if (!hit) return 'no-item';
    hit.click();
    return 'ok';
  })()`);
  const segSelected = async () => js(`(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const seg = ${OWN_SEG};
    if (!seg) return 'NO-SEG';
    const sel = seg.querySelector('.ant-segmented-item-selected');
    return sel ? norm(sel.textContent) : 'NO-SEL';
  })()`);
  const api = async (path) => parseJson(await js(`(async () => {
    const r = await fetch(${JSON.stringify(path)}, { headers: { Authorization: 'Bearer ' + (localStorage.getItem('auth_token') || '') } });
    let b = null; try { b = await r.json(); } catch (e) {}
    return JSON.stringify({ status: r.status, body: b });
  })()`)) || {};
  // 「谁的」必须按表头定位到**那一个单元格**取。首跑拿整行 innerText 判，结果被
  // 我自己在稿正文里写的「用来验收藏…」里的「收藏」二字判红——门禁自伤，不是产品缺。
  const DATA_ROWS = `.ant-table-tbody tr:not(.ant-table-measure-row):not(.ant-table-expanded-row):not(.ant-table-placeholder)`;
  const mateRow = async () => parseJson(await js(`(() => {
    const scope = ${SCOPE};
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const ths = Array.from(scope.querySelectorAll('.ant-table-thead th')).map((x) => norm(x.innerText));
    const wi = ths.findIndex((t) => t.includes('谁的'));
    const rows = Array.from(scope.querySelectorAll('${DATA_ROWS}'));
    const hit = rows.find(r => (r.innerText || '').includes('同事的稿'));
    if (!hit) return JSON.stringify({ row: false, rows: rows.length });
    const b = hit.querySelector('button[aria-label="收藏"], button[aria-label="取消收藏"]');
    const tds = Array.from(hit.children);
    const who = wi >= 0 && tds[wi] ? norm(tds[wi].innerText) : 'NO-COL[' + ths.join('/') + ']';
    return JSON.stringify({ row: true, label: b ? b.getAttribute('aria-label') : null, who });
  })()`)) || {};
  // 同事的归属**显示名**从后端读（库里 materialtest 的 display_name 是「素材员·测试」），
  // 判归属只认 owner_id——显示名是给人看的，收藏改的是可见范围、不动 owner_id。
  const meSelf = await api('/api/auth/me');
  const ADMIN_ID = String(meSelf.body?.id || '');
  const seedAll = await api('/api/assets/scripts?owner=all&page_size=200');
  const seedRow = (seedAll.body?.items || []).find((x) => String(x.name).includes('同事的稿')) || {};
  const MATE_ID = String(seedRow.owner_id || '');
  const MATE_NAME = String(seedRow.owner_name || '');

  const sw0 = await readSwitch();
  assert('T1 顶栏有「仅看自己」开关，且默认是关（＝看全部）', sw0.found === true && sw0.on === false, JSON.stringify(sw0));
  const pref0 = await api('/api/assets/ui/preferences');
  assert('T1b 后端读回的偏好里 asset_scope_mine=false（隔离是 opt-in，不是新默认）',
    pref0.status === 200 && pref0.body?.ui_config?.asset_scope_mine === false,
    JSON.stringify(pref0.body?.ui_config));

  assert('T2a 点开关＝打开', (await clickSwitch()) === 'ok');
  await sleep(1800);
  const swOn = await readSwitch();
  const pref1 = await api('/api/assets/ui/preferences');
  assert('T2b 打开后开关变 checked', swOn.on === true, JSON.stringify(swOn));
  assert('T2c 选择真落进后端（按人存，换浏览器也是这个状态）',
    pref1.body?.ui_config?.asset_scope_mine === true, JSON.stringify(pref1.body?.ui_config));
  assert('T2d 只写了一个键，「极简/完整」的选择没被冲掉（按键合并）',
    pref1.body?.ui_config?.asset_library_mode === 'simple', JSON.stringify(pref1.body?.ui_config));

  assert('T3a 切到 ② 脚本库', (await clickTab('脚本库')) === 'ok');
  await sleep(2200);
  const whoSeg = await segSelected();
  assert('T3b 全局开关翻了，脚本库的「我的/全部」跟着落到「我的」（一处翻动五处一起收）', whoSeg === '我的', whoSeg);
  const headsT = await js(`
    (() => Array.from((${SCOPE}).querySelectorAll('.ant-table-thead th'))
      .map(x=>x.textContent.replace(/\\s+/g,' ').trim()).join('｜'))()
  `);
  assert('T3c ② 表头有「收藏」列', /收藏/.test(String(headsT)), headsT);
  const starCount = parseJson(await js(`(() => {
    const rows = Array.from((${SCOPE}).querySelectorAll('${DATA_ROWS}'));
    const withStar = rows.filter(r => r.querySelector('button[aria-label="收藏"], button[aria-label="取消收藏"]')).length;
    return JSON.stringify({ rows: rows.length, withStar });
  })()`)) || {};
  assert('T3d 每一行都摆得出星标（不只是表头多一列）',
    starCount.rows > 0 && starCount.withStar === starCount.rows, JSON.stringify(starCount));

  const mineView = await mateRow();
  assert('T4 「我的」这一侧看不到同事的稿（没收藏过就不该出现，这才是隔离本身）',
    mineView.row === false, JSON.stringify(mineView));

  assert('T5a 手动切到「全部」（面板里局部切，不写回全局开关）', (await segPick('全部')) === 'ok');
  await sleep(2000);
  const allView = await mateRow();
  assert('T5b 「全部」里看得到同事那条', allView.row === true, JSON.stringify(allView));
  assert('T5c 「谁的」列如实写着它属于同事，此刻还没收藏所以不带「收藏」二字',
    !!MATE_NAME && allView.row === true && allView.who === MATE_NAME && !/收藏/.test(String(allView.who)),
    JSON.stringify({ allView, MATE_NAME, MATE_ID, ADMIN_ID }));
  const doFav = await js(`(() => {
    const rows = Array.from((${SCOPE}).querySelectorAll('.ant-table-tbody tr'));
    const hit = rows.find(r => (r.innerText || '').includes('同事的稿'));
    if (!hit) return 'no-row';
    const b = hit.querySelector('button[aria-label="收藏"]');
    if (!b) return 'no-star';
    b.click();
    return 'ok';
  })()`);
  assert('T5d 点这条的星标把它收藏起来（用户要的那只手）', doFav === 'ok', doFav);
  await sleep(2000);
  const afterFav = await mateRow();
  assert('T5e 收藏后星标变实心（aria-label 从「收藏」变「取消收藏」）',
    afterFav.label === '取消收藏', JSON.stringify(afterFav));
  const meAfter = await api('/api/assets/scripts?owner=me&page_size=200');
  const favHit = (meAfter.body?.items || []).find((x) => String(x.name).includes('同事的稿'));
  assert('T5f 后端 owner=me 里出现了这条同事的稿，且 favorited=true',
    meAfter.status === 200 && !!favHit && favHit.favorited === true,
    JSON.stringify({ status: meAfter.status, name: favHit && favHit.name, fav: favHit && favHit.favorited }));
  assert('T5g 收藏**没有**改变归属（owner_id 仍是同事的，写权限没被绕过）',
    !!favHit && !!MATE_ID && favHit.owner_id === MATE_ID && favHit.owner_id !== ADMIN_ID,
    JSON.stringify({ owner_id: favHit && favHit.owner_id, MATE_ID, ADMIN_ID, name: favHit && favHit.owner_name }));

  assert('T6a 切回「我的」', (await segPick('我的')) === 'ok');
  await sleep(2000);
  const mineWithFav = await mateRow();
  assert('T6b 收藏过的同事稿现在在「我的」里，且「谁的」写清来路（显示名 · 收藏）',
    !!MATE_NAME && mineWithFav.row === true && mineWithFav.who === `${MATE_NAME} · 收藏`,
    JSON.stringify({ mineWithFav, MATE_NAME }));

  const meList = await api('/api/assets/scripts?owner=me&page_size=200');
  const allList = await api('/api/assets/scripts?owner=all&page_size=200');
  const meIds = (meList.body?.items || []).map((x) => x.id);
  const allIds = new Set((allList.body?.items || []).map((x) => x.id));
  const stray = meIds.filter((id) => !allIds.has(id));
  const unjust = (meList.body?.items || []).filter((x) => x.favorited !== true && String(x.owner_id) !== ADMIN_ID).map((x) => x.name);
  assert('T7 「我的」＝「我写的 ∪ 我收藏的」，且是「全部」的子集（没有第三种来路）',
    meList.status === 200 && allList.status === 200 && meIds.length <= allIds.size
      && stray.length === 0 && unjust.length === 0,
    JSON.stringify({ me: meIds.length, all: allIds.size, stray, unjust }));
  await shot('t1-scope-switch-and-favorite');

  // 还原三件：取消收藏 → 局部切回全部 → 关掉全局开关（不还原下次跑 T4 直接假红）
  const undoFav = await js(`(() => {
    const rows = Array.from((${SCOPE}).querySelectorAll('.ant-table-tbody tr'));
    const hit = rows.find(r => (r.innerText || '').includes('同事的稿'));
    const b = hit ? hit.querySelector('button[aria-label="取消收藏"]') : null;
    if (!b) return 'no-star';
    b.click();
    return 'ok';
  })()`);
  await sleep(1800);
  assert('T8a 还原：取消收藏点回去了', undoFav === 'ok', undoFav);
  const afterUndo = await api('/api/assets/scripts?owner=me&page_size=200');
  const stillFav = (afterUndo.body?.items || []).filter((x) => String(x.name).includes('同事的稿'));
  assert('T8b 还原：收藏关系清掉后，同事那条又不属于「我的」了（me 收成只剩自己写的）',
    afterUndo.status === 200 && stillFav.length === 0, JSON.stringify(stillFav.map((x) => x.name)));
  assert('T8c 还原：脚本库这一屏切回「全部」', (await segPick('全部')) === 'ok');
  await sleep(1200);
  assert('T8d 还原：顶栏「仅看自己」关回去', (await clickSwitch()) === 'ok');
  await sleep(1500);
  const swOff = await readSwitch();
  const prefOff = await api('/api/assets/ui/preferences');
  assert('T8e 还原后后端存的是 asset_scope_mine=false（下一次跑仍从「看全部」起步）',
    swOff.on === false && prefOff.body?.ui_config?.asset_scope_mine === false,
    JSON.stringify({ sw: swOff, cfg: prefOff.body?.ui_config }));

  // ───────────────────────────────────────────────────────────
  // T9 完整模式（五环）那一侧：开关不是只喂极简，四个面板的底层查询都要收到 owner
  // ───────────────────────────────────────────────────────────
  assert('T9a 重新打开「仅看自己」（切到完整视图前先开，省一次重取）', (await clickSwitch()) === 'ok');
  await sleep(1200);
  // 抓请求**先开录再切模式**：四个面板的列表请求就在「切到完整视图」那一刻发出第一轮，
  // 切完再开录必然 0 命中（首跑就是这么假红的）。另外判据按**端点族**分，
  // 之前那条正斜杠只匹配裸 `/api/assets?`，summaries/productions/outputs 三个子路径永远抓不到。
  netOn = true;
  netLog.length = 0;
  assert('T9b 切到完整视图', (await js(`(() => {
    const hit = Array.from(document.querySelectorAll('.ant-segmented-item')).find(x => x.textContent.trim() === '完整');
    if (!hit) return 'no-item';
    hit.click();
    return 'ok';
  })()`)) === 'ok');
  await sleep(2500);
  const fullPanels = ['素材与文案', '文案审核', '生产与投板', '成片墙'];
  const FAM = {
    '素材与文案': (p) => p === '/api/assets',
    '文案审核': (p) => p === '/api/assets/summaries',
    '生产与投板': (p) => p === '/api/assets/productions',
    '成片墙': (p) => p === '/api/assets/outputs' || p.startsWith('/api/assets/outputs/'),
  };
  const pathOf = (u) => { try { return new URL(u).pathname; } catch { return u; } };
  const netMiss = [];
  const netSeen = {};
  for (const name of fullPanels) {
    await clickTab(name);
    await sleep(2400);
    // 末条为准：偏好接口回得慢时，面板可能先按默认全量发一次再收敛成 owner=me，
    // 用户最终看到的是收敛后的那一次。
    const fam = netLog.filter((u) => FAM[name](pathOf(u)));
    const last = fam[fam.length - 1] || '';
    const okMe = /[?&]owner=me(&|$)/.test(last);
    netSeen[name] = `${fam.length ? fam.length : 0}条/末条${/[?&]owner=([^&]*)/.test(last) ? last.match(/[?&]owner=([^&]*)/)[1] : '无owner'}`;
    if (!fam.length) netMiss.push(`${name}＝一条列表请求都没抓到`);
    else if (!okMe) netMiss.push(`${name}＝末条没带 owner=me（${last.slice(0, 120)}）`);
  }
  assert('T9c 完整模式四个面板的列表请求都收到 owner=me（一处翻动，五处一起收）',
    netMiss.length === 0, JSON.stringify({ miss: netMiss, seen: netSeen }));
  await shot('t2-full-mode-scope-requests');
  // 关回去：T1 下次还要从「默认看全部」起步
  assert('T9d 还原：关回「仅看自己」', (await clickSwitch()) === 'ok');
  await sleep(1200);
  netLog.length = 0;
  await clickTab('素材与文案');
  await sleep(2400);
  const backFam = netLog.filter((u) => FAM['素材与文案'](pathOf(u)));
  const backLast = backFam[backFam.length - 1] || '';
  netOn = false;
  assert('T9e 还原后素材列表请求带的是 owner=all（不是卡在 me 上）', /[?&]owner=all(&|$)/.test(backLast),
    `${backFam.length}条 末条=${backLast.slice(0, 160)}`);

  // ───────────────────────────────────────────────────────────
  // C. material 角色：无 canReview → 主按钮文案是「投豆包」；默认极简
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
    const matTabs = await grabTabs();
    assert('C2 material 的极简也是四步页签', ['导稿', '脚本库', '投豆包', '看成片']
      .every((w) => String(matTabs).includes(w)), `tabs=${matTabs}`);
    await clickTab('投豆包');
    await sleep(1500);
    const mBtns = parseJson(await grabButtons());
    assert('C3 material 看不到「轻量过审并投豆包」（无审核职能）',
      !!(mBtns && mBtns.dispatch && !mBtns.dispatch.some(b => b.t.includes('轻量过审'))),
      JSON.stringify(mBtns && mBtns.dispatch));
    assert('C4 material 主按钮文案含「投豆包」',
      !!(mBtns && mBtns.dispatch && mBtns.dispatch.some(b => b.t.includes('投豆包'))),
      JSON.stringify(mBtns && mBtns.dispatch));
    await shot('c-material-role');
  } else {
    assert('C0 material token 缺（跳过 C 段）', true);
  }

  const summary = results.reduce((a, r) => { a[r.c ? 'pass' : 'fail']++; return a; }, { pass: 0, fail: 0 });
  console.log(`\n总计 ${summary.pass}/${results.length} PASS，截图在 ${OUT}/`);
  writeFileSync(`${OUT}/report.json`, JSON.stringify(results, null, 2));
  process.exitCode = summary.fail ? 1 : 0;
}

main().catch((e) => { console.error('CDP 脚本异常', e); process.exitCode = 3; })
  .finally(async () => { try { ws && ws.close(); } catch {} chrome.kill('SIGKILL'); });
