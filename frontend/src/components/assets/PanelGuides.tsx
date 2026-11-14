/**
 * 素材库五板块「怎么用」内嵌动画（2026-11-13 用户口径：不光试产，其他板块也要）。
 *
 * 每个板块一个薄壳组件（StepGuide ＋ 步骤配置），话术全部逐字抄自对应面板源码：
 *  · ① ImportGuide        ← AssetImportPanel 的 placeholder/提示原文
 *  · ② CopyGuide          ← AssetListPanel 反推/出文案链路（含「图片不反推」白话）
 *  · ③ ReviewGuide        ← AssetReviewPanel/Card 审核动作（试产另有专属动画，不重复）
 *  · ④ ProduceGuide       ← AssetProductionPanel 四档状态话术＋投板抽屉 tooltip 原文
 *  · ⑤ OutputGuide        ← AssetOutputWall 下载/交付包话术
 * 改任何面板的主按钮文案时，请连改这里（CDP 各板块断言会替你把关）。
 */
import React, { useState } from 'react';
import StepGuide, {
  MockBtn, MockCallout, MockCard, MockChip, MockFlow, MockLines, MockPanel,
  MockSteps, MockTag, MockTextarea,
} from './StepGuide';

/* ───────────────────────── ① 导入 ───────────────────────── */

export function ImportGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="导入怎么用 · 40 秒动画版"
      tagline="链接或文案进批次 → 自动下载原片 → 一键跳 ② 继续加工"
      footnote="批次名可以留空——留空自动命名，不拦你"
      steps={[
        {
          title: '第 1 步 · 粘链接就行',
          sub: '一行一条分享链接，整段含中文的分享文案也能直接粘',
          tips: [
            '「一行一条分享链接（可以整段粘含中文的分享文案，后端自己提 http token）」——不用自己挑链接',
            '例：https://v.douyin.com/xxxx/ 这剧太上头了 ← 整句粘进来也对',
          ],
          stage: (
            <>
              <MockTextarea caret>
                https://v.douyin.com/Ab1Cd2/ 这剧太上头了<br />
                她替姐姐嫁的第二天，新郎出现在婚礼上 https://v.douyin.com/Ef3Gh4/
              </MockTextarea>
              <MockCallout pos="bottom">后端自己提 http token——不用洗数据</MockCallout>
            </>
          ),
        },
        {
          title: '第 2 步 · 没有链接？直接粘文案',
          sub: '一条文案一段，空行分隔；勾上自动下载原片',
          tips: [
            '「一条文案一段（空行分隔）」——先有稿子后配视频也走得通',
            '默认勾「导入后自动下载原片」：原片进自有桶，后面反推/回源都不求人',
          ],
          stage: (
            <>
              <MockTextarea>
                总裁摘下手表坐在塑料凳上吃泡面，秘书问他为什么<br /><br />
                他寻子坠崖挂在歪脖子树上，拼死跃进山洞竟挖出黄金
              </MockTextarea>
              <div style={{ marginTop: 8 }}>
                <MockTag color="green">✓ 导入后自动下载原片</MockTag>
              </div>
            </>
          ),
        },
        {
          title: '第 3 步 · 批次名与分类（都可省）',
          sub: '批次名留空自动命名；分类不选就整批未分类',
          tips: [
            '「批次名（可选，留空自动命名）」——赶时间可以直接点导入',
            '分类决定后面出文案用哪套原型词表；拿不准就先不选，② 里还能补',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 8 }}><MockChip>批次</MockChip>　批次名（可选，留空自动命名）</div>
              <MockLines widths={['46%']} />
              <div style={{ marginTop: 8 }}><MockChip>分类</MockChip>　可不选（这批全标未分类）</div>
            </MockCard>
          ),
        },
        {
          title: '第 4 步 · 提交后一键跳 ②',
          sub: '导入成功，批次码点一下就带着筛选跳到素材列表',
          tips: [
            '不用手动切页签——批次码就是跳转按钮（onSelectBatch 直达 ②）',
            '接下来在 ② 反推文案、出钩子候选；整条链：导入→反推→出文案→审核→生产→成片',
          ],
          stage: (
            <>
              <MockFlow at="① 导入" note="导入完成 → 批次码一键跳 ② 素材与文案" />
              <div style={{ marginTop: 14 }}>
                <MockBtn kind="primary">跳到这一批的素材列表 →</MockBtn>
              </div>
            </>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}

/* ───────────────────────── ② 素材与文案 ───────────────────────── */

export function CopyGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="反推与出文案怎么用 · 50 秒动画版"
      tagline="勾选素材 → 反推文案 → 出钩子候选 → 交 ③ 审核，全程后台跑、任务条会报"
      footnote="图片不反推文案——图片只当投产用的角色卡"
      steps={[
        {
          title: '第 1 步 · 先勾选要加工的素材',
          sub: '视频才反推；混进图片会被白话提醒',
          tips: [
            '没勾就点按钮 → 「先勾选要反推文案的素材」',
            '全是图片 → 「选中的 N 条都是图片：图片只当投产用的角色卡，不反推文案（提交了也是白扣一次钱）」',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockTag color="blue">✓ 已勾</MockTag>AS-142C3C00 钓鱼踩出巨型金矿</div>
              <MockLines widths={['90%', '70%']} />
              <div style={{ marginTop: 6 }}><MockTag color="default">图片 · 不勾它反推</MockTag>角色卡三视图</div>
            </MockCard>
          ),
        },
        {
          title: '第 2 步 · 点「反推文案」，剩下交给后台',
          sub: '提交即回任务号，跑完顶部任务条会报',
          tips: [
            '「反推文案已排到后台，跑完顶部任务条会报」——不用守着页面',
            '反推按计时上限扣费、后台记账，台面上不弹钱确认单（11-13 口径）',
          ],
          stage: (
            <>
              <MockSteps items={['勾选', '点反推文案', '后台跑', '任务条报']} at={2} />
              <div style={{ marginTop: 12 }}><MockTag color="blue">反推文案已排到后台，跑完顶部任务条会报</MockTag></div>
            </>
          ),
        },
        {
          title: '第 3 步 · 稿子回来，点「出钩子文案」',
          sub: '反推详规就位后，按原型批量出候选',
          tips: [
            '按钮就叫「出钩子文案（N）」——N 是勾选的视频数',
            '单条约 95 秒、提交即回任务号；一批多条也是后台排队，不占你屏幕',
          ],
          stage: (
            <>
              <MockCard dim>
                <MockChip>反推详规已回</MockChip>
                <MockLines widths={['92%', '64%']} />
              </MockCard>
              <div style={{ marginTop: 10, textAlign: 'center' }}>
                <MockBtn kind="primary">出钩子文案（3）</MockBtn>
              </div>
            </>
          ),
        },
        {
          title: '第 4 步 · 候选出来，去 ③ 让人定夺',
          sub: '一条素材出多条候选；谁卡在哪一步看阶段标签',
          tips: [
            '五个阶段一排摆出来：一线问的是「谁卡在哪一步」',
            '出完文案阶段转「等审核」——切 ③ 文案审核接着走',
          ],
          stage: (
            <>
              <MockFlow at="② 素材与文案" note="候选就绪 → ③ 文案审核（防橡皮章：默认只看推荐条）" />
              <div style={{ marginTop: 12 }}>
                <MockTag color="orange">等审核</MockTag><MockTag color="green">推荐</MockTag><MockTag color="default">候选 #1~#3</MockTag>
              </div>
            </>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}

/* ───────────────────────── ③ 文案审核 ───────────────────────── */

export function ReviewGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="审核怎么用 · 60 秒动画版"
      tagline="读文案 → 对判定标签 → 过 / 改后过 / 驳；拿不准还能先试产看片（另有专属动画）"
      footnote="写文案的人不能审自己写的文案（管理员除外）——三角色纪律"
      steps={[
        {
          title: '第 1 步 · 默认「只看推荐条」，别关掉',
          sub: '一条素材多条候选，通常只有一条能钩人',
          tips: [
            '这是防橡皮章设计：先把最像的那条摆到你眼前',
            '范围四个互斥筛选：只看推荐条／命中违禁词／和原视频对不上／等——叠加用',
          ],
          stage: (
            <>
              <MockTag color="green">✓ 只看推荐条（默认开）</MockTag>
              <MockCard focus>
                <div style={{ marginBottom: 6 }}><MockChip>候选 #1</MockChip>　<MockTag color="orange">推荐</MockTag><MockTag color="default">等审核</MockTag></div>
                他在河里踩到的哪是金块，分明是整条金矿，扔掉鱼竿运回黄金
                <MockLines widths={['88%']} />
              </MockCard>
            </>
          ),
        },
        {
          title: '第 2 步 · 读判定标签，必要时核原片',
          sub: '实体未命中／问句式／数字时间锚点／原型 X——黄字是提醒你看的',
          tips: [
            '「和原视频对不上」＝预警（标红但不卡你过审）——过审成功也会弹黄字',
            '右侧「核验原片/脚本」点开就是原片播放＋反推脚本全文，对得上号再落锤',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}>41 字 判读：<span style={{ color: '#d48806' }}>实体未命中：这笔财富开遍分公司</span></div>
              <MockTag color="default">问句式</MockTag><MockTag color="blue">数字时间锚点</MockTag><MockTag color="violet">原型 C</MockTag>
              <div style={{ marginTop: 8 }}>
                <MockBtn>核验原片/脚本</MockBtn>　<MockBtn>网页版提示词·复制</MockBtn>
              </div>
            </MockCard>
          ),
        },
        {
          title: '第 3 步 · 三键定夺：过 / 改后过 / 驳',
          sub: '过＝照原文过审；改后过＝顺手改几个字再过；驳＝打回重写',
          tips: [
            '改后过是给「就差一句」的候选留的活路——不用整条重出',
            '驳掉的文案回采集人手里；撤销过审会连带作废这条**还没投出去**的生产单，所以单独走一次确认',
          ],
          stage: (
            <MockCard focus>
              <MockLines widths={['92%', '80%']} />
              <div style={{ marginTop: 10, textAlign: 'right' }}>
                <MockBtn kind="primary">✓ 过</MockBtn>　
                <MockBtn>✎ 改后过</MockBtn>　
                <MockBtn kind="danger">✗ 驳</MockBtn>
              </div>
            </MockCard>
          ),
        },
        {
          title: '第 4 步 · 拿不准？点「试产」看片再定',
          sub: '紫色「试产」＝改提示词投豆包出一条验证片，看完再定稿/废片',
          tips: [
            '不打回采集人、不用先过审——试产是给审核员自己的验片工具',
            '完整六步另有专属动画：工具条「试产怎么用」',
          ],
          stage: (
            <MockCard>
              <MockLines widths={['86%']} />
              <div style={{ marginTop: 10, textAlign: 'right' }}>
                <MockBtn kind="violet">试产</MockBtn>
                <MockCallout pos="top">先看片再盖章，不猜</MockCallout>
              </div>
            </MockCard>
          ),
        },
        {
          title: '第 5 步 · 过审完成，接 ④ 生产',
          sub: '审完停在当前页继续下一条；要投产就切 ④',
          tips: [
            '「过审」只是质检记录盖章——投产归属在操作人（生产单/成片墙「投：X」）',
            '下一步：④ 生产与投板「生成生产单」（审核台里也有同名入口，同一个弹窗）',
          ],
          stage: (
            <>
              <MockFlow at="③ 文案审核" note="已过审 → ④ 生产与投板 生成生产单" />
              <div style={{ marginTop: 12 }}><MockTag color="green">已过审</MockTag><MockBtn kind="primary">生成生产单 →</MockBtn></div>
            </>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}

/* ───────────────────────── ④ 生产与投板 ───────────────────────── */

export function ProduceGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="生产与投板怎么用 · 60 秒动画版"
      tagline="生成生产单（建单不花钱）→ 人工确认投去出片 → 机器回收 → 成片进 ⑤"
      footnote="四档状态话术说真话——「还没投」就是只建了单、不占号也不出片"
      steps={[
        {
          title: '第 1 步 · 「从过审文案开单」开窗',
          sub: '勾已过审文案、定条数 N、可选换皮参数',
          tips: [
            '「列出全部已过审的文案，勾选后生成生产单（一条文案派生 N 条差异化提示词）」',
            'N 不是把同一条重复投 N 次——差异记在 variant_basis，产物才不会近似到白烧额度',
          ],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 8 }}><b>从过审文案开单（3 待产）</b>　已过审文案 ☑ ×3　条数 N＝3</div>
              <MockLines widths={['90%', '72%']} />
              <div style={{ marginTop: 10, textAlign: 'right' }}><MockBtn kind="primary">提交（建单不花钱）</MockBtn></div>
            </MockPanel>
          ),
        },
        {
          title: '第 2 步 · 提交窗自关，先看清状态',
          sub: '新单是「还没投」——建单不占号也不出片',
          tips: [
            '「只建了单、还没投板：不占号也不出片，点『投去出片』才开始」',
            '这一步反悔零成本：单没投，号没烧——想改就作废重建',
          ],
          stage: (
            <MockCard>
              <MockChip>order_ready</MockChip>　<MockTag color="orange">还没投</MockTag>
              <div style={{ marginTop: 6, color: '#888', fontSize: 12 }}>
                只建了单、还没投板：不占号也不出片，点「投去出片」才开始
              </div>
            </MockCard>
          ),
        },
        {
          title: '第 3 步 · 「投去 AI 出片」开抽屉：勾确认才点得动',
          sub: '「可自动投板，但逐批人工确认」——按钮不勾就是灰的',
          tips: [
            '「投去 AI 出片（N）」→ 一次最多 20 张；点「确认投去出片」那一下就是人工确认，投完窗口当场缩掉，进度看顶部横幅',
            '没配板子凭据时后端当场白话拒绝——老路「导出任务文件（手工投）」没断',
          ],
          stage: (
            <MockPanel>
              <MockSteps items={['勾单', '投去 AI 出片', '勾人工确认', '确认投去出片']} at={2} />
              <div style={{ marginTop: 12 }}>
                <MockTag color="green">✓ 逐批人工确认</MockTag>
                <MockBtn kind="primary">确认投去出片</MockBtn>
              </div>
              <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>只回收（已有 tid）＝不花钱的收片动作</div>
            </MockPanel>
          ),
        },
        {
          title: '第 4 步 · 等出片：机器建任务、自动回收',
          sub: '投出去后不用守着——任务条报进度，成片自动回本行「成片」列',
          tips: [
            '人工在企微后台投的，回来用「补记手工投板结果」把账记上（这是记账不是又投一次）',
            '「记的是出片成功，但库里一段片子都没收到」＝多半人工回写或回收没落库——看本行「提醒」',
          ],
          stage: (
            <MockCard>
              <MockTag color="blue">机器去企微后台建任务 → 等出片 → 成片自动回到每张单的「成片」列</MockTag>
              <MockLines widths={['82%']} />
              <div style={{ marginTop: 8 }}><MockBtn>补记手工投板结果</MockBtn>　<MockBtn>只回收（已有 tid）</MockBtn></div>
            </MockCard>
          ),
        },
        {
          title: '第 5 步 · 片子回来，去 ⑤ 成片墙挑',
          sub: '「片子已回收 N 段：在『成片墙』和本行『成片』列都能看」',
          tips: [
            '挑片子去 ⑤ 的墙——缩略图摆开、点开就播、勾选下载',
            '要交付下游就切「交付包」视图整包导出',
          ],
          stage: (
            <>
              <MockFlow at="④ 生产与投板" note="已回收 → ⑤ 成片墙 挑片/交付" />
              <div style={{ marginTop: 12 }}><MockTag color="green">已产 3 条</MockTag><MockBtn kind="primary">去成片墙看这几张 →</MockBtn></div>
            </>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}

/* ───────────────────────── ⑤ 成片墙 ───────────────────────── */

export function OutputGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="成片墙怎么用 · 40 秒动画版"
      tagline="一面墙摆开回收的片子：点开就播、勾选下载、整包成交付包"
      footnote="默认全部批次、最新在上——挑片子就在一组里挑，不用去生产单行里翻"
      steps={[
        {
          title: '第 1 步 · 墙上一眼扫片',
          sub: '缩略图按素材成组摆开；点一下就播',
          tips: [
            '两级视图：先选组（素材/批次），组内摆片——勾选集收起即清空，不跨组串账',
            '「图打不开」＝直链时效问题（约 1 小时）——关掉重开即可续期，不是片子丢了',
          ],
          stage: (
            <MockCard>
              <MockChip>AS-142C3C00 · 已产 3 段</MockChip>
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                {['▶ 10.1s', '▶ 10.1s', '▶ 10.1s'].map((t, i) => (
                  <div key={i} style={{ flex: 1, height: 74, background: '#1f1f1f', color: '#fff', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12 }}>{t}</div>
                ))}
              </div>
            </MockCard>
          ),
        },
        {
          title: '第 2 步 · 勾选 → 下载',
          sub: '「下载勾选的 N 条」，浏览器右上角看进度',
          tips: [
            '串行一条条落（并行会被浏览器拦一部分），每条走 /download 口落账——谁下过哪条有据可查',
            '「已发起 N 条下载，浏览器右上角下载列表里看进度」',
          ],
          stage: (
            <>
              <MockSteps items={['勾选', '点下载', '落账', '浏览器进度']} at={1} />
              <div style={{ marginTop: 12 }}><MockBtn kind="primary">下载勾选的 2 条</MockBtn>　<MockTag color="default">已下载</MockTag></div>
            </>
          ),
        },
        {
          title: '第 3 步 · 交付视图＋篮子打包：整包给下游',
          sub: '切「交付包」视图，打包 zip 带 manifest 清单',
          tips: [
            '「交付包」视图摆整批成果；勾选进跨组篮子后点「打包下载（N 条）」——后端 zip＋manifest 一次拿走',
            '包里的账（哪条单哪段片）在清单里，出问题能倒查',
          ],
          stage: (
            <MockCard focus>
              <MockTag color="blue">成片</MockTag>｜<MockTag color="violet">交付包</MockTag>
              <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>zip ＝ 勾选成片 ＋ manifest 清单</div>
              <div style={{ marginTop: 8 }}><MockBtn kind="primary">打包下载（5 条）</MockBtn></div>
            </MockCard>
          ),
        },
        {
          title: '第 4 步 · 找不到片？回 ④ 看提醒',
          sub: '墙上一片都没有，多半是回收没落库不是没出片',
          tips: [
            '「记的是出片成功，但库里一段片子都没收到——多半是人工回写或回收没落库，成因看本行『提醒』」',
            '回 ④ 用「只回收」再收一轮（不花钱）；确认丢了才走补记/重投',
          ],
          stage: (
            <>
              <MockFlow at="⑤ 成片墙" note="缺片 → 回 ④ 生产与投板：先看提醒，再『只回收』" />
              <div style={{ marginTop: 12 }}><MockTag color="red">success 但零回收</MockTag><MockBtn>回 ④ 看提醒</MockBtn></div>
            </>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}

/* ───────────────── 入口小按钮（各面板工具条共用一颗） ───────────────── */

export function GuideEntry({ label, onOpen }: { label: string; onOpen: () => void }) {
  return (
    <span
      onClick={onOpen}
      style={{ cursor: 'pointer', fontSize: 12, color: '#722ed1', marginLeft: 6, whiteSpace: 'nowrap' }}
    >
      ❓ {label}
    </span>
  );
}

/** 面板内一行式用法：const [gOpen,setGOpen]=useState(false) → <GuideEntry/> + <ImportGuide open onClose/> */
export const useGuideOpen = () => useState(false);
