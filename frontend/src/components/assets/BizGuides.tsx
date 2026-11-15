/**
 * 业务区板块「怎么用」内嵌动画（11-14 用户「把所有待办事项都安排下去」批准向素材库外铺）。
 *
 * 第一颗：发布管理 PublishFlowGuide——把本页既有的静态「发布流程指引」①→④ 升级成
 * 会动的分步版；静态版保留当速查手册，动画版管教会。话术逐字抄自：
 *  · PublishManagement.tsx 的指引 Modal 原文（「发布链路 = 成品库『一键发布』创建任务 →
 *    本页『发布任务』确认发布 → 审计可溯源」「窗口内随机选点错峰发布」「心跳检查置为 valid」…）
 *  · 按钮真字面：新建发布任务 / 确认发布 / 立即发布 / 新增配置 / 新增账号 / 新增自定义窗口
 *
 * 11-15 业务区动画推进①（log 021）新增两颗：
 *  · SliceFlowGuide 短剧切片（Projects/ProjectDetail/EpisodeDetail/ClipReview 四页链路）
 *  · BatchSliceGuide 批量切片（BatchSlice 一页三步工作流）
 * 话术同样逐字 grep 抄真机源码；改这些页面的主按钮文案时请连改这里
 * （X44/F72 耦合制度，CDP 断言把关）。
 */
import React, { useState } from 'react';
import StepGuide, {
  MockBtn, MockCallout, MockCard, MockChip, MockLines, MockPanel,
  MockSteps, MockTag, MockTextarea,
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

/**
 * 短剧切片怎么用（11-15 业务区动画推进①）。链路 = 项目 → 上传正片 → 一键切片 → 审核 → 出片下载。
 * 话术逐字抄自：Projects.tsx（「新建项目」「搜索项目名称...」）、ProjectDetail.tsx（「上传正片」卡、
 * 「多视频上传（合并成剧集）」、「批量一键切片（N）」、「开始批量切片」、「无候选片段时自动补一轮
 * AI 选点」、「已为 N 个剧集启动一键切片，完成后可到「成品预览」Tab 查看结果」、「一键下载全部」）、
 * EpisodeDetail.tsx（WORKFLOW_STEPS 六步、工作台入口四颗、「一键切片」Popconfirm 原文与「开始切片」、
 * 「启动选点」、「开始检测」）、ClipReview.tsx（「通过 / 批量通过 (N) / 一键全部通过 (N)」）。
 */
export function SliceFlowGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="短剧切片怎么用 · 60 秒动画版"
      tagline="建项目 → 传正片 → 一键切片 → 审片段 → 拿成品"
      footnote="赶时间就「一键切片」免审核直接出片；要精挑就走「启动选点 → 片段审核 → 切片执行」完整链路"
      steps={[
        {
          title: '第 1 步 · 建项目',
          sub: '一部短剧一个项目，右上角「新建项目」填名称即可',
          tips: [
            '列表页可按「搜索项目名称...」找回老项目；状态分 草稿 / 处理中 / 已完成 / 已归档',
            '点项目名称或「详情」进入项目页，后续全在项目里操作',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 8 }}><MockChip>短剧切片</MockChip>　<MockBtn kind="primary">新建项目</MockBtn></div>
              <MockLines widths={['92%', '78%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue">甜宠短剧 A 组</MockTag>
                <MockTag color="default">草稿</MockTag>
                <MockBtn>详情</MockBtn>　<MockBtn>编辑</MockBtn>
              </div>
            </MockCard>
          ),
          ms: 8000,
        },
        {
          title: '第 2 步 · 上传正片',
          sub: '拖进来就行——每个视频单独作为一个剧集；要连拍合并用「多视频上传」',
          tips: [
            '「点击或拖拽视频到此处上传（可一次拖入多个，每个视频单独作为一个剧集）」',
            '「多视频上传（合并成剧集）」弹窗里勾「合并成一个视频（作为一个正片进入选点/切片处理）」——无损拼接不转码，各视频需编码/分辨率/帧率一致',
            '可开「秒差检测（音画同步校验）」，不同步仅提示标注、不拦截上传',
          ],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 8 }}><b>多视频上传（当前项目下创建剧集）</b></div>
              <MockCallout pos="bottom">单个视频也会作为一个剧集；需要合并请在下方使用「多视频上传」</MockCallout>
              <MockLines widths={['70%']} />
              <div style={{ marginTop: 8, textAlign: 'center', border: '1px dashed #d9d9d9', borderRadius: 8, padding: 14, color: '#999' }}>
                点击或拖拽多个视频到此处
              </div>
              <div style={{ marginTop: 8 }}><MockTag color="green">☑ 合并成一个视频</MockTag><MockTag color="default">秒差检测（音画同步校验）</MockTag></div>
            </MockPanel>
          ),
          ms: 9000,
        },
        {
          title: '第 3 步 · 发起切片',
          sub: '快路：勾选多集点「批量一键切片」；单集进详情页点「一键切片」',
          tips: [
            '项目页勾选剧集 →「批量一键切片（N）」→ 弹窗确认「开始批量切片」——免审核直接出片',
            '「无候选片段时自动补一轮 AI 选点」默认开着：没选过点的剧集会先自动选点再切',
            '单集精修：剧集详情页顶部工作台入口有「一键切片」「片段审核」「区间检测」「切片任务」「成品预览」五颗按钮',
          ],
          stage: (
            <>
              <MockSteps items={['上传视频', 'AI 智能选点', '片段审核', '区间检测', '切片执行', '成品预览']} at={4} />
              <MockCard focus>
                <MockLines widths={['80%']} />
                <div style={{ marginTop: 8, textAlign: 'right' }}>
                  <MockBtn kind="primary">批量一键切片（3）</MockBtn>　<MockBtn kind="danger">一键切片</MockBtn>
                </div>
              </MockCard>
              <MockCallout pos="top">免审核直接出片：候选片段（含待审核）直接切割成成品</MockCallout>
            </>
          ),
          ms: 9000,
        },
        {
          title: '第 4 步 · 想精挑：选点 + 片段审核',
          sub: '「启动选点」出候选，去「片段审核」逐个定夺',
          tips: [
            '「AI 智能选点」工作台：「启动选点」自动分析并推荐精彩片段，可调「选点个数」「入选评分」',
            '「片段审核」页：每个候选可「通过」/「拒绝」，也可「批量通过 (N)」「一键全部通过 (N)」',
            '「区间检测」会自动找片尾/静止/水印区间（「开始检测」或「手动添加」），切片时自动避让',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip color="blue">AI 智能选点</MockChip>　<MockBtn kind="primary">启动选点</MockBtn></div>
              <MockLines widths={['90%', '76%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue">待审核: 12</MockTag>
                <MockTag color="green">已通过: 8</MockTag>
                <MockBtn kind="primary">通过</MockBtn> <MockBtn>批量通过 (5)</MockBtn> <MockBtn>一键全部通过 (12)</MockBtn>
              </div>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 5 步 · 收成品',
          sub: '「成品预览」里点开直接播，整组打包下载',
          tips: [
            '切片完的产出按剧集折叠在「成品预览」Tab；点任意一行展开预览',
            '每组顶部「一键下载全部」整集打包；单条点「下载」',
            '「暂无成品。请先对剧集执行切片（可勾选多个剧集后使用「批量一键切片」），完成后即可在此预览。」',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip color="green">成品预览（24）</MockChip>　<MockBtn>一键下载全部</MockBtn></div>
              <MockLines widths={['88%', '72%', '80%']} />
              <MockCallout pos="bottom">切片任务排队中 / 运行中… 完成后本页自动可见</MockCallout>
            </MockCard>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}

/**
 * 批量切片怎么用（11-15 业务区动画推进①·BatchSlice.tsx 一页三步工作流）。
 * 话术逐字抄自 BatchSlice.tsx：整页 Alert 原文（「系统按剧名查找/创建项目…「AI 选点 → 自动审核
 * → 一键切片 → 删除源视频」…」）、卡标题「① 上传列表（JSON）/ ② 一键切片配置选项 / ③ 执行结果」、
 * JSON 占位符 drama/episodes/path、按钮真字面「创建批次并开始处理」「恢复默认配置」「刷新批次列表」
 * 「重试失败项」「取消批次」「输出列表」、成品 Alert「每个成品支持「预览」播放，以及「编辑」通过
 * 拖动进度条选定时间范围进行简单裁剪（会重新编码生成新片段）。」。
 */
export function BatchSliceGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="批量切片怎么用 · 50 秒动画版"
      tagline="一份 JSON 排几十集，机器按剧名建项目连夜切完"
      footnote="批次跑完若有失败：选中该批次点「重试失败项」，已完成项将跳过"
      steps={[
        {
          title: '第 1 步 · ① 上传列表（JSON）',
          sub: '剧名 + 每集的 NAS 路径，粘文本或拖 .json 文件都行',
          tips: [
            '格式：「drama」（剧名）＋「episodes」（剧集数组，每项要有 path）；title 可选',
            '支持整个数组一次给多部剧：[{ "drama": ... }, ...]',
            '系统按剧名查找/创建项目，不用先去建项目',
          ],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 6 }}><b>① 上传列表（JSON）</b></div>
              <MockTextarea caret>{`{
  "drama": "短剧A",
  "episodes": [
    { "title": "第1集", "path": "/mnt/nas/shortdrama/ep01.mp4" }
  ]
}`}</MockTextarea>
              <MockCallout pos="bottom">点击或拖拽 JSON 文件到此处</MockCallout>
            </MockPanel>
          ),
          ms: 9000,
        },
        {
          title: '第 2 步 · ② 一键切片配置选项',
          sub: '预设一键套用，或手工调 AI 选点 / 字幕 / 打码 / 水印 / 去重档位',
          tips: [
            '「选择配置」下拉与剧集详情页「一键切片配置」共用一套预设，选中后自动套用竖屏转横屏/字幕/打码/水印/去重档位等全部参数',
            '「启用 AI 选点」管候选数、最低评分、最短/最长时长；「启用区间检测」切片前自动检测片尾/静止/水印区间',
            '「画面去重」按档位降低平台查重风险；「输出档位」高规格素材可降档提速',
          ],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>选择配置：</MockChip>　<MockTag color="default">默认</MockTag><MockTag color="purple">标准档</MockTag></div>
              <MockLines widths={['86%', '70%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue">启用 AI 选点 ✓</MockTag>
                <MockTag color="blue">切片前自动检测</MockTag>
                <MockTag color="orange">去重档位</MockTag>
                <MockTag color="green">输出档位</MockTag>
              </div>
              <div style={{ marginTop: 10, textAlign: 'right' }}>
                <MockBtn kind="primary">创建批次并开始处理</MockBtn>　<MockBtn>恢复默认配置</MockBtn>
              </div>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 3 步 · 机器连夜干四件事',
          sub: '按列表顺序逐集走「AI 选点 → 自动审核 → 一键切片 → 删除源视频」',
          tips: [
            '批次行点开即展开明细：每集的阶段（上传源视频/选点中/审核中/检测中/切片中）和进度实时刷新',
            '状态话术：待处理 / 上传中 / 选点中 / 审核中 / 检测中 / 切片中 / 已完成 / 失败 / 已取消',
            '跑不完可以「取消批次」（未完成的剧集将标记为已取消）；部分失败点「重试失败项」',
          ],
          stage: (
            <>
              <MockSteps items={['上传源视频', 'AI 选点', '自动审核', '区间检测', '一键切片', '删除源视频']} at={4} />
              <MockCard focus>
                <MockLines widths={['82%']} />
                <div style={{ marginTop: 8 }}>
                  <MockTag color="blue">切片中</MockTag>
                  <MockTag color="green">已完成</MockTag>
                  <MockBtn>刷新批次列表</MockBtn> <MockBtn>重试失败项</MockBtn> <MockBtn kind="danger">取消批次</MockBtn>
                </div>
              </MockCard>
            </>
          ),
          ms: 9000,
        },
        {
          title: '第 4 步 · 验收成品',
          sub: '「输出列表」汇总所有成品：预览、修剪裁、下载',
          tips: [
            '「每个成品支持「预览」播放，以及「编辑」通过拖动进度条选定时间范围进行简单裁剪（会重新编码生成新片段）。」',
            '裁剪弹窗里可「取当前播放点为起点」「选全部」，点「开始裁剪」出新片段',
            '明细分组双击任意一集可直接跳该剧集成品预览；下载走「下载」链接',
          ],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 6 }}><b>输出列表（共 48 个成品）</b></div>
              <MockLines widths={['88%', '64%']} />
              <div style={{ marginTop: 8, textAlign: 'right' }}>
                <MockBtn>预览</MockBtn>　<MockBtn kind="primary">编辑</MockBtn>　<MockBtn>下载</MockBtn>
              </div>
              <MockCallout pos="bottom">拖动进度条选定时间范围 →「开始裁剪」</MockCallout>
            </MockPanel>
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
