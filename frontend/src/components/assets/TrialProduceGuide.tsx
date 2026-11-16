/**
 * 「试产怎么用」六步动画引导（2026-11-13 用户提：一线看不懂试产流程）。
 *
 * 设计红线：
 * · 画面所有角标/按钮/提示词的**字面**与 AssetReviewCard / AssetReviewPanel 真实 UI 一字不差
 *   （蓝标「试产中：豆包出片（约 25 分钟），任务条会报」、绿标「试产片已回：看完给结论」、
 *    主按钮「看试产片 · 对比判定」、ok「投豆包试产（占 1 个号池额度）」……），
 *   教程画假词比不画更坏——用户照着找不到按钮会直接怀疑系统。
 * · 纯 CSS keyframes＋步进状态机，零依赖零网络；每步自动播，可点圆点跳步／暂停。
 * · 讲清三件一线最容易慌的事：①待审不用先过审也能试（不打回采集人）；②点完窗口就关，
 *   进度在卡上看，不用守着；③号池一发即烧——废片再试是**新建**一单，会再占 1 个号。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Modal, Space, Typography } from 'antd';
import { PauseCircleOutlined, PlayCircleOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { FramePlayer } from './StepGuide';

const { Text, Paragraph } = Typography;

/** 每步自动播放时长（毫秒）——第 3 步要演完「关窗→排队」给足，第 6 步收尾带回流箭头 */
const STEP_MS = [6200, 6600, 8200, 5200, 7200, 8600];

const STEPS: { title: string; sub: string; tips: string[] }[] = [
  {
    title: '第 1 步 · 在哪点：审核卡上的「试产」',
    sub: '鼠标移到右侧操作区，点紫色的「试产」',
    tips: [
      '待审核的候选就能试——不用先过审，也不会打回给采集人重提',
      '用途：提示词拿去豆包出一条验证片，先看片再决定这条文案的去向',
    ],
  },
  {
    title: '第 2 步 · 弹窗里改提示词',
    sub: '没起草的当场自动起草，草稿直接能改',
    tips: [
      '框里就是投给豆包的完整提示词：改角色、换镜头、调句子都行',
      '「改词再试一轮」时会预填上一轮的词——迭代不用从空白重写',
    ],
  },
  {
    title: '第 3 步 · 投出去：窗口自动关，进度看角标',
    sub: '点「投豆包试产」后什么都不用守着',
    tips: [
      '投出去窗口立刻自动关闭；卡片亮蓝标「试产中」，按钮同时变灰防重复投',
      '⚠️ 号池一发即烧：投出去的每一步都占 1 个号池额度，别连续点',
    ],
  },
  {
    title: '第 4 步 · 等片回来（约 25 分钟）',
    sub: '豆包队列快慢会有浮动，任务条会报进度',
    tips: [
      '蓝标「试产中：豆包出片（约 25 分钟），任务条会报」',
      '片回到这条卡上：角标自动转绿「试产片已回：看完给结论」',
    ],
  },
  {
    title: '第 5 步 · 对比着看：原片 ｜ 试产片',
    sub: '点主按钮「看试产片 · 对比判定」开对比视图',
    tips: [
      '左边是原片，右边是这条提示词产出的试产片，可各自播放',
      '下方同时展示本轮所用提示词与候选文案——词和片对得上号才敢定',
    ],
  },
  {
    title: '第 6 步 · 给结论：定稿 或 废片',
    sub: '看完随手二选一，流程就闭环了',
    tips: [
      '「定稿」＝这条文案过审进入正式投产；试产片本身不进成片墙、不进交付包',
      '「废片」＝本单作废、文案仍留在待审——回第 2 步改词新建一单再试',
    ],
  },
];

export default function TrialProduceGuide({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(true);
  const timerRef = useRef<number | null>(null);

  const goto = useCallback((i: number) => {
    setStep(((i % STEPS.length) + STEPS.length) % STEPS.length);
  }, []);

  useEffect(() => {
    if (!open) {
      setStep(0);
      setPlaying(true);
      return;
    }
    if (!playing) return;
    timerRef.current = window.setTimeout(() => {
      setStep((s) => (s + 1) % STEPS.length);
    }, STEP_MS[step]);
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [open, playing, step]);

  const cur = STEPS[step];
  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={880}
      destroyOnClose
      title={
        <Space>
          <ThunderboltOutlined style={{ color: '#722ed1' }} />
          试产怎么用 · 60 秒动画版
          <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
            审核员的验片工具：改提示词 → 投豆包 → 看片 → 定稿/废片，全程不打回采集人
          </Text>
        </Space>
      }
    >
      <style>{CSS}</style>
      <div className="tg-wrap">
        {/* 步骤指示 */}
        <div className="tg-dots">
          {STEPS.map((s, i) => (
            <button
              type="button"
              key={s.title}
              className={`tg-dot ${i === step ? 'on' : ''} ${i < step ? 'done' : ''}`}
              onClick={() => { setPlaying(false); goto(i); }}
              title={s.title}
            >
              {i + 1}
            </button>
          ))}
        </div>
        <div className="tg-cols">
          <FramePlayer frameDir="/guides/trial" step={step} playing={playing} />
          <div className="tg-side">
            <Paragraph strong style={{ marginBottom: 2 }}>{cur.title}</Paragraph>
            <Text type="secondary">{cur.sub}</Text>
            <ul className="tg-tips">
              {cur.tips.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
            <Text type="warning" style={{ fontSize: 12 }}>
              试产片不进成片墙、不进交付包——它是给你看的参考片
            </Text>
          </div>
        </div>
        <div className="tg-ctrls">
          <Button size="small" onClick={() => { setPlaying(false); goto(step - 1); }}>上一步</Button>
          <Button
            size="small"
            type="text"
            icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={() => setPlaying((p) => !p)}
          >
            {playing ? '暂停' : '连播'}
          </Button>
          <Button size="small" onClick={() => { setPlaying(false); goto(step + 1); }}>下一步</Button>
          <Button size="small" type="primary" onClick={onClose}>学会了，去试一条</Button>
        </div>
      </div>
    </Modal>
  );
}

/** 全部演出动画：tg- 前缀避免撞全局样式 */
const CSS = `
.tg-wrap{font-size:13px}
.tg-dots{display:flex;gap:8px;margin-bottom:10px}
.tg-dot{width:26px;height:26px;border-radius:50%;border:1.5px solid #d9d9d9;background:#fff;
  color:#999;cursor:pointer;font-weight:600;line-height:1}
.tg-dot.on{border-color:#722ed1;color:#722ed1;box-shadow:0 0 0 3px #f9f0ff}
.tg-dot.done{border-color:#b37feb;color:#b37feb}
.tg-cols{display:flex;gap:14px}
.tg-stage{position:relative;flex:0 0 520px;height:330px;background:#f5f3ff;border-radius:10px;
  overflow:hidden;padding:12px}
.tg-side{flex:1;min-width:0}
.tg-tips{margin:10px 0;padding-left:18px}
.tg-tips li{margin-bottom:6px;line-height:1.5}
.tg-ctrls{display:flex;justify-content:center;gap:10px;margin-top:12px}
`;
