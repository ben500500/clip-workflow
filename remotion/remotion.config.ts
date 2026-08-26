import {Config} from '@remotion/cli/config';

Config.setEntryPoint('./src/index.ts');
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);

// Chromium 可执行路径：容器内由 REMOTION_CHROMIUM_EXECUTABLE 注入（node:20-slim + chromium），
// 未注入时 Remotion 会回退到其内置/自动下载的浏览器。
if (process.env.REMOTION_CHROMIUM_EXECUTABLE) {
  Config.setBrowserExecutable(process.env.REMOTION_CHROMIUM_EXECUTABLE);
}
