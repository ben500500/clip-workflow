import React from 'react';
import {Composition} from 'remotion';
import {HighlightMix, computeMixLayout} from './components/HighlightMix';
import {
  DEFAULT_FPS,
  DEFAULT_HEIGHT,
  DEFAULT_TRANSITION_FRAMES,
  DEFAULT_WIDTH,
  type HighlightMixProps,
} from './types';

/**
 * Remotion 根组件：注册唯一 Composition `highlight-mix-enhanced`。
 * 实际渲染由 render.ts 注入完整 props.json（覆盖 defaultProps）。
 */
export const RemotionRoot: React.FC = () => {
  const defaultProps: HighlightMixProps = {
    durationInFrames: 30,
    fps: DEFAULT_FPS,
    width: DEFAULT_WIDTH,
    height: DEFAULT_HEIGHT,
    transitionFrames: DEFAULT_TRANSITION_FRAMES,
    segments: [],
    subtitles: [],
    intro: {title: '高光混剪', episode: ''},
    outro: {text: '感谢观看'},
  };

  return (
    <Composition
      id="highlight-mix-enhanced"
      component={HighlightMix}
      durationInFrames={30}
      fps={DEFAULT_FPS}
      width={DEFAULT_WIDTH}
      height={DEFAULT_HEIGHT}
      defaultProps={defaultProps}
      // 根据实际 props 动态计算渲染元数据：
      // - durationInFrames：片头+各段+片尾+转场重叠的真实时长（避免静态 30 帧截断）
      // - width/height/fps：跟随 props（后端 ffprobe 探测源视频方向后下发竖屏
      //   720x1280/1080x1920）——2026-11-20 修复：此前 Composition 尺寸写死
      //   1280x720 横屏，竖屏源被 cover 裁掉上下大半画面。
      calculateMetadata={({props}) => ({
        durationInFrames: Math.max(1, Math.round(computeMixLayout(props).totalFrames)),
        width: props.width ?? DEFAULT_WIDTH,
        height: props.height ?? DEFAULT_HEIGHT,
        fps: props.fps ?? DEFAULT_FPS,
        props,
      })}
    />
  );
};
