/**
 * Remotion 混剪增强数据契约（HighlightMixProps）。
 *
 * 与后端 `remotion_mix_config`（SliceTask.remotion_mix_config）JSON 一一对应，
 * 由 render.ts 从 `--props <props.json>` 注入，作为 `<Composition>` 的 defaultProps 与
 * 实际渲染 props 使用。
 */

/** 单个高光段：容器内本地路径 + 源内时间轴 + 可选标题 */
export interface Segment {
  /** 该段在容器内的本地绝对路径（后端任务预先下载到工作目录） */
  file: string;
  /** 源内时间轴起点（秒） */
  start: number;
  /** 源内时间轴终点（秒） */
  end: number;
  /** 段标题文案（可选，可在段上叠加） */
  title?: string;
}

/** 单条字幕：命中区间（秒）+ 文本 */
export interface Subtitle {
  start: number;
  end: number;
  text: string;
}

/** 片头配置 */
export interface IntroConfig {
  title?: string;
  episode?: string;
  /** 封面图本地路径（可选） */
  cover?: string;
}

/** 片尾配置 */
export interface OutroConfig {
  text?: string;
}

/** 字幕样式 */
export interface SubtitleStyle {
  /** 字号相对画布高度的比例（720p 时 0.22 → ~158px） */
  fontRatio?: number;
  /** 字幕文字颜色（CSS 十六进制） */
  color?: string;
  /** 字幕描边颜色 */
  borderColor?: string;
}

/** 段间转场类型 */
export type TransitionType = 'dissolve' | 'zoom' | 'slide';

/** 根组件 props：后端 config JSON 直接映射 */
export interface HighlightMixProps {
  /** 高光段列表（按源时间/评分顺序，引擎已排好序） */
  segments?: Segment[];
  /** 字幕列表（可空） */
  subtitles?: Subtitle[];
  /** 片头配置（可选） */
  intro?: IntroConfig;
  /** 片尾配置（可选） */
  outro?: OutroConfig;
  /** 输出帧率（默认 30） */
  fps?: number;
  /** 总帧数（由后端按片头+各段+片尾+转场时长换算） */
  durationInFrames?: number;
  /** 输出宽度（默认 1280） */
  width?: number;
  /** 输出高度（默认 720） */
  height?: number;
  /** 段间转场帧数（默认 12） */
  transitionFrames?: number;
  /** 转场类型（默认按 dissolve/zoom/slide 轮换） */
  transitionType?: TransitionType;
  /** 字幕样式 */
  subtitleStyle?: SubtitleStyle;
}

export const DEFAULT_WIDTH = 1280;
export const DEFAULT_HEIGHT = 720;
export const DEFAULT_FPS = 30;
export const DEFAULT_TRANSITION_FRAMES = 12;
