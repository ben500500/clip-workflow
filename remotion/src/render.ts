/**
 * Remotion 渲染 CLI 入口（T4）。
 *
 * 用法：
 *   node dist/render.js --props <props.json> --output <out.mp4> [--tier 720p|1080p]
 *
 * 流程：
 *   1. 解析 CLI 参数：props.json（HighlightMixProps 数据契约）与输出路径
 *   2. 用 @remotion/bundler 对 src/index.ts 即时 bundle
 *   3. selectComposition 选中 `highlight_mix_enhanced`，注入 props
 *   4. renderMedia 渲染 h264 mp4
 *   5. STDOUT 输出 `PROGRESS: <pct>%` 供后端解析回传进度
 *
 * 本机无 chromium 时不会实渲染；容器内由 REMOTION_CHROMIUM_EXECUTABLE 指定浏览器。
 */
import {bundle} from '@remotion/bundler';
import {selectComposition, renderMedia} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';

const COMPOSITION_ID = 'highlight_mix_enhanced';

/** 输出档位 → 分辨率 */
const TIERS: Record<string, {width: number; height: number}> = {
  '720p': {width: 1280, height: 720},
  '1080p': {width: 1920, height: 1080},
};

function parseArgs(argv: string[]) {
  const args: Record<string, string> = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const val = argv[i + 1];
      if (val && !val.startsWith('--')) {
        args[key] = val;
        i++;
      } else {
        args[key] = '';
      }
    }
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const propsPath = args['props'];
  const outputPath = args['output'];
  const tier = (args['tier'] || '720p').toLowerCase();

  if (!propsPath || !outputPath) {
    console.error('Usage: node render.js --props <props.json> --output <out.mp4> [--tier 720p|1080p]');
    process.exit(1);
  }

  // 1. 读取 props
  let props: Record<string, unknown>;
  try {
    props = JSON.parse(fs.readFileSync(propsPath, 'utf-8'));
  } catch (e) {
    console.error(`[render] 无法读取 props.json: ${propsPath}`, e);
    process.exit(1);
  }

  // 2. 按档位覆盖分辨率
  const tierCfg = TIERS[tier] || TIERS['720p'];
  props = {
    ...props,
    width: props.width ?? tierCfg.width,
    height: props.height ?? tierCfg.height,
    fps: props.fps ?? 30,
  };

  // 3. 即时 bundle
  console.error(`[render] bundling entry: ${path.resolve('src/index.ts')}`);
  const serveUrl = await bundle({
    entryPoint: path.resolve('src/index.ts'),
    // 在 docker 内不需要内置浏览器下载，交给运行时 chromium
  });

  // 4. 选中 Composition
  const composition = await selectComposition({
    serveUrl,
    id: COMPOSITION_ID,
    inputProps: props,
  });

  // 5. 渲染 h264 mp4
  console.error(`[render] rendering ${composition.width}x${composition.height}@${composition.fps}fps → ${outputPath}`);

  let lastPct = -1;
  await renderMedia({
    composition,
    serveUrl,
    codec: 'h264',
    outputLocation: outputPath,
    inputProps: props,
    onProgress: ({progress}) => {
      const pct = Math.round(progress * 100);
      if (pct !== lastPct) {
        lastPct = pct;
        // 供后端解析的进度行
        console.log(`PROGRESS: ${pct}%`);
      }
    },
  });

  console.error(`[render] done: ${outputPath}`);
}

main().catch((err) => {
  console.error('[render] fatal', err);
  process.exit(1);
});
