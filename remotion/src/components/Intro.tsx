import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {IntroConfig} from '../types';

/**
 * 片头标题卡：剧集标题 + 集数 + 可选封面图。
 * 入场淡入上移，末尾淡出，为混剪开场做包装。
 */
export const Intro: React.FC<{
  intro: IntroConfig;
  /** 片头时长（帧） */
  durationInFrames: number;
}> = ({intro, durationInFrames}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fadeOut = interpolate(frame, [durationInFrames - 15, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = fadeIn * fadeOut;
  const translateY = interpolate(frame, [0, 25], [30, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const title = intro.title || '高光混剪';
  const episode = intro.episode || '';

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: '#0d0d12',
        opacity,
      }}
    >
      <div style={{transform: `translateY(${translateY}px)`, textAlign: 'center', padding: 40}}>
        {intro.cover ? (
          <img
            src={intro.cover}
            style={{
              width: width * 0.4,
              borderRadius: 16,
              marginBottom: 30,
              objectFit: 'cover',
            }}
            alt="cover"
          />
        ) : null}
        {episode ? (
          <div
            style={{
              fontSize: height * 0.05,
              color: '#EDD736',
              fontWeight: 600,
              letterSpacing: 4,
              marginBottom: 16,
              fontFamily: 'Noto Sans SC, sans-serif',
            }}
          >
            {episode}
          </div>
        ) : null}
        <div
          style={{
            fontSize: height * 0.1,
            color: '#ffffff',
            fontWeight: 800,
            fontFamily: 'Noto Sans SC, sans-serif',
          }}
        >
          {title}
        </div>
      </div>
    </AbsoluteFill>
  );
};
