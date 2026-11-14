/**
 * 通用「怎么用」分步动画框架（2026-11-13 用户口径：教学内嵌产品界面，五板块全铺）。
 *
 * 由来：TrialProduceGuide（试产六步，a483d50 已上线）验证了形态可行——
 * 这里把「步骤圆点＋侧栏文案＋自动播＋控制器＋弹层骨架」抽成通用件，
 * 各板块只交「步骤配置＋每步画面」，教程越长越要复用，不然维护五份复制粘贴必漂移。
 *
 * 红线（继承 X44）：
 * · 画面里出现的按钮名/提示话术，一律从对应面板源码 grep 逐字抄，不许发明；
 * · 类名沿用 tg- 前缀——CDP 脚本（shoot-trial-guide.mjs）与后续各板块验收共用选择器；
 * · 纯 CSS＋React state，零新依赖；教程组件不参与任何写操作。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Modal, Space, Typography } from 'antd';
import { PauseCircleOutlined, PlayCircleOutlined, ThunderboltOutlined } from '@ant-design/icons';

const { Text, Paragraph } = Typography;

export interface GuideStep {
  title: string;
  sub: string;
  tips: string[];
  /** 该步的演出画面（各板块自带 mock 组件） */
  stage: React.ReactNode;
  /** 自动播时长 ms，缺省 7000 */
  ms?: number;
}

export interface StepGuideProps {
  open: boolean;
  onClose: () => void;
  /** 弹层标题主句，如「试产怎么用 · 60 秒动画版」 */
  headline: string;
  /** 标题旁一句副标语 */
  tagline: string;
  steps: GuideStep[];
  /** 侧栏底部的常驻提醒（橙字），如「试产片不进成片墙…」 */
  footnote?: string;
  okText?: string;
}

export default function StepGuide({
  open, onClose, headline, tagline, steps, footnote, okText = '学会了',
}: StepGuideProps) {
  const [step, setStep] = useState(0);
  const [tick, setTick] = useState(0);
  const [playing, setPlaying] = useState(true);
  const timerRef = useRef<number | null>(null);

  const goto = useCallback((i: number) => {
    setStep(((i % steps.length) + steps.length) % steps.length);
    setTick((t) => t + 1);
  }, [steps.length]);

  useEffect(() => {
    if (!open) { setStep(0); setTick(0); setPlaying(true); return; }
    if (!playing) return;
    timerRef.current = window.setTimeout(() => {
      setStep((s) => (s + 1) % steps.length);
      setTick((t) => t + 1);
    }, steps[step]?.ms ?? 7000);
    return () => { if (timerRef.current) window.clearTimeout(timerRef.current); };
  }, [open, playing, step, steps]);

  const cur = steps[step];
  if (!cur) return null;
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
          {headline}
          <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>{tagline}</Text>
        </Space>
      }
    >
      <style>{CSS}</style>
      <div className="tg-wrap">
        <div className="tg-dots">
          {steps.map((s, i) => (
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
          {/* key 强制当步重放入场动画 */}
          <div className="tg-stage" key={`st-${step}-${tick}`}>{cur.stage}</div>
          <div className="tg-side">
            <Paragraph strong style={{ marginBottom: 2 }}>{cur.title}</Paragraph>
            <Text type="secondary">{cur.sub}</Text>
            <ul className="tg-tips">
              {cur.tips.map((t) => <li key={t}>{t}</li>)}
            </ul>
            {footnote && (
              <Text type="warning" style={{ fontSize: 12 }}>{footnote}</Text>
            )}
          </div>
        </div>
        <div className="tg-ctrls">
          <Button size="small" onClick={() => { setPlaying(false); goto(step - 1); }}>上一步</Button>
          <Button
            size="small" type="text"
            icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={() => setPlaying((p) => !p)}
          >
            {playing ? '暂停' : '连播'}
          </Button>
          <Button size="small" onClick={() => { setPlaying(false); goto(step + 1); }}>下一步</Button>
          <Button size="small" type="primary" onClick={onClose}>{okText}，去试一下</Button>
        </div>
      </div>
    </Modal>
  );
}

/* ───────── 通用 mock 原语：各板块画面用它们拼，样式与真机同色系 ───────── */

export function MockChip({ color = 'orange', children }: { color?: string; children: React.ReactNode }) {
  return <span className={`tg-chip tg-chip-${color}`}>{children}</span>;
}

export function MockCard({ children, focus, dim }: { children: React.ReactNode; focus?: boolean; dim?: boolean }) {
  return <div className={`tg-card ${focus ? 'tg-card-focus' : ''} ${dim ? 'tg-dim' : ''}`}>{children}</div>;
}

export function MockLines({ widths = ['92%', '78%', '85%'] }: { widths?: string[] }) {
  return <div className="tg-lines">{widths.map((w, i) => <i key={i} style={{ width: w }} />)}</div>;
}

export function MockBtn({ kind = '', children }: { kind?: '' | 'primary' | 'danger' | 'violet' | 'muted'; children: React.ReactNode }) {
  return <span className={`tg-btn ${kind ? `tg-btn-${kind}` : ''}`}>{children}</span>;
}

export function MockTag({ color = 'blue', children }: { color?: string; children: React.ReactNode }) {
  return <span className={`tg-tag tg-tag-${color}`}>{children}</span>;
}

/** 流程总览条：①导入→②…→⑤成片墙，当前所在环节高亮（多份教程共用同一张地图） */
export function MockFlow({ at, note }: { at: string; note?: string }) {
  const nodes = ['① 导入', '② 素材与文案', '③ 文案审核', '④ 生产与投板', '⑤ 成片墙'];
  return (
    <div className="tg-flow">
      {nodes.map((n) => (
        <span key={n} className={`tg-flow-n ${n === at ? 'on' : ''}`}>{n}</span>
      ))}
      {note && <div className="tg-flow-note">{note}</div>}
    </div>
  );
}

/** 通用横向步骤条（板块内小流程，如「勾→点→等→报」） */
export function MockSteps({ items, at }: { items: string[]; at: number }) {
  return (
    <div className="tg-hsteps">
      {items.map((s, i) => (
        <span key={s} className={`tg-hstep ${i === at ? 'on' : ''} ${i < at ? 'done' : ''}`}>{s}</span>
      ))}
    </div>
  );
}

export function MockTextarea({ children, caret }: { children: React.ReactNode; caret?: boolean }) {
  return <div className={`tg-textarea ${caret ? 'tg-blink-caret' : ''}`}>{children}</div>;
}

export function MockCallout({ children, pos = 'top' }: { children: React.ReactNode; pos?: string }) {
  return <div className={`tg-callout tg-callout-${pos}`}>{children}</div>;
}

export function MockCursor({ cls }: { cls: string }) {
  return <div className={`tg-cursor ${cls}`}>➤</div>;
}

export function MockPanel({ children }: { children: React.ReactNode }) {
  return <div className="tg-modal tg-modal-in">{children}</div>;
}

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

.tg-card{position:relative;width:100%;background:#fff;border:1px solid #eee;border-radius:8px;
  padding:10px 12px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.tg-card-focus{border-color:#b37feb;box-shadow:0 0 0 3px #f9f0ff}
.tg-dim{opacity:.35}
.tg-lines i{display:block;height:8px;background:#f0f0f0;border-radius:3px;margin:6px 0}

.tg-chip{display:inline-block;background:#fff7e6;color:#d46b08;border-radius:4px;padding:0 6px;font-size:12px}
.tg-chip-green{background:#f6ffed;color:#389e0d}
.tg-chip-blue{background:#e6f4ff;color:#1677ff}
.tg-chip-red{background:#fff1f0;color:#cf1322}
.tg-tag{display:inline-block;border-radius:4px;padding:1px 8px;font-size:12px;margin:3px 6px 3px 0}
.tg-tag-blue{background:#e6f4ff;color:#1677ff;border:1px solid #91caff}
.tg-tag-green{background:#f6ffed;color:#389e0d;border:1px solid #b7eb8f}
.tg-tag-red{background:#fff1f0;color:#cf1322;border:1px solid #ffa39e}
.tg-tag-orange{background:#fff7e6;color:#d46b08;border:1px solid #ffd591}
.tg-tag-default{background:#fafafa;color:#666;border:1px solid #ddd}
.tg-btn{display:inline-block;border:1px solid #d9d9d9;border-radius:6px;padding:1px 8px;
  font-size:12px;background:#fff}
.tg-btn-primary{background:#1677ff;border-color:#1677ff;color:#fff}
.tg-btn-danger{color:#cf1322;border-color:#ffa39e}
.tg-btn-violet{background:#722ed1;border-color:#722ed1;color:#fff}
.tg-btn-muted{background:#f5f5f5;color:#bfbfbf;border-style:dashed}

.tg-flow{margin-top:8px}
.tg-flow-n{display:inline-block;padding:5px 9px;margin:3px 2px;border:1px solid #ddd;border-radius:8px;
  background:#fff;color:#999;font-size:12px;position:relative}
.tg-flow-n+.tg-flow-n::before{content:"→";position:absolute;left:-11px;top:50%;transform:translateY(-50%);color:#ccc}
.tg-flow-n.on{border-color:#722ed1;color:#722ed1;background:#f9f0ff;animation:tg-pulse 1.4s infinite;
  font-weight:600}
.tg-flow-note{margin-top:10px;color:#888;font-size:12px}

.tg-hsteps{margin:10px 0}
.tg-hstep{display:inline-block;padding:4px 10px;margin:2px 3px;border-radius:14px;font-size:12px;
  background:#fff;border:1px solid #e0e0e0;color:#999}
.tg-hstep.done{border-color:#b37feb;color:#b37feb;background:#fbf7ff}
.tg-hstep.on{border-color:#722ed1;color:#fff;background:#722ed1;animation:tg-pulse 1.4s infinite}

.tg-textarea{border:1px solid #d9d9d9;border-radius:6px;padding:8px 10px;line-height:1.7;
  color:#555;min-height:90px;position:relative;background:#fff;font-size:12px}
.tg-blink-caret::after{content:"|";color:#722ed1;animation:tg-blink 1s infinite}

.tg-modal{position:absolute;inset:16px 40px;background:#fff;border-radius:10px;z-index:4;
  box-shadow:0 6px 24px rgba(0,0,0,.16);padding:14px 16px}
.tg-modal-in{animation:tg-pop .55s both}

.tg-callout{position:absolute;background:#722ed1;color:#fff;border-radius:6px;
  padding:4px 10px;font-size:12px;animation:tg-fadein .6s both;z-index:6}
.tg-callout-top{right:14px;top:14px}
.tg-callout-bottom{left:50%;bottom:14px;transform:translateX(-50%);animation:tg-floatup .8s .4s both}
.tg-callout-center{left:50%;top:46%;transform:translateX(-50%);animation:tg-floatup 1s .5s both}

.tg-cursor{position:absolute;font-size:16px;color:#333;z-index:5;text-shadow:0 1px 2px #fff}

@keyframes tg-fadein{from{opacity:0}to{opacity:1}}
@keyframes tg-floatup{from{opacity:0;transform:translate(-50%,10px)}
  to{opacity:1;transform:translate(-50%,0)}}
@keyframes tg-pop{from{opacity:0;transform:scale(.85)}to{opacity:1;transform:scale(1)}}
@keyframes tg-blink{0%,100%{opacity:1}50%{opacity:.15}}
@keyframes tg-pulse{0%,100%{box-shadow:0 0 0 0 rgba(114,46,209,.45)}
  50%{box-shadow:0 0 0 8px rgba(114,46,209,0)}}
`;
