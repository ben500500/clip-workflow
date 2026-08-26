# clip-remotion — Remotion 混剪增强渲染工程（P1 MVP）

Remotion（React 视频编程框架）渲染子项目，用于给现有 ffmpeg concat 高光混剪成品做
**模板化增强包装**（片头 / 片尾 / 段间转场 / 动态字幕）。

## 目录结构

```
remotion/
├── package.json              # @remotion/bundler + renderer + cli
├── tsconfig.json             # strict + ES2022 + react-jsx
├── remotion.config.ts        # entry → src/index.ts；REMOTION_CHROMIUM_EXECUTABLE 注入
├── scripts/build.mjs         # esbuild 编译 render.ts → dist/render.js
├── src/
│   ├── index.ts              # registerRoot(RemotionRoot)
│   ├── RemotionRoot.tsx      # 注册 Composition: highlight_mix_enhanced
│   ├── render.ts             # CLI 入口（props 注入 + renderMedia + PROGRESS 输出）
│   ├── types.ts              # HighlightMixProps 数据契约
│   └── components/
│       ├── HighlightMix.tsx  # 根编排：片头 + 段序列 + 片尾 + 段间转场
│       ├── Segment.tsx       # 单段高光（OffthreadVideo + 字幕）
│       ├── Intro.tsx         # 片头标题卡
│       ├── Outro.tsx         # 片尾包装
│       ├── Transition.tsx    # 段间转场（dissolve/zoom/slide）
│       └── SubtitleOverlay.tsx # 字幕叠加
```

## 构建

```bash
npm install
npm run build        # 产出 dist/render.js（esbuild 编译）
npm run typecheck    # tsc --noEmit
```

## 渲染

```bash
node dist/render.js --props <props.json> --output <out.mp4> [--tier 720p|1080p]
```

- 从 `<props.json>` 读取 `HighlightMixProps`（与后端 `remotion_mix_config` 一一对应）
- `@remotion/bundler` 即时 bundle → `selectComposition` → `renderMedia` 渲染 h264 mp4
- STDOUT 输出 `PROGRESS: <pct>%` 供后端解析回传进度
- 容器内由 `REMOTION_CHROMIUM_EXECUTABLE` 指定 chromium 路径（node:20-slim + chromium）

## 数据契约（HighlightMixProps）

```ts
interface HighlightMixProps {
  segments: {file: string; start: number; end: number; title?: string}[];
  subtitles?: {start: number; end: number; text: string}[];
  intro?: {title?: string; episode?: string; cover?: string};
  outro?: {text?: string};
  fps?: number;              // 默认 30
  durationInFrames: number;
  width?: number;            // 默认 1280
  height?: number;           // 默认 720
  transitionFrames?: number; // 段间转场帧数，默认 12
  transitionType?: 'dissolve' | 'zoom' | 'slide';
  subtitleStyle?: {fontRatio?: number; color?: string; borderColor?: string};
}
```

## 镜像基础

`node:20-slim + chromium`，容器内安装 `fonts-noto-cjk` 以支持中文字幕/标题。
