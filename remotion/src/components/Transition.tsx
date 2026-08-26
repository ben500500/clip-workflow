import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {TransitionType} from '../types';

/**
 * 段间转场包装组件。
 *
 * 包住子内容（一个高光段），在进入/退出时施加 dissolve / zoom / slide 动画，
 * 让硬切升级为平滑转场。转场时长由 transitionFrames 控制（默认 12 帧）。
 */
export const Transition: React.FC<{
  children: React.ReactNode;
  /** 转场类型：dissolve 淡入淡出 / zoom 拉近 / slide 滑入 */
  type: TransitionType;
  /** 转场帧数 */
  frames?: number;
}> = ({children, type = 'dissolve', frames = 12}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // 进入：前 transitionFrames 帧从 0 → 1
  const enter = interpolate(frame, [0, frames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  // 退出：最后 transitionFrames 帧从 1 → 0
  const exit = interpolate(frame, [frames, frames * 2], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  // 组合透明度：进入×退出
  const opacity = enter * exit;

  // 弹簧缓动（进入段）
  const eased = spring({
    frame: Math.min(frame, frames),
    fps,
    config: {damping: 200, stiffness: 200, mass: 0.8},
  });

  let style: React.CSSProperties = {
    opacity: Math.max(0, Math.min(1, opacity)),
  };

  if (type === 'zoom') {
    // zoom：从 0.85 拉到 1，再轻微回落
    const scale = interpolate(frame, [0, frames, frames * 2], [0.85, 1, 1.02], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    style = {...style, transform: `scale(${scale})`};
  } else if (type === 'slide') {
    // slide：从下方 8% 滑入
    const translateY = interpolate(frame, [0, frames], [frame, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    style = {...style, transform: `translateY(${translateY}px)`};
  } else {
    // dissolve：轻微上浮，默认
    const translateY = interpolate(frame, [0, frames], [eased * 12, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    style = {...style, transform: `translateY(${translateY}px)`};
  }

  return <div style={{...style, position: 'absolute', inset: 0}}>{children}</div>;
};
