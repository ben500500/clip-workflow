/**
 * 业务区板块「怎么用」内嵌动画（11-14 用户「把所有待办事项都安排下去」批准向素材库外铺）。
 *
 * 第一颗：发布管理 PublishFlowGuide——把本页既有的静态「发布流程指引」①→④ 升级成
 * 会动的分步版；静态版保留当速查手册，动画版管教会。话术逐字抄自：
 *  · PublishManagement.tsx 的指引 Modal 原文（「发布链路 = 成品库『一键发布』创建任务 →
 *    本页『发布任务』确认发布 → 审计可溯源」「窗口内随机选点错峰发布」「心跳检查置为 valid」…）
 *  · 按钮真字面：新建发布任务 / 确认发布 / 立即发布 / 新增配置 / 新增账号 / 新增自定义窗口
 * 改本页按钮文案请连改这里（X44/F72 耦合制度，CDP 断言把关）。
 */
import React, { useState } from 'react';
import StepGuide, {
  MockBtn, MockCallout, MockCard, MockChip, MockLines, MockPanel,
  MockSteps, MockTag,
} from './StepGuide';

export function PublishFlowGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="发布流程怎么用 · 60 秒动画版"
      tagline="成品库「一键发布」创建任务 → 本页「发布任务」确认发布 → 审计可溯源"
      footnote="登录态失效会导致发布失败——心跳检查保持 valid"
      steps={[
        {
          title: '第 1 步 · 前置准备（一次性）',
          sub: '发布配置＋视频号账号库＋登录态扫码，三样就绪才发得动',
          tips: [
            '「发布配置」Tab 新增配置：平台＋账号＋Chrome 调试端口＋每日上限＋发布间隔——每个发布账号对应独立的 Chrome 登录态',
            '「视频号账号」Tab 新增账号并绑定配置；要挂小程序先在「小程序链接」Tab 维护',
            '「运营者端口矩阵」Tab 选账号 →「登录态扫码」→ 微信扫码 →「心跳检查」置为 valid',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>发布配置</MockChip>　视频号 · Chrome 9222档 · 每日上限 · 间隔</div>
              <MockLines widths={['88%']} />
              <div style={{ marginBottom: 6 }}><MockChip>账号库</MockChip>　新增账号 → 绑定配置 → 小程序链接（可选）</div>
              <MockLines widths={['76%']} />
              <div><MockTag color="green">心跳检查 valid</MockTag><MockTag color="red">expired＝发不出</MockTag></div>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 2 步 · 去「成品预览」点一键发布',
          sub: '选平台可多选；发布素材自动带短标题/配文/标签',
          tips: [
            '选发布平台（如视频号＋抖音批量发布）→ 选发布账号（从账号库）与小程序链接',
            '「截图确认后发布」推荐选是——RPA 填好表单后截图人工确认，避免误发',
            '提交后自动创建发布任务并触发 RPA 发布，不用在这页手建',
          ],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 8 }}><b>一键发布</b>　平台：☑视频号 ☑抖音</div>
              <MockLines widths={['84%', '60%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue">发布素材：短标题/配文/标签自动代入</MockTag>
                <MockTag color="green">截图确认后发布：是（推荐）</MockTag>
              </div>
              <div style={{ marginTop: 10, textAlign: 'right' }}><MockBtn kind="primary">提交（创建任务＋触发 RPA）</MockBtn></div>
            </MockPanel>
          ),
          ms: 9000,
        },
        {
          title: '第 3 步 · 回本页「发布任务」确认发布',
          sub: '待确认 →「查看截图」→「确认发布」才算正式发出',
          tips: [
            '状态流转：待发布 → 待确认 → 已发布；失败会记录错误信息，死信任务可点「重发」',
            '未开启截图确认的任务会直接自动发布，无需人工确认',
            '本页「新建发布任务」是给补发/手工建单用的，正常链路从上一步来',
          ],
          stage: (
            <>
              <MockSteps items={['待发布', 'RPA 填表', '待确认', '确认发布', '已发布']} at={2} />
              <MockCard focus>
                <MockLines widths={['80%']} />
                <div style={{ marginTop: 8, textAlign: 'right' }}>
                  <MockBtn>查看截图</MockBtn>　<MockBtn kind="primary">确认发布</MockBtn>
                </div>
              </MockCard>
              <MockCallout pos="bottom">截图没问题再点「确认发布」——这一下才真发出去</MockCallout>
            </>
          ),
          ms: 9000,
        },
        {
          title: '第 4 步 · 定时窗口与审计',
          sub: '要错峰就挂定时窗口；发没发成、谁点的，账都在',
          tips: [
            '「定时发布时间窗口（预置 ＋ 自定义）」：选窗口即「窗口内随机选点错峰发布」；不够就「新增自定义窗口」',
            '「发布审计与可观测（仅管理员）」：每条任务的确认人、时间、错误信息可溯源',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>发布窗口</MockChip>　<MockTag color="default">选择发布窗口（窗口内随机选点错峰发布）</MockTag></div>
              <MockLines widths={['92%', '70%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue">09:12 已发布 · 确认人：小林</MockTag>
                <MockTag color="red">失败：登录态过期 → 可「重发」</MockTag>
              </div>
            </MockCard>
          ),
          ms: 9000,
        },
      ]}
    />
  );
}

/** 入口按钮小件（与素材库五板块同款紫色 ❓ 风格） */
export function BizGuideEntry({ label, onOpen }: { label: string; onOpen: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <span
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ cursor: 'pointer', fontSize: 12, color: '#722ed1', marginLeft: 6, whiteSpace: 'nowrap', opacity: hover ? 1 : 0.85 }}
    >
      ❓ {label}
    </span>
  );
}
