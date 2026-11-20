import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import type {OutroConfig} from '../types';

/**
 * 片尾包装卡：结束文案 + 关注引导。
 */
export const Outro: React.FC<{
  outro: OutroConfig;
  durationInFrames: number;
}> = ({outro, durationInFrames}) => {
  const frame = useCurrentFrame();
  const fadeIn = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fadeOut = interpolate(frame, [durationInFrames - 15, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = fadeIn * fadeOut;

  const text = outro.text || '感谢观看 · 一键三连支持一下吧！';
  const subtitle = outro.subtitle !== undefined ? outro.subtitle : '点赞 · 收藏 · 关注';
  const background = outro.background || '#0d0d12';

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: background,
        opacity,
      }}
    >
      <div
        style={{
          fontSize: 44,
          color: '#ffffff',
          fontWeight: 700,
          textAlign: 'center',
          padding: 40,
          fontFamily: 'Noto Sans SC, sans-serif',
        }}
      >
        {text}
      </div>
      {subtitle ? (
        <div
          style={{
            fontSize: 24,
            color: '#EDD736',
            marginTop: 20,
            fontFamily: 'Noto Sans SC, sans-serif',
          }}
        >
          {subtitle}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
