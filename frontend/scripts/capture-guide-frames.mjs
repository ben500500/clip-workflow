#!/usr/bin/env node
/*
 * 教程动画 → 逐帧图片 · 捕获脚本（2026-11-16 用户口径「动画效果太差，改成一帧一帧的图片」）
 *
 * 原理：不手算坐标。打开现网各「怎么用」弹层 → 暂停自动播 → 逐点步骤圆点 →
 * 对当步画面 .tg-stage 内所有动画元素打 currentTime 相位偏移（getAnimations subtree，
 * 含伪元素动画），在 0~4.32s 上采 12 帧（0.36s/帧，正好盖过 3.6s 巡航一轮），
 * 每帧按 .tg-stage 包围盒截图存盘。全程零写操作（仅本地文件写盘）。
 * 输出：frontend/public/guides/<slug>/s<步>/f<帧>.png ＋ manifest。
 * 用法：node capture-guide-frames.mjs <token 文件>
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = 'http://192.168.1.163';
const OUT = new URL('../public/guides/', import.meta.url).pathname;
const FRAMES = 12;
const PHASE = 0.36; // s/帧 → 12 帧 4.32s ≥ 3.6s 巡航一轮
const TOK = readFileSync(process.argv[2] || '/tmp/.cdp_tok_adm', 'utf8').trim();
if (!TOK.startsWith('ey')) { console.error('token 文件不对'); process.exit(2); }

// slug → {page, open: 打开弹层的点击逻辑表达式, slug}
const GUIDES = [
  { slug: 'panel-import', page: '/assets', tab: '导入', entry: '导入怎么用' },
  { slug: 'panel-copy', page: '/assets', tab: '素材与文案', entry: '这一屏怎么用' },
  { slug: 'panel-review', page: '/assets', tab: '文案审核', entry: '审核怎么用', btn: true },
  { slug: 'panel-produce', page: '/assets', tab: '生产与投板', entry: '开单投板怎么用' },
  { slug: 'panel-output', page: '/assets', tab: '成片墙', entry: '挑片交付怎么用' },
  { slug: 'biz-publish', page: '/publish', tab: null, entry: '发布流程动画版', btn: true },
  { slug: 'biz-slice', page: '/projects', tab: null, entry: '短剧切片怎么用', span: true },
  { slug: 'biz-batch', page: '/batch-slice', tab: null, entry: '批量切片怎么用', span: true },
  { slug: 'trial', page: '/assets', tab: '文案审核', entry: '试产怎么用', btn: true },
  // 11-16 业务区动画推进②（去重/变体矩阵/资源下载，frameDir 逐帧图片模式）
  { slug: 'biz-dedup', page: '/dedupe', tab: null, entry: '去重处理怎么用', span: true },
  { slug: 'biz-variant', page: '/variant-matrix', tab: null, entry: '变体矩阵怎么用', span: true },
  { slug: 'biz-resource', page: '/resource-download', tab: null, entry: '资源下载怎么用', span: true },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9341', '--user-data-dir=/tmp/asset-shot-profile-frames',
  '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' });

let ws; const pending = new Map(); let msgId = 0;
const send = (m, p = {}) => new Promise((res, rej) => { const id = ++msgId; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method: m, params: p })); });

async function main() {
  let t = null;
  for (let i = 0; i < 60 && !t; i++) {
    try { const l = await (await fetch('http://127.0.0.1:9341/json')).json(); t = l.find((x) => x.type === 'page'); } catch {}
    if (!t) await sleep(250);
  }
  if (!t) throw new Error('CDP 未就绪');
  ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error('x')) : p.res(m.result); } };
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `try{localStorage.setItem('auth_token', ${JSON.stringify(TOK)})}catch(e){}` });
  const js = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 150)}` : r.result?.value;
  };

  const clickEntry = async (g) => {
    if (g.tab) {
      const tk = await js(`(() => { const t=Array.from(document.querySelectorAll('.ant-tabs-tab')).find(x=>x.textContent.includes('${g.tab}')); if(!t) return 'no-tab'; t.click(); return 'ok'; })()`);
      await sleep(2200);
      if (tk !== 'ok') return 'no-tab';
    }
    return await js(`(() => {
      const sel = ${g.btn ? '"button"' : '"span"'};
      const b = Array.from(document.querySelectorAll(sel)).find(x => x.textContent.includes('${g.entry}'));
      if(!b) return 'no-entry';
      b.click(); return 'ok';
    })()`);
  };

  const stepCount = async () => Number(await js(`document.querySelectorAll('.tg-dot').length`));
  const pause = async () => {
    await js(`(() => { const b=Array.from(document.querySelectorAll('.tg-ctrls button')).find(x=>x.textContent.includes('暂停')); b&&b.click(); })()`);
    await sleep(400);
  };
  const gotoStep = async (i) => {
    await js(`(() => { const d=document.querySelectorAll('.tg-dot')[${i}]; d&&d.click(); })()`);
    await sleep(800);
  };
  const stageRect = async () => await js(`(() => {
    const st = document.querySelector('.tg-stage');
    if (!st) return null;
    const r = st.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
  })()`);
  const samplePhase = async (tSec) => await js(`(() => {
    const st = document.querySelector('.tg-stage');
    if (!st) return 'NO-STAGE';
    st.getAnimations({subtree:true}).forEach((a) => { try { a.currentTime = ${Math.round(tSec * 1000)}; } catch (e) {} });
    return 'ok';
  })()`);

  const manifest = {};
  for (const g of GUIDES) {
    await send('Page.navigate', { url: `${BASE}${g.page}` });
    await sleep(4200);
    const open = await clickEntry(g);
    if (open !== 'ok') { console.log(`SKIP ${g.slug}: ${open}`); manifest[g.slug] = { error: open }; continue; }
    await sleep(1400);
    await pause();
    const n = await stepCount();
    manifest[g.slug] = { steps: n, frames: FRAMES, files: [] };
    for (let i = 0; i < n; i++) {
      await gotoStep(i);
      let rect = await stageRect();
      if (!rect) { console.log(`SKIP ${g.slug} s${i + 1}: NO-STAGE`); continue; }
      for (let f = 0; f < FRAMES; f++) {
        const phase = await samplePhase(f * PHASE);
        if (phase !== 'ok') { console.log(`WARN ${g.slug} s${i + 1} f${f}: ${phase}`); continue; }
        const { data } = await send('Page.captureScreenshot', {
          format: 'png',
          clip: { x: rect.x, y: rect.y, width: rect.w, height: rect.h, scale: 1 },
        });
        const p = `${OUT}${g.slug}/s${i + 1}/f${String(f).padStart(2, '0')}.png`;
        mkdirSync(p.substring(0, p.lastIndexOf('/')), { recursive: true });
        writeFileSync(p, Buffer.from(data, 'base64'));
        manifest[g.slug].files.push(`${g.slug}/s${i + 1}/f${String(f).padStart(2, '0')}.png`);
      }
      // 每步结束复位相位，避免残留
      await samplePhase(0);
    }
    console.log(`OK ${g.slug}: ${n} steps × ${FRAMES} frames = ${manifest[g.slug].files.length} files`);
    await js(`(() => { const x=document.querySelector('.ant-modal-close'); x&&x.click(); })()`);
    await sleep(600);
  }

  writeFileSync(`${OUT}frames-manifest.json`, JSON.stringify(manifest, null, 2));
  const total = Object.values(manifest).reduce((s, v) => s + (v.files?.length || 0), 0);
  console.log(`=== 帧图总计 ${total} 张 → ${OUT} ===`);
  chrome.kill();
  process.exit(0);
}
main().catch((e) => { console.error(e.message); chrome.kill(); process.exit(2); });
