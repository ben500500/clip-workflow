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

/** 微型审核卡 */
function MiniCard({ step, phase, dim }: { step: number; phase: number; dim?: boolean }) {
  // phase: 卡内容随步骤变的“演出状态”，step 决定挂哪组 class
  const trial = step >= 2;
  return (
    <div className={`tg-card ${step === 0 ? 'tg-card-focus' : ''} ${dim ? 'tg-dim' : ''}`}>
      <div className="tg-card-head">
        <span className="tg-chip">待审</span>
        <span className="tg-code">8QZYV · 候选 #3</span>
      </div>
      <div className="tg-lines">
        <i style={{ width: '92%' }} />
        <i style={{ width: '78%' }} />
        <i style={{ width: '85%' }} />
      </div>
      {/* 角标与按钮：完全照 AssetReviewCard 的真实文案与颜色 */}
      {phase >= 3 && phase < 4 && (
        <div className={`tg-badge ${trial ? 'show' : ''}`}>
          <span className="tg-tag tg-tag-blue">试产中：豆包出片（约 25 分钟），任务条会报</span>
        </div>
      )}
      {phase >= 4 && (
        <div className="tg-badge show">
          <span className="tg-tag tg-tag-green">试产片已回：看完给结论</span>
          <span className="tg-btn tg-btn-primary">看试产片 · 对比判定</span>
          <span className="tg-btn">直接定稿</span>
          <span className="tg-btn tg-btn-danger">废片</span>
        </div>
      )}
      <div className="tg-card-ops">
        {phase >= 5 ? (
          <span className="tg-btn-lg tg-btn-muted">试产中…（1 条在豆包）</span>
        ) : (
          <span className={`tg-btn-lg tg-btn-violet ${step === 0 ? 'tg-pulse' : ''}`}>试产</span>
        )}
      </div>
    </div>
  );
}

/** 演出层：光标、弹窗、对比视图、判定印章都画在这里 */
function Stage({ step, tick }: { step: number; tick: number }) {
  // tick 强制重放当步 keyframes（重新挂载）
  switch (step) {
    case 0:
      return (
        <div className="tg-stage" key={`s0-${tick}`}>
          <div className="tg-cursor tg-cursor-to-trial">➤</div>
          <MiniCard step={0} phase={0} />
          <div className="tg-callout tg-callout-trial">在这里点「试产」——不用先过审</div>
        </div>
      );
    case 1:
      return (
        <div className="tg-stage" key={`s1-${tick}`}>
          <MiniCard step={1} phase={1} />
          <div className="tg-modal tg-modal-in">
            <div className="tg-modal-title">试产：8QZYV（第 3 条候选）</div>
            <div className="tg-draft">✍️ 已按这条稿子当场起草（可改）</div>
            <div className="tg-textarea tg-blink-caret">
              ① 场景：深夜的普通家庭卧室<br />② 人物：婆婆把主角赶到客厅……<br />③ 「把存折收好，别声张」
            </div>
            <div className="tg-modal-foot">
              <span className="tg-btn">取消</span>
              <span className={`tg-btn tg-btn-primary ${step === 1 ? 'tg-pulse-late' : ''}`}>
                投豆包试产（占 1 个号池额度）
              </span>
            </div>
          </div>
        </div>
      );
    case 2:
      return (
        <div className="tg-stage" key={`s2-${tick}`}>
          <div className="tg-modal tg-modal-out" />
          <MiniCard step={2} phase={3} />
          <div className="tg-cursor tg-cursor-away">➤</div>
          <div className="tg-callout tg-callout-center">窗口自己关——去审下一条，不用守着</div>
        </div>
      );
    case 3:
      return (
        <div className="tg-stage" key={`s3-${tick}`}>
          <MiniCard step={3} phase={3} />
          <div className="tg-queue">
            <span className="tg-dots tg-dots-1">● ● ●</span>
            <span className="tg-queue-txt">豆包队列里 · 约 25 分钟</span>
          </div>
        </div>
      );
    case 4:
      return (
        <div className="tg-stage" key={`s4-${tick}`}>
          <MiniCard step={4} phase={4} />
          <div className="tg-compare tg-modal-in">
            <div className="tg-compare-title">试产判定：8QZYV（第 3 条候选）</div>
            <div className="tg-compare-body">
              <div className="tg-player"><span className="tg-play">▶</span><b>原片</b></div>
              <div className="tg-player tg-player-win"><span className="tg-play">▶</span><b>试产片</b></div>
            </div>
            <div className="tg-compare-prompt">本轮提示词：①场景…②矛盾…③引爆…</div>
          </div>
        </div>
      );
    default:
      return (
        <div className="tg-stage" key={`s5-${tick}`}>
          {/* 第 6 步＝第 5 步对比弹窗的「给结论」瞬间：印章落在弹窗底部按钮上方（与真机一致） */}
          <MiniCard step={5} phase={4} dim />
          <div className="tg-compare">
            <div className="tg-compare-title">试产判定：8QZYV（第 3 条候选）</div>
            <div className="tg-compare-body">
              <div className="tg-player"><span className="tg-play">▶</span><b>原片</b></div>
              <div className="tg-player tg-player-win"><span className="tg-play">▶</span><b>试产片</b></div>
            </div>
            <div className="tg-compare-foot">
              <span className="tg-btn tg-btn-primary">定稿（文案过审）</span>
              <span className="tg-btn tg-btn-danger">废片</span>
            </div>
            <div className="tg-verdict">
              <span className="tg-stamp tg-stamp-ok">定稿 ✓</span>
            </div>
          </div>
          <div className="tg-loop">
            <span className="tg-loop-arrow">↺</span>
            <span className="tg-loop-txt">选了「废片」→ 单作废、文案留待审——改词新建一单再试，回第 2 步</span>
          </div>
        </div>
      );
  }
}

export default function TrialProduceGuide({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [step, setStep] = useState(0);
  const [tick, setTick] = useState(0);
  const [playing, setPlaying] = useState(true);
  const timerRef = useRef<number | null>(null);

  const goto = useCallback((i: number) => {
    setStep(((i % STEPS.length) + STEPS.length) % STEPS.length);
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    if (!open) {
      setStep(0);
      setTick(0);
      setPlaying(true);
      return;
    }
    if (!playing) return;
    timerRef.current = window.setTimeout(() => {
      setStep((s) => (s + 1) % STEPS.length);
      setTick((t) => t + 1);
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
          <Stage step={step} tick={tick} />
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

/* 迷你卡 */
.tg-card{position:relative;width:460px;background:#fff;border:1px solid #eee;border-radius:8px;
  padding:10px 12px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.tg-card-focus{border-color:#b37feb;box-shadow:0 0 0 3px #f9f0ff}
.tg-card-head{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.tg-chip{background:#fff7e6;color:#d46b08;border-radius:4px;padding:0 6px;font-size:12px}
.tg-code{color:#999;font-size:12px}
.tg-lines i{display:block;height:8px;background:#f0f0f0;border-radius:3px;margin:6px 0}
.tg-card-ops{position:absolute;right:10px;top:38px;display:flex;flex-direction:column;gap:6px}

/* 真实文案的标签与按钮 */
.tg-tag{display:inline-block;border-radius:4px;padding:1px 8px;font-size:12px;margin:3px 6px 3px 0}
.tg-tag-blue{background:#e6f4ff;color:#1677ff;border:1px solid #91caff}
.tg-tag-green{background:#f6ffed;color:#389e0d;border:1px solid #b7eb8f}
.tg-btn{display:inline-block;border:1px solid #d9d9d9;border-radius:6px;padding:1px 8px;
  font-size:12px;background:#fff}
.tg-btn-primary{background:#1677ff;border-color:#1677ff;color:#fff}
.tg-btn-danger{color:#cf1322;border-color:#ffa39e}
.tg-btn-violet{background:#722ed1;border-color:#722ed1;color:#fff;border-radius:6px;padding:2px 14px;font-size:12px}
.tg-btn-lg{border-radius:6px;padding:3px 14px;font-size:12px;border:1px solid #d9d9d9;background:#fff}
.tg-btn-muted{background:#f5f5f5;color:#bfbfbf;border-style:dashed}
.tg-badge{margin-top:6px;animation:tg-fadein .5s both}

/* 光标 */
.tg-cursor{position:absolute;font-size:16px;color:#333;z-index:5;text-shadow:0 1px 2px #fff}
.tg-cursor-to-trial{top:250px;left:-30px;animation:tg-move-to-trial 2.6s .2s both, tg-click .5s 2.9s both}
.tg-cursor-away{top:60px;right:220px;animation:tg-cursor-fade 1.2s .8s both}

/* 弹层（第2步） */
.tg-modal{position:absolute;inset:16px 40px;background:#fff;border-radius:10px;z-index:4;
  box-shadow:0 6px 24px rgba(0,0,0,.16);padding:14px 16px}
.tg-modal-in{animation:tg-pop .55s both}
.tg-modal-out{animation:tg-pop-out .45s both;pointer-events:none}
.tg-modal-title{font-weight:600;margin-bottom:8px}
.tg-draft{display:inline-block;background:#f6ffed;color:#389e0d;border:1px solid #b7eb8f;
  border-radius:4px;padding:1px 8px;font-size:12px;margin-bottom:8px}
.tg-textarea{border:1px solid #d9d9d9;border-radius:6px;padding:8px 10px;line-height:1.7;
  color:#555;min-height:120px;position:relative}
.tg-blink-caret::after{content:"|";color:#722ed1;animation:tg-blink 1s infinite}
.tg-modal-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:10px}

.tg-callout{position:absolute;background:#722ed1;color:#fff;border-radius:6px;
  padding:4px 10px;font-size:12px;animation:tg-fadein .6s both;z-index:6}
.tg-callout-trial{right:14px;top:14px}
.tg-callout-center{left:50%;top:46%;transform:translateX(-50%);animation:tg-floatup 1s .5s both}

/* 队列（第4步） */
.tg-queue{margin-top:26px;text-align:center;color:#722ed1}
.tg-dots-1{display:inline-block;animation:tg-blink 1.4s infinite;letter-spacing:6px}
.tg-queue-txt{display:inline-block;padding:2px 10px;border:1px dashed #b37feb;border-radius:6px;
  font-size:12px;background:#fff}

/* 对比视图（第5步） */
.tg-compare{position:absolute;inset:30px 30px 56px;z-index:4}
.tg-compare-title{font-weight:600;margin-bottom:8px}
.tg-compare-body{display:flex;gap:10px}
.tg-player{flex:1;height:140px;background:#1f1f1f;color:#fff;border-radius:8px;display:flex;
  flex-direction:column;align-items:center;justify-content:center;gap:6px}
.tg-player-win{border:2px solid #52c41a}
.tg-play{font-size:22px;animation:tg-blink 1.6s infinite}
.tg-compare-foot{display:flex;gap:8px;justify-content:flex-end;margin-top:10px}
.tg-dim{opacity:.35}
.tg-compare .tg-verdict{position:absolute;right:-6px;top:-18px}
.tg-compare-prompt{margin-top:8px;background:#fafafa;border:1px dashed #ddd;border-radius:6px;
  padding:6px 8px;color:#888;font-size:12px}

/* 判定（第6步） */
.tg-verdict{position:absolute;right:34px;top:56px;z-index:5}
.tg-stamp{display:block;border-radius:8px;padding:6px 16px;font-weight:700;margin-bottom:10px;font-size:15px}
.tg-stamp-ok{background:#f6ffed;color:#389e0d;border:2px solid #389e0d;
  animation:tg-stamp-in .5s .8s both, tg-shake .3s 1.3s both}
.tg-stamp-no{background:#fff1f0;color:#cf1322;border:2px dashed #cf1322;opacity:.55;
  animation:tg-fadein .6s 2s both}
.tg-loop{position:absolute;left:24px;bottom:20px;color:#722ed1;font-size:12px;
  animation:tg-floatup .8s 2.6s both}
.tg-loop-arrow{font-size:18px;display:inline-block;margin-right:6px;
  animation:tg-spin 2.4s 3s infinite linear}

/* 强调脉动 */
.tg-pulse{animation:tg-pulse 1.1s .6s 2 both}
.tg-pulse-late{animation:tg-pulse 1.1s 2.2s 2 both}

@keyframes tg-fadein{from{opacity:0}to{opacity:1}}
@keyframes tg-floatup{from{opacity:0;transform:translate(-50%,10px)}
  to{opacity:1;transform:translate(-50%,0)}}
@keyframes tg-pop{from{opacity:0;transform:scale(.85)}to{opacity:1;transform:scale(1)}}
@keyframes tg-pop-out{from{opacity:1;transform:scale(1)}to{opacity:0;transform:scale(.9)}}
@keyframes tg-blink{0%,100%{opacity:1}50%{opacity:.15}}
@keyframes tg-move-to-trial{
  0%{top:250px;left:-30px}
  60%{top:88px;left:392px}
  100%{top:88px;left:392px}
}
@keyframes tg-click{0%,100%{transform:scale(1)}50%{transform:scale(.7)}}
@keyframes tg-cursor-fade{from{opacity:1}to{opacity:0}}
@keyframes tg-pulse{0%,100%{box-shadow:0 0 0 0 rgba(114,46,209,.45)}
  50%{box-shadow:0 0 0 8px rgba(114,46,209,0)}}
@keyframes tg-stamp-in{from{opacity:0;transform:scale(2) rotate(8deg)}
  to{opacity:1;transform:scale(1) rotate(-4deg)}}
@keyframes tg-shake{0%,100%{transform:rotate(-4deg)}25%{transform:rotate(-1deg)}
  75%{transform:rotate(-6deg)}}
@keyframes tg-spin{from{transform:rotate(0)}to{transform:rotate(-360deg)}}
`;
