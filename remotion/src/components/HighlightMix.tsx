import React from 'react';
import {AbsoluteFill, Sequence, useVideoConfig} from 'remotion';
import type {HighlightMixProps, TransitionType} from '../types';
import {DEFAULT_TRANSITION_FRAMES} from '../types';
import {Intro} from './Intro';
import {Outro} from './Outro';
import {Segment} from './Segment';
import {Transition} from './Transition';

/**
 * 混剪增强根编排组件（T2）。
 *
 * 时间轴布局：
 *   [片头][段0][段1..段N][片尾]
 * 段与段之间自动插入 transitionFrames 帧的转场重叠（dissolve/zoom/slide 轮换）。
 * 各段以 <Sequence from=... durationInFrames=...> 定位到绝对时间轴。
 */
export const HighlightMix: React.FC<HighlightMixProps> = ({
  segments = [],
  subtitles,
  intro,
  outro,
  transitionFrames = DEFAULT_TRANSITION_FRAMES,
  transitionType,
  subtitleStyle,
}) => {
  const {fps, height} = useVideoConfig();

  // ── 计算各段时间轴 ──
  const introFrames = intro ? Math.round((intro.title || intro.episode || intro.cover ? 3.2 : 2) * fps) : 0;
  const outroFrames = outro ? Math.round(2.5 * fps) : 0;

  const segFrames = segments.map((s) => Math.round((s.end - s.start) * fps));

  // 各段在绝对时间轴的起始帧（含转场重叠）
  let cursor = introFrames;
  const segStarts: number[] = [];
  for (let i = 0; i < segments.length; i++) {
    segStarts.push(cursor);
    // 下一段与当前段重叠 transitionFrames 帧（转场过渡区间）
    cursor += segFrames[i] - (i < segments.length - 1 ? Math.min(transitionFrames, segFrames[i]) : 0);
  }
  const bodyEnd = cursor;
  const outroStart = bodyEnd;

  // 转场类型轮换：显式指定则统一，否则按 dissolve → zoom → slide 循环
  const types: TransitionType[] = ['dissolve', 'zoom', 'slide'];

  return (
    <AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden'}}>
      {/* 片头 */}
      {intro ? (
        <Sequence from={0} durationInFrames={introFrames}>
          <Intro intro={intro} durationInFrames={introFrames} />
        </Sequence>
      ) : null}

      {/* 高光段序列 */}
      {segments.map((seg, i) => {
        const type = transitionType ?? types[i % types.length];
        const start = segStarts[i];
        const dur = segFrames[i];
        return (
          <Sequence key={i} from={start} durationInFrames={dur}>
            <Transition type={type} frames={Math.min(transitionFrames, dur)}>
              <Segment segment={seg} subtitles={subtitles} subtitleStyle={subtitleStyle} />
            </Transition>
          </Sequence>
        );
      })}

      {/* 片尾 */}
      {outro ? (
        <Sequence from={outroStart} durationInFrames={outroFrames}>
          <Outro outro={outro} durationInFrames={outroFrames} />
        </Sequence>
      ) : null}

      {/* 底部安全边距占位（无实际作用，保持呼吸感） */}
      <AbsoluteFill style={{pointerEvents: 'none'}}>
        <div style={{position: 'absolute', bottom: height * 0.02, width: '100%'}} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
