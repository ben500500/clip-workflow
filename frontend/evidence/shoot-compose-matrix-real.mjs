#!/usr/bin/env node
/*
 * 屏 3 · 组合出片 —— **真后端 + 真数据** 的 CDP 实测门（11-24 本地实测）
 *
 * 与 shoot-compose-matrix.mjs 的分工：
 *   · 那一个打 mock，验的是「请求形状＋后端一定拒的东西界面会不会先拦」。
 *   · 这一个打**真站点**（真 FastAPI＋真 ffmpeg＋真 MinIO＋真片子），验的是
 *     「真数据在这一屏点得动吗、拼出来的片子真能播吗、出包拿到的是真 zip 吗」。
 *   mock 永远造不出「presign 打不通导致出包 502」这一类只有真链路才露出来的坑，
 *   11-24 本机实测就是这么抓到 MINIO_EXTERNAL_ENDPOINT 的。
 *
 * 判据（全部从界面/网络取证，不写死数据条数，换库换机都能跑）：
 *   R1 极简视图有「组合出片」这一屏
 *   R2 钩子候选与正片候选都从真库拉到了行
 *   R3 取数形状：钩子按 kind 点名、正片带 media_kind=video
 *   R4 勾 1×1 → 汇总三个数＋0 元话术
 *   R5 叠加走真预设（库里有行、下拉能选中）
 *   R6 POST /assets/compose/matrix 只打一次，body 逐字段合口径
 *   R7 轮询到终态：界面出「成功 1 条／失败 0 条」，耗时是真转码耗时
 *   R8 产物真能播：拿 output_id 走 /preview，页面里 <video> 真解码出画面
 *   R9 出包同一条口：POST /assets/outputs/package，zip 落盘且里面是真 mp4
 *   R10 全程无未捕获页面报错；主按钮（打到服务端的动作）≤6 次
 *
 * 用法：
 *   SITE=http://127.0.0.1 SITE_USER=admin SITE_PASS=xxx \
 *     node frontend/evidence/shoot-compose-matrix-real.mjs
 *   打现网：SITE=http://192.168.1.163 SITE_USER=... SITE_PASS=...（凭据走环境变量，不落文件）
 *   端口：CDP 9347（**绝不用 9223**，那是用户的隧道口）。
 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import http from 'node:http';

const SITE = (process.env.SITE || 'http://127.0.0.1').replace(/\/+$/, '');
const USER = process.env.SITE_USER || 'admin';
const PASS = process.env.SITE_PASS || '';
const CDP_PORT = Number(process.env.CDP_PORT || 9347);
const OUT = process.env.SHOT_OUT || '/tmp/shots-compose-matrix-real';
const DL = join(OUT, 'dl');
mkdirSync(DL, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
const parseJson = (s) => { try { return typeof s === 'string' ? JSON.parse(s) : s; } catch { return null; } };

/** 直连站点打 API（带真 token），用于前置准备与事后取证 */
const api = (method, path, body, token) => new Promise((resolve) => {
  const u = new URL(SITE + path);
  const data = body === undefined ? null : Buffer.from(JSON.stringify(body));
  const req = http.request(
    { hostname: u.hostname, port: u.port || 80, path: u.pathname + u.search, method,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}),
                 ...(data ? { 'Content-Length': data.length } : {}) },
      timeout: 120000 },
    (res) => { const buf = []; res.on('data', (c) => buf.push(c)); res.on('end', () => resolve({ status: res.statusCode, json: parseJson(Buffer.concat(buf).toString('utf8')) })); },
  );
  req.on('error', (e) => resolve({ status: 0, json: { detail: String(e) } }));
  if (data) req.write(data);
  req.end();
});

const results = [];
const assert = (n, c, d = '') => { results.push({ n, c: !!c }); console.log(`${c ? 'PASS' : 'FAIL'} ${n}${c ? '' : ' — ' + flat(d).slice(0, 320)}`); };

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${CDP_PORT}`, '--user-data-dir=/tmp/asset-shot-profile-compose-real',
  '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' });

let ws; const pending = new Map(); let msgId = 0;
const send = (m, params = {}) => new Promise((res, rej) => {
  const id = ++msgId; pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method: m, params }));
});

const netLog = [];        // 每一次打到 /api/ 的请求（方法＋路径＋query＋body＋状态码）
const respBodies = [];    // 关心的响应体（jobs 轮询、package）
const pageErrors = [];
const clicks = [];

async function main() {
  if (!PASS) { console.error('SITE_PASS 没给（真后端要真登录）'); process.exit(2); }

  // ── 前置：真登录 + 把视图切到极简（真偏好接口，不是 mock 返回值）──
  const login = await api('POST', '/api/auth/login', { username: USER, password: PASS });
  const TOKEN = login.json?.access_token || '';
  if (!TOKEN) { console.error('登录失败', JSON.stringify(login).slice(0, 200)); process.exit(2); }
  await api('PUT', '/api/assets/ui/preferences', { ui_config: { asset_library_mode: 'simple' } }, TOKEN);
  const before = await api('GET', '/api/assets/outputs?kind=composed&page=1&page_size=5', undefined, TOKEN);
  console.log(`前置：登录 ok｜真库现有 composed 产物 ${before.json?.total ?? '?'} 条`);

  let target = null;
  for (let i = 0; i < 60 && !target; i++) {
    try { const l = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json`)).json(); target = l.find((x) => x.type === 'page'); } catch {}
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
    if (m.method === 'Network.requestWillBeSent') {
      const r = m.params.request || {};
      if (!r.url.includes('/api/')) return;
      const u = new URL(r.url);
      netLog.push({ id: m.params.requestId, m: r.method, p: u.pathname, q: u.search, b: r.postData ? parseJson(r.postData) : null, status: 0 });
    }
    if (m.method === 'Network.responseReceived') {
      const u = new URL(m.params.response?.url || '');
      const rec = netLog.find((x) => x.id === m.params.requestId);
      if (rec) rec.status = m.params.response?.status || 0;
      if (u.pathname.includes('/api/') && m.params.response?.status >= 200 && m.params.response?.status < 300) {
        send('Network.getResponseBody', { requestId: m.params.requestId })
          .then((r) => { if (r?.body) respBodies.push({ p: u.pathname + u.search, status: m.params.response.status, body: r.base64Encoded ? Buffer.from(r.body, 'base64') : Buffer.from(r.body, 'utf8') }); })
          .catch(() => {});
      }
    }
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params?.exceptionDetails || {};
      pageErrors.push(`EXC ${String(d.exception?.description || d.text || JSON.stringify(d)).replace(/\s+/g, ' ').slice(0, 260)}`);
    }
    if (m.method === 'Runtime.consoleAPICalled' && ['error'].includes(m.params?.type)) {
      const txt = (m.params.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
      if (txt) pageErrors.push(`console.error ${String(txt).replace(/\s+/g, ' ').slice(0, 240)}`);
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  try { await send('Log.enable'); } catch {}
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `try{localStorage.setItem('auth_token','${TOKEN}');}catch(e){}` });
  for (const method of ['Browser.setDownloadBehavior', 'Page.setDownloadBehavior']) {
    try { await send(method, { behavior: 'allow', downloadPath: DL, eventsEnabled: true }); } catch {}
  }

  const js = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    return r.exceptionDetails ? `EXC ${JSON.stringify(r.exceptionDetails).slice(0, 200)}` : r.result?.value;
  };
  const shot = async (n) => { const { data } = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${OUT}/${n}.png`, Buffer.from(data, 'base64')); };
  const goto = async (path) => {
    await send('Page.navigate', { url: SITE + path });
    for (let i = 0; i < 40; i++) { if (await js('document.readyState') === 'complete') break; await sleep(120); }
  };
  const CARD = `(function(){const norm=(s)=>(s||'').replace(/\\s+/g,' ').trim();return Array.from(document.querySelectorAll('.ant-card')).find((c)=>{const h=c.querySelector('.ant-card-head-title');return h&&norm(h.textContent).indexOf('组合出片')===0;});})()`;
  const rectOf = (elExpr) => `(function(){const el=${elExpr};if(!el)return null;el.scrollIntoView({block:'center',inline:'center'});const r=el.getBoundingClientRect();if(!r.width&&!r.height)return null;return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,t:(el.textContent||el.value||'').replace(/\\s+/g,' ').trim().slice(0,46)});})()`;
  const click = async (elExpr, label) => {
    const hit = parseJson(await js(rectOf(elExpr)));
    if (!hit) { console.log(`  · 点不到（不存在或不可见）：${label}`); return null; }
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: hit.x, y: hit.y, button: 'left', clickCount: 1 });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: hit.x, y: hit.y, button: 'left', clickCount: 1 });
    clicks.push({ label, hit: hit.t });
    await sleep(300);
    return hit;
  };
  const btn = (txt) => `(function(){const card=${CARD};if(!card)return null;return Array.from(card.querySelectorAll('button')).find((b)=>(b.textContent||'').replace(/\\s+/g,' ').trim().indexOf(${JSON.stringify(txt)})>=0);})()`;
  const tableRow = (tblIdx, rowIdx) => `(function(){const card=${CARD};if(!card)return null;const t=(card.querySelectorAll('.ant-table'))[${tblIdx}];if(!t)return null;const r=t.querySelectorAll('.ant-table-tbody tr.ant-table-row')[${rowIdx}];if(!r)return null;return r.querySelector('.ant-checkbox-wrapper');})()`;
  const cardText = () => js(`(function(){const card=${CARD};return card?card.innerText.replace(/\\s+/g,' '):'NO-CARD';})()`);
  const rowCount = (tblIdx) => js(`(function(){const card=${CARD};if(!card)return -1;const t=(card.querySelectorAll('.ant-table'))[${tblIdx}];if(!t)return -1;return Array.from(t.querySelectorAll('.ant-table-tbody tr.ant-table-row')).filter(function(r){const c=r.querySelector('.ant-checkbox-input');return c&&!c.disabled;}).length;})()`);
  const clearToasts = () => js(`(function(){document.querySelectorAll('.ant-message,.ant-notification').forEach((n)=>{n.style.display='none';});return 1;})()`);

  await goto('/assets');
  for (let i = 0; i < 40; i++) { if (await js(`(function(){const c=${CARD};return !!c;})()`)) break; await sleep(400); }
  await sleep(2000);

  // ── R1/R2/R3 ──
  assert('R1 真后端下极简视图出现「组合出片」这一屏', (await js(`(function(){return !!(${CARD});})()`)) === true,
    `${String(await cardText()).slice(0, 120)}｜页面报错 ${JSON.stringify(pageErrors.slice(0, 3))}`);
  const nHook = await rowCount(0);
  const nMat = await rowCount(1);
  assert('R2 钩子池与正片池都从真库拉到了行（不是空表）', nHook > 0 && nMat > 0, `钩子 ${nHook} 行｜正片 ${nMat} 行`);
  const pulls = netLog.filter((x) => x.p === '/api/assets/outputs' || x.p === '/api/assets');
  assert('R3 取数形状：钩子按 kind 点名（doubao_raw/composed）、正片带 media_kind=video',
    pulls.some((x) => /kind=doubao_raw/.test(x.q)) && pulls.some((x) => /kind=composed/.test(x.q)) && pulls.some((x) => /media_kind=video/.test(x.q)),
    JSON.stringify(pulls.map((x) => `${x.m} ${x.p}?${x.q}`).slice(0, 6)));
  await shot('r1-screen-real-data');

  // ── R4 勾 1×1 ──
  await click(tableRow(0, 0), '勾第 1 支钩子');
  await click(tableRow(1, 0), '勾第 1 条正片');
  await sleep(500);
  const t4 = flat(await cardText());
  const cnt = (t4.match(/(\d+)\s*支钩子\s*×\s*(\d+)\s*条正片\s*＝\s*(\d+)\s*条成片/) || []).map(Number);
  assert('R4 勾 1×1 → 汇总三个数说得清，且明写 0 元',
    cnt[1] === 1 && cnt[2] === 1 && cnt[3] === 1 && /0 元/.test(t4), t4.slice(0, 260));
  await shot('r4-one-by-one');

  // ── R5 叠加走真预设 ──
  await click(`(function(){const card=${CARD};return Array.from(card.querySelectorAll('.ant-segmented-item')).find((x)=>(x.textContent||'').trim()==='用预设');})()`, '叠加＝用预设');
  await sleep(700);
  await click(`(function(){const card=${CARD};const s=Array.from(card.querySelectorAll('.ant-select')).find((x)=>/预设|挑一套/.test(x.innerText));return s?s.querySelector('.ant-select-selector'):null;})()`, '预设下拉');
  await sleep(800);
  const presetOpts = parseJson(await js(`(function(){return JSON.stringify(Array.from(document.querySelectorAll('.ant-select-item-option')).map((x)=>x.innerText.replace(/\\s+/g,' ').trim()).slice(0,8));})()`)) || [];
  await click(`(function(){return Array.from(document.querySelectorAll('.ant-select-item-option')).find((x)=>!x.classList.contains('ant-select-item-option-disabled'));})()`, '选中第一套真预设');
  await sleep(600);
  assert('R5 库里已有真预设行、下拉列得出来、点得中（11-24 本机建的那套）',
    presetOpts.length > 0 && !/还没选预设/.test(flat(await cardText())), JSON.stringify(presetOpts).slice(0, 240));
  await shot('r5-preset-real');

  // ── R6/R7 真跑一次组合导出（真 ffmpeg）──
  // 后台任务的终态**先从台账读**（api 直连），再回头看界面有没有跟上：
  // 界面没跟上＝前端问题；界面跟上了但台账里是失败＝数据/环境问题。
  // 混在一起判，就会把「本机 MinIO 少一个原片」报成「这一屏跑不通」。
  await clearToasts();
  await click(btn('组合导出'), '主按钮：组合导出');
  let jobId = null;
  for (let i = 0; i < 30 && !jobId; i++) {
    const ack = respBodies.filter((x) => x.p.startsWith('/api/assets/compose/matrix')).map((x) => parseJson(x.body.toString('utf8'))).pop();
    jobId = ack?.job_id || null;
    if (!jobId && ack && !ack.queued) break;   // 同步档：没有 job，直接就是结果
    await sleep(1000);
  }
  let job = null;
  if (jobId) {
    for (let i = 0; i < 150; i++) {
      job = (await api('GET', `/api/assets/jobs/${jobId}`, undefined, TOKEN)).json;
      if (job && ['succeeded', 'failed', 'cancelled'].includes(job.status)) break;
      await sleep(2000);
    }
  }
  const cellsFromJob = (job?.result?.results || []);
  const envGap = cellsFromJob.filter((c) => !c.ok && /取回第\d+段失败/.test(String(c.error || '')));
  let doneTxt = '';
  for (let i = 0; i < 40; i++) {
    doneTxt = flat(await cardText()) + ' ' + flat(await js(`(function(){return Array.from(document.querySelectorAll('.ant-message-notice-content,.ant-alert-message')).map((x)=>x.innerText).join(' ｜ ');})()`));
    if (/成功 \d+ 条／失败 \d+ 条/.test(doneTxt) || /全部失败|逐格原因/.test(doneTxt)) break;
    await sleep(2000);
  }
  await sleep(800);
  const matrix = netLog.find((x) => x.m === 'POST' && x.p === '/api/assets/compose/matrix');
  assert('R6 POST /assets/compose/matrix 只打一次，body 逐字段合口径（async_mode 真、预设走 id、不带 overlay_params）',
    netLog.filter((x) => x.p === '/api/assets/compose/matrix').length === 1
    && (matrix?.b?.hook_output_ids || []).length === 1 && (matrix?.b?.material_ids || []).length === 1
    && matrix?.b?.async_mode === true && !!matrix?.b?.overlay_preset_id && matrix?.b?.overlay_params == null,
    JSON.stringify(matrix?.b || {}).slice(0, 300));
  assert('R7 台账跑到终态，界面在终态后跟上并说同一套数（真转码，收口带耗时）',
    netLog.filter((x) => x.p.startsWith('/api/assets/jobs')).length >= 2
    && (job?.status === 'succeeded' ? /成功 1 条／失败 0 条/.test(doneTxt)
        // 耗时是真转码耗时：界面显示小数（如「耗时 33.34s」），且必须 >=1 秒才叫「真跑了活」
        && (() => { const m = doneTxt.match(/耗时 (\d+(?:\.\d+)?)s/); return !!m && Number(m[1]) >= 1; })()
        : /全部失败|逐格原因/.test(doneTxt)),
    `台账 ${job?.status}｜界面 ${doneTxt.slice(-260)}`);
  if (envGap.length) {
    console.log(`  · 环境缺件（不是产品问题）：本机 MinIO 没有这些原片 → ${envGap.map((c) => String(c.error).slice(0, 110)).join(' ;; ')}`);
  }
  await shot('r7-matrix-done');

  // 从台账响应里取真 output_id（取证，不靠界面文案猜）
  const outId = (cellsFromJob.find((c) => c.ok && c.output_id) || {}).output_id || null;
  assert('R8 任务台账回读：真产物 output_id 落库（不是界面自说自话）',
    !!outId && cellsFromJob.filter((c) => c.ok).length === 1, JSON.stringify(cellsFromJob).slice(0, 300));

  // ── R9 真片子在浏览器里真能解码播放 ──
  if (!outId) { console.log('  · 跳过 R9～R11：这一格没拼出片（原因见上面的环境缺件行），没有产物可播可包'); }
  const play = outId ? await js(`(async function(){
    const r = await fetch('/api/assets/outputs/${outId}/preview', { headers: { Authorization: 'Bearer ${TOKEN}' } });
    const j = await r.json();
    const url = j.url || j.preview_url || null;
    if (!url) return JSON.stringify({ ok: false, why: 'no-url', j: j });
    const v = document.createElement('video');
    v.muted = true; v.playsInline = true; v.src = url; document.body.appendChild(v);
    const st = await new Promise((res) => {
      v.addEventListener('loadeddata', () => res('data'));
      v.addEventListener('error', () => res('err'));
      setTimeout(() => res('timeout'), 25000);
    });
    const out = { ok: st === 'data' && v.videoWidth > 0, st, w: v.videoWidth, h: v.videoHeight, dur: v.duration, mode: j.mode };
    v.remove(); return JSON.stringify(out);
  })()`) : '{"skipped":true}';
  const playInfo = parseJson(play) || {};
  assert('R9 产物是真片子：浏览器拿 /preview 的签名地址真解码出画面（宽高＋时长都在）',
    !!outId && playInfo.ok === true && playInfo.w > 0 && Number(playInfo.dur) > 5, play);

  // ── R10 出包：同一条口 + 真 zip 落盘 ──
  if (outId) await click(btn('打包这 1 条'), '主按钮：打包这 1 条（zip）');
  await sleep(4000);
  const pkg = netLog.find((x) => x.m === 'POST' && x.p === '/api/assets/outputs/package');
  assert('R10 出包打的就是成片墙那条口，ids＝成功格 output_id',
    !!outId && !!pkg && (pkg.b?.ids || []).length === 1 && pkg.b.ids[0] === outId && pkg.status === 200,
    JSON.stringify({ b: pkg?.b, status: pkg?.status }).slice(0, 220));
  const zipFile = (() => { try { return readdirSync(DL).filter((n) => /zip$/i.test(n)).sort((a, b) => statSync(join(DL, b)).size - statSync(join(DL, a)).size)[0] || null; } catch { return null; } })();
  if (zipFile) {
    const buf = readFileSync(join(DL, zipFile));
    writeFileSync(join(OUT, `zipcheck-${zipFile}.txt`), `size=${buf.length} magic=${buf.slice(0, 4).toString('hex')}`);
    assert('R11 zip 真落盘、是真 zip、体积是片子量级（不是空壳冒充）',
      buf.slice(0, 2).toString('latin1') === 'PK' && buf.length > 500000, `${zipFile} ${buf.length}B`);
  } else {
    assert('R11 zip 落盘（headless 下载策略限制时只算环境限制，R10 的 200 才是判据）', pkg?.status === 200, '未落盘');
  }
  await shot('r11-package');

  // ── R12 全程干净 ──
  assert('R12 全程无未捕获的页面报错', pageErrors.length === 0, pageErrors.slice(0, 4).join(' ｜ '));
  const primaries = clicks.filter((c) => /主按钮/.test(c.label));
  assert(`R13 主按钮（打到服务端的动作）共 ${primaries.length} 次 ≤6`, primaries.length <= 6, JSON.stringify(primaries));

  const summary = results.reduce((a, r) => { a[r.c ? 'pass' : 'fail']++; return a; }, { pass: 0, fail: 0 });
  writeFileSync(join(OUT, 'netlog.json'), JSON.stringify(netLog, null, 2));
  writeFileSync(join(OUT, 'report.json'), JSON.stringify({ results, clicks, pageErrors, matrix: matrix?.b, cells: cellsFromJob, job, envGap, playInfo, site: SITE }, null, 2));
  console.log(`\n总计 ${summary.pass}/${results.length} PASS，取证与截图在 ${OUT}/`);
  process.exitCode = summary.fail ? 1 : 0;
}

main().catch((e) => { console.error('CDP 脚本异常', e); process.exitCode = 3; })
  .finally(async () => {
    try { ws && ws.close(); } catch {}
    chrome.kill('SIGKILL');
  });
