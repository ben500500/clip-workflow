import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile, useVideoConfig} from 'remotion';
import type {Segment as SegmentData, Subtitle, SubtitleStyle} from '../types';
import {SubtitleOverlay} from './SubtitleOverlay';

/**
 * 单段高光渲染：OffthreadVideo 覆盖裁切 + 字幕叠加。
 * 外层由 HighlightMix 的 <Sequence> 提供时间定位，转场由外层 Transition 施加。
 *
 * 媒体路径契约：props 里只能传 public 目录相对名或 http(s) URL——Remotion 的
 * compositor 只从内部 HTTP 服务拉流（bundle 目录为根），绝对文件路径会被当成
 * URL 解析而 404。后端预先把源视频 symlink 进 public 目录。
 */
export const Segment: React.FC<{
  segment: SegmentData;
  subtitles?: Subtitle[];
  subtitleStyle?: SubtitleStyle;
}> = ({segment, subtitles, subtitleStyle}) => {
  const {height, fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {/* cover 裁切：视频等比填满画布；trimBefore/After 把源内 [start,end] 子段
          映射到本段时间线（单位为帧）——缺省时每段都从源视频 0 秒开始播，
          成片会变成「同一段开头画面反复重复」（2026-11-20 生产发现） */}
      <OffthreadVideo
        src={segment.file.startsWith('http') ? segment.file : staticFile(segment.file)}
        trimBefore={Math.round(segment.start * fps)}
        trimAfter={Math.round(segment.end * fps)}
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
