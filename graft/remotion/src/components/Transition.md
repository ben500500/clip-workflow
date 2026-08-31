# remotion/src/components/Transition.tsx

- Transition · function · L11-L72 — Transition: React.FC<{ children: React.ReactNode; /** 转场类型：dissolve 淡入淡出 / zoom 拉近 / slide 滑入 */ type: TransitionType; /** 转场帧数 */ frames?: number; /** 段总时长（帧），用于计算退出时序 */ durationInFrames?: number; }> = ({children, type = 'dissolve', frames = 12, durationInFrames})
