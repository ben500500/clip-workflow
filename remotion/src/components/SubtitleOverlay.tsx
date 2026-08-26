import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Subtitle, SubtitleStyle} from '../types';

/**
 * 字幕叠加组件（T3）。
 *
 * 按当前帧时间命中字幕列表（start/end 秒），叠加在当前画面上。
 * 支持入场/退场淡入淡出、描边、字号随画布高度比例缩放。
 */
export const SubtitleOverlay: React.FC<{
  subtitles?: Subtitle[];
  style?: SubtitleStyle;
}> = ({subtitles = [], style = {}}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();

  const time = frame / fps;
  const active = subtitles.find((s) => time >= s.start && time <= s.end);

  if (!active) {
    return null;
  }

  const fontRatio = style.fontRatio ?? 0.22;
  const fontSize = Math.round(height * fontRatio);
  const color = style.color ?? '#ffffff';
  const borderColor = style.borderColor ?? '#000000';

  // 字幕命中区间内的入场/退场淡入淡出（各 4 帧）
  const fadeIn = Math.min(1, (time - active.start) * fps / 4);
  const fadeOut = Math.min(1, (active.end - time) * fps / 4);
  const opacity = Math.max(0, Math.min(1, Math.min(fadeIn, fadeOut)));

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: 'center',
        paddingBottom: height * 0.08,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          fontSize,
          color,
          fontWeight: 700,
          textAlign: 'center',
          opacity,
          padding: '8px 24px',
          fontFamily: 'Noto Sans SC, sans-serif',
          WebkitTextStroke: `${Math.max(2, Math.round(fontSize * 0.06))}px ${borderColor}`,
          paintOrder: 'stroke fill',
          textShadow: '0 2px 8px rgba(0,0,0,0.6)',
          lineHeight: 1.4,
          maxWidth: '90%',
        }}
      >
        {active.text}
      </div>
    </AbsoluteFill>
  );
};
