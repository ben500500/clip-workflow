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
 * Remotion 根组件：注册唯一 Composition `highlight_mix_enhanced`。
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
      id="highlight_mix_enhanced"
      component={HighlightMix}
      durationInFrames={30}
      fps={DEFAULT_FPS}
      width={DEFAULT_WIDTH}
      height={DEFAULT_HEIGHT}
      defaultProps={defaultProps}
      // 根据实际 props（片头+各段+片尾+转场重叠）动态计算渲染时长，
      // 避免静态注册 30 帧导致真实混剪被截断成 1 秒。
      calculateMetadata={({props}) => ({
        durationInFrames: Math.max(1, Math.round(computeMixLayout(props).totalFrames)),
        props,
      })}
    />
  );
};
