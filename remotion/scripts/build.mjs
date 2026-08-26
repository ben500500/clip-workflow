// 将 render.ts 编译为 CommonJS（dist/render.js），供后端以子进程调用。
import {build} from 'esbuild';
import {mkdirSync} from 'node:fs';

mkdirSync('dist', {recursive: true});

build({
  entryPoints: ['src/render.ts'],
  outfile: 'dist/render.js',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  sourcemap: false,
  loader: {'.node': 'file'},
  external: ['@remotion/bundler', '@remotion/renderer'],
  // rspack/原生绑定等 node 模块保持 external，由 node_modules 运行时解析
  packages: 'external',
}).then(() => {
  console.log('[build] dist/render.js compiled');
}).catch((err) => {
  console.error('[build] failed', err);
  process.exit(1);
});
