import React from 'react';
import {AbsoluteFill, OffthreadVideo, useVideoConfig} from 'remotion';
import type {Segment as SegmentData, Subtitle, SubtitleStyle} from '../types';
import {SubtitleOverlay} from './SubtitleOverlay';

/**
 * 单段高光渲染：OffthreadVideo 覆盖裁切 + 字幕叠加。
 * 外层由 HighlightMix 的 <Sequence> 提供时间定位，转场由外层 Transition 施加。
 */
export const Segment: React.FC<{
  segment: SegmentData;
  subtitles?: Subtitle[];
  subtitleStyle?: SubtitleStyle;
}> = ({segment, subtitles, subtitleStyle}) => {
  const {height} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {/* cover 裁切：视频等比填满画布 */}
      <OffthreadVideo
        src={segment.file}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover',
        }}
      />
      {/* 段标题（可选） */}
      {segment.title ? (
        <div
          style={{
            position: 'absolute',
            top: 20,
            left: 24,
            fontSize: height * 0.06,
            color: '#ffffff',
            fontWeight: 700,
            fontFamily: 'Noto Sans SC, sans-serif',
            textShadow: '0 2px 8px rgba(0,0,0,0.8)',
          }}
        >
          {segment.title}
        </div>
      ) : null}
      <SubtitleOverlay subtitles={subtitles} style={subtitleStyle} />
    </AbsoluteFill>
  );
};
