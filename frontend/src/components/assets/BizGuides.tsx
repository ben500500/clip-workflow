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
 * 11-16 补账：这两颗初版漏配 c06a129 立下的动效规矩（每步巡航光标 pulse/blink）——
 * 现全部 9 步补齐，shoot-biz-slice-guides.mjs 每步数无限循环元素>0 实测把关。
 * 11-16 业务区动画推进②新增三颗（frameDir 逐帧图片模式，11-16 用户口径「动画效果太差，
 * 改成一帧一帧的图片」）：
 *  · DedupGuide 去重处理（DedupeProcessing.tsx 双模式工作流）
 *  · VariantMatrixGuide 变体矩阵（VariantMatrix.tsx 看板页）
 *  · ResourceDownloadGuide 资源下载（ResourceDownload.tsx 多 Tab 工作台）
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
       frameDir="/guides/biz-publish"
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
          cursor: [20, 300, 120, 180],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>发布配置</MockChip>　视频号 · Chrome 9222档 · 每日上限 · 间隔</div>
              <MockLines widths={['88%']} />
              <div style={{ marginBottom: 6 }}><MockChip>账号库</MockChip>　新增账号 → 绑定配置 → 小程序链接（可选）</div>
              <MockLines widths={['76%']} />
              <div><MockTag color="green" blink>心跳检查 valid</MockTag><MockTag color="red">expired＝发不出</MockTag></div>
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
          cursor: [20, 300, 380, 160],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 8 }}><b>一键发布</b>　平台：☑视频号 ☑抖音</div>
              <MockLines widths={['84%', '60%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue">发布素材：短标题/配文/标签自动代入</MockTag>
                <MockTag color="green" blink>截图确认后发布：是（推荐）</MockTag>
              </div>
              <div style={{ marginTop: 10, textAlign: 'right' }}><MockBtn kind="primary" pulse>提交（创建任务＋触发 RPA）</MockBtn></div>
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
          cursor: [20, 300, 330, 150],
          stage: (
            <>
              <MockSteps items={['待发布', 'RPA 填表', '待确认', '确认发布', '已发布']} at={2} />
              <MockCard focus>
                <MockLines widths={['80%']} />
                <div style={{ marginTop: 8, textAlign: 'right' }}>
                  <MockBtn>查看截图</MockBtn>　<MockBtn kind="primary" pulse>确认发布</MockBtn>
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
          cursor: [20, 300, 240, 45],
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
       frameDir="/guides/biz-slice"
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
          cursor: [20, 300, 170, 42],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 8 }}><MockChip>短剧切片</MockChip>　<MockBtn kind="primary" pulse>新建项目</MockBtn></div>
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
          cursor: [20, 300, 240, 205],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 8 }}><b>多视频上传（当前项目下创建剧集）</b></div>
              <MockCallout pos="bottom">单个视频也会作为一个剧集；需要合并请在下方使用「多视频上传」</MockCallout>
              <MockLines widths={['70%']} />
              <div style={{ marginTop: 8, textAlign: 'center', border: '1px dashed #d9d9d9', borderRadius: 8, padding: 14, color: '#999' }}>
                点击或拖拽多个视频到此处
              </div>
              <div style={{ marginTop: 8 }}><MockTag color="green" blink>☑ 合并成一个视频</MockTag><MockTag color="default">秒差检测（音画同步校验）</MockTag></div>
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
          cursor: [20, 300, 390, 160],
          stage: (
            <>
              <MockSteps items={['上传视频', 'AI 智能选点', '片段审核', '区间检测', '切片执行', '成品预览']} at={4} />
              <MockCard focus>
                <MockLines widths={['80%']} />
                <div style={{ marginTop: 8, textAlign: 'right' }}>
                  <MockBtn kind="primary" pulse>批量一键切片（3）</MockBtn>　<MockBtn kind="danger">一键切片</MockBtn>
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
          cursor: [20, 300, 215, 40],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip color="blue">AI 智能选点</MockChip>　<MockBtn kind="primary" pulse>启动选点</MockBtn></div>
              <MockLines widths={['90%', '76%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue" blink>待审核: 12</MockTag>
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
          cursor: [20, 300, 255, 42],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip color="green">成品预览（24）</MockChip>　<MockBtn pulse>一键下载全部</MockBtn></div>
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
       frameDir="/guides/biz-batch"
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
          cursor: [20, 300, 230, 130],
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
            '「选择配置」下拉与剧集详情页「一键切片配置」共用，选中后自动套用竖屏转横屏/字幕/打码/水印/去重档位等全部参数',
            '「启用 AI 选点」管候选数、最低评分、最短/最长时长；「启用区间检测」切片前自动检测片尾/静止/水印区间',
            '「画面去重」按档位降低平台查重风险；「输出档位」高规格素材可降档提速',
          ],
          cursor: [20, 300, 395, 175],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>选择配置：</MockChip>　<MockTag color="default">默认</MockTag><MockTag color="purple">标准档</MockTag></div>
              <MockLines widths={['86%', '70%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue" blink>启用 AI 选点 ✓</MockTag>
                <MockTag color="blue">切片前自动检测</MockTag>
                <MockTag color="orange">去重档位</MockTag>
                <MockTag color="green">输出档位</MockTag>
              </div>
              <div style={{ marginTop: 10, textAlign: 'right' }}>
                <MockBtn kind="primary" pulse>创建批次并开始处理</MockBtn>　<MockBtn>恢复默认配置</MockBtn>
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
          cursor: [20, 300, 300, 118],
          stage: (
            <>
              <MockSteps items={['上传源视频', 'AI 选点', '自动审核', '区间检测', '一键切片', '删除源视频']} at={4} />
              <MockCard focus>
                <MockLines widths={['82%']} />
                <div style={{ marginTop: 8 }}>
                  <MockTag color="blue" blink>切片中</MockTag>
                  <MockTag color="green">已完成</MockTag>
                  <MockBtn pulse>刷新批次列表</MockBtn> <MockBtn>重试失败项</MockBtn> <MockBtn kind="danger">取消批次</MockBtn>
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
          cursor: [20, 300, 400, 150],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 6 }}><b>输出列表（共 48 个成品）</b></div>
              <MockLines widths={['88%', '64%']} />
              <div style={{ marginTop: 8, textAlign: 'right' }}>
                <MockBtn>预览</MockBtn>　<MockBtn kind="primary" pulse>编辑</MockBtn>　<MockBtn>下载</MockBtn>
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

/**
 * 去重处理怎么用（11-16 业务区动画推进②·DedupeProcessing.tsx 一页双模式工作流）。
 * 话术逐字抄自 DedupeProcessing.tsx：Card 标题「去重处理（多视频号素材去重）」、顶部按钮
 * 「去重配置」「刷新」「查看变体矩阵」「提交生成」「上传去重」、两个 Tab 名
 * 「从已切片任务选择（SliceOutput 多选）」「批量文件拖入（上传→切片）」、
 * 空态「暂无已切片输出。可拖入文件去重，或先去「批量切片」产出切片。」、
 * Dragger 文案「点击或拖拽视频文件到此处（可多选）」、上传后话术「已创建批量切片批次…
 * 正在去重切片并派生变体，可在「批量切片」或「变体矩阵」查看」、配置弹窗标题
 * 「去重配置（档位 + 变体数量 + 手动手段）」。改本页按钮文案请连改这里（X44/F72）。
 */
export function DedupGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="去重处理怎么用 · 60 秒动画版"
      frameDir="/guides/biz-dedup"
      tagline="选输入源 → 配去重手段＋变体数 → 复用切片链路产出变体"
      footnote="产出直接出现在「变体矩阵」；要精调手段就点「去重配置」开档位＋手动覆盖"
      steps={[
        {
          title: '第 1 步 · 选输入源（两种模式）',
          sub: '从已切片任务多选，或直接拖文件进来去重',
          tips: [
            '「从已切片任务选择（SliceOutput 多选）」Tab：按项目/剧集/文件名筛选，勾选输出行（项目/剧集行不可选）',
            '「批量文件拖入（上传→切片）」Tab：「点击或拖拽视频文件到此处（可多选）」——上传后复用 batch-slice/run 切片链路',
            '顶部「刷新」拉最新已切片输出；空态会提示「暂无已切片输出。可拖入文件去重，或先去「批量切片」产出切片。」',
          ],
          cursor: [20, 300, 200, 160],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 8 }}><MockChip>去重处理（多视频号素材去重）</MockChip>　<MockTag color="default">从已切片任务选择（SliceOutput 多选）</MockTag></div>
              <MockLines widths={['92%', '78%']} />
              <div style={{ marginTop: 8, border: '1px dashed #d9d9d9', borderRadius: 8, padding: 14, color: '#999', textAlign: 'center' }}>
                点击或拖拽视频文件到此处（可多选）
              </div>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 2 步 · 配去重手段＋变体数量',
          sub: '档位一键套用，或手动调画面/水印/噪点等手段',
          tips: [
            '点「去重配置」开弹窗：标题「去重配置（档位 + 变体数量 + 手动手段）」——选去重档位＋变体数量（默认 3）',
            '「每个素材派生 N 套去重变体（默认 3）」；手动手段可开裁剪/翻转/变速/饱和度/伽马/对比度/亮度/噪点/锐化/暗角/滚动条/抖动/水印/闪光/人脸水印',
            '变体数量 > 1 时切片后自动派生 N 个去重变体，进「变体矩阵」',
          ],
          cursor: [20, 300, 240, 130],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>去重配置（档位 + 变体数量 + 手动手段）</MockChip></div>
              <MockLines widths={['86%', '70%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="purple">去重档位</MockTag>
                <MockTag color="blue" blink>变体数量：3</MockTag>
                <MockTag color="green">裁剪 / 翻转 / 变速</MockTag>
                <MockTag color="orange">水印 / 噪点 / 锐化</MockTag>
              </div>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 3 步 · 提交生成（两种入口）',
          sub: '已切片任务点「提交生成」；拖文件点「上传去重」',
          tips: [
            'Tab1 勾选输出后点「提交生成」：对选中 SliceOutput 批量生成变体，提示「已投递 N 个变体生成任务（每个 N 套），请在「变体矩阵」查看产出」',
            'Tab2 填批次名称（留空自动生成「去重处理-MMDD-HHmmss」）后点「上传去重」：复用切片链路，「已创建批量切片批次 …（N 个视频），正在去重切片并派生变体，可在「批量切片」或「变体矩阵」查看」',
            '批次名输入框 placeholder「批次名称（留空自动生成）」',
          ],
          cursor: [20, 300, 380, 150],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>批次名称（留空自动生成）</MockChip></div>
              <MockLines widths={['80%']} />
              <div style={{ marginTop: 10, textAlign: 'right' }}>
                <MockBtn kind="primary" pulse>提交生成</MockBtn>　<MockBtn kind="primary" pulse>上传去重</MockBtn>
              </div>
              <MockCallout pos="bottom">已投递变体生成任务——去「变体矩阵」查看产出</MockCallout>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 4 步 · 看产出（跳变体矩阵）',
          sub: '去重变体在「变体矩阵」按组摆开，可绑定账号分发',
          tips: [
            '顶部「查看变体矩阵」按钮一键跳到 /variant-matrix，变体按组折叠展示',
            '每组有基准＋N 套变体，画面/音频/时域三路指纹互相拉开距离，供不同视频号分别上传',
            '「变体组」列会标「已生成」或「未去重」，一眼看出哪些已产出',
          ],
          cursor: [20, 300, 300, 118],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>变体组</MockChip>　<MockTag color="blue" blink>已生成</MockTag><MockTag>未去重</MockTag></div>
              <MockLines widths={['88%', '72%']} />
              <div style={{ marginTop: 10, textAlign: 'right' }}><MockBtn kind="primary" pulse>查看变体矩阵</MockBtn></div>
            </MockCard>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}

/**
 * 变体矩阵怎么用（11-16 业务区动画推进②·VariantMatrix.tsx 看板页）。
 * 话术逐字抄自 VariantMatrix.tsx：Card 标题「变体矩阵看板（多视频号素材去重）」、顶部
 * 「清理卡住」「撞车阈值」「刷新」、搜索框 placeholder「按基准文件名搜索变体组」、
 * 筛选项「全部 / 有碰撞 / 未绑定账号」、Alert「多视频号素材去重：一套切片派生 N 套结构性
 * 差异变体…变体组默认收起，有碰撞需处理的组自动展开并置顶。」、空态「没有匹配的变体组。
 * 在去重模式下配置「多版本数 > 1」切片后，将在此展示生成的素材变体。」、折叠项
 * 「变体组 XXX」「一键下载全部」「删除整组」、行内按钮「复核」「绑定」「下载」、
 * 绑定弹窗 Alert「一个视频号账号只能绑定一个变体，防止同素材原样发多号被平台判定搬运。」、
 * 阈值弹窗标题「撞车判定阈值（运营可调）」。改本页按钮文案请连改这里（X44/F72）。
 */
export function VariantMatrixGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="变体矩阵怎么用 · 60 秒动画版"
      frameDir="/guides/biz-variant"
      tagline="一套切片派生 N 套变体 → 三路指纹拉开距离 → 绑账号分发"
      footnote="有碰撞的组自动展开置顶——先处理撞车，再绑账号，最后才下载发布"
      steps={[
        {
          title: '第 1 步 · 看变体组',
          sub: '变体按组折叠，有碰撞的组自动展开置顶',
          tips: [
            'Card 标题「变体矩阵看板（多视频号素材去重）」；顶部「刷新」拉最新，「撞车阈值」调判定，「清理卡住」清超时 running',
            '搜索框「按基准文件名搜索变体组」；筛选「全部 / 有碰撞 / 未绑定账号」',
            '折叠项标「变体组 XXX · 基准文件名 · 共 N 变体」；有碰撞组自动展开并置顶，让运营第一眼看到要处理的',
          ],
          cursor: [20, 300, 200, 150],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>变体矩阵看板（多视频号素材去重）</MockChip></div>
              <MockLines widths={['88%', '72%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="default">全部</MockTag>
                <MockTag color="red" blink>有碰撞</MockTag>
                <MockTag color="gold">未绑定账号</MockTag>
              </div>
              <MockCallout pos="bottom">变体组默认收起，有碰撞需处理的组自动展开并置顶</MockCallout>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 2 步 · 处理撞车',
          sub: '「撞车」红标组先复核，再调阈值或清理',
          tips: [
            '行内「复核」按钮：发布前指纹复核，通过可安全发布，未通过给撞车原因',
            '「撞车阈值」按钮开「撞车判定阈值（运营可调）」弹窗：画面 pHash / 音频声纹 / 时域序列 / 综合加权，「距离值越低越相似；低于阈值判定为撞车」',
            '顶部「清理卡住」清掉超时 30 分钟的 running 变体（回写 failed）；有碰撞的红标组优先处理',
          ],
          cursor: [20, 300, 320, 140],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>撞车判定阈值（运营可调）</MockChip></div>
              <MockLines widths={['84%', '68%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="red" blink>撞车</MockTag>
                <MockTag color="green">正常</MockTag>
                <MockBtn pulse>复核</MockBtn>
              </div>
              <MockCallout pos="bottom">距离值越低越相似；低于阈值判定为撞车</MockCallout>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 3 步 · 绑视频号账号',
          sub: '一账号一变体，防止同素材原样发多号',
          tips: [
            '行内「绑定」按钮开弹窗：标题「绑定账号 - 基准 / 变体 N」',
            '弹窗 Alert「一个视频号账号只能绑定一个变体，防止同素材原样发多号被平台判定搬运。」',
            '下拉「选择视频号账号」选平台账号，点「绑定」确认；未绑定的变体在筛选「未绑定账号」下集中处理',
          ],
          cursor: [20, 300, 260, 170],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>绑定账号 - 变体 2</MockChip></div>
              <MockLines widths={['80%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="warning">一个视频号账号只能绑定一个变体</MockTag>
              </div>
              <div style={{ marginTop: 10, textAlign: 'right' }}><MockBtn kind="primary" pulse>绑定</MockBtn></div>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 4 步 · 下载与整组操作',
          sub: '单条下载、整组一键下载，或删除整组清理',
          tips: [
            '行内「下载」按钮：下载单个变体视频（presigned URL 强制下载）；整组「一键下载全部」逐个顺序触发',
            '整组「删除整组」：删组内全部变体（DB + MinIO），基准切片输出保留，不可恢复',
            '空态「没有匹配的变体组。在去重模式下配置「多版本数 > 1」切片后，将在此展示生成的素材变体。」',
          ],
          cursor: [20, 300, 340, 150],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>变体组 3a2b1c4d</MockChip>　<MockTag color="blue">共 4 变体</MockTag></div>
              <MockLines widths={['86%', '70%']} />
              <div style={{ marginTop: 10, textAlign: 'right' }}>
                <MockBtn pulse>一键下载全部</MockBtn>　<MockBtn kind="danger">删除整组</MockBtn>
              </div>
            </MockCard>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}

/**
 * 资源下载怎么用（11-16 业务区动画推进②·ResourceDownload.tsx 多 Tab 工作台）。
 * 话术逐字抄自 ResourceDownload.tsx：链接导入 Tab「导入视频素材（URL 直链）」「直接导入」
 * Alert、按钮「单链接导入」「批量导入」「提交导入」「批量提交」、默认分辨率「720p」、
 * 下载任务 Tab「下载任务」、行内「查看」「导入切片」「入切片」「反推提示词」「重试」、
 * 反推提示词 Tab「视频反推提示词（AI 提示词提取）」「开始反推」「一键复制」、
 * 上传区「没有链接？点此或拖拽本地视频到这里上传后反推」、解析服务商 Tab
 * 「当前使用的解析 API 服务」。改本页按钮文案请连改这里（X44/F72）。
 */
export function ResourceDownloadGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StepGuide
      open={open} onClose={onClose}
      headline="资源下载怎么用 · 60 秒动画版"
      frameDir="/guides/biz-resource"
      tagline="贴链接导入 → 下载入库 → 反推提示词 → 一键入切片"
      footnote="支持 30+ 平台分享链接与视频直链；下载完可直接入切片或反推提示词"
      steps={[
        {
          title: '第 1 步 · 贴链接导入',
          sub: '单链接或批量，粘贴视频分享链接即可',
          tips: [
            '「导入视频素材（URL 直链）」Tab：Alert「直接导入」——粘贴链接即创建下载任务，无需绑定授权材料',
            '按钮「单链接导入」填单个链接点「提交导入」；「批量导入」每行一条点「批量提交」，最多 100 条',
            '「默认分辨率」选 720p/1080p，下载入库时按所选分辨率统一缩放（默认 720p）',
          ],
          cursor: [20, 300, 240, 170],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 8 }}><b>导入视频素材（URL 直链）</b></div>
              <MockCallout pos="top">直接导入：粘贴视频分享链接即可创建下载任务</MockCallout>
              <MockLines widths={['84%', '60%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="default">单链接导入</MockTag>
                <MockTag color="blue" blink>批量导入</MockTag>
                <MockTag color="green">默认分辨率 720p</MockTag>
              </div>
              <div style={{ marginTop: 10, textAlign: 'right' }}><MockBtn kind="primary" pulse>提交导入</MockBtn></div>
            </MockPanel>
          ),
          ms: 9000,
        },
        {
          title: '第 2 步 · 下载入库（看任务进度）',
          sub: '任务在「下载任务」Tab 实时刷新，状态＋进度条',
          tips: [
            '「下载任务」Tab：状态流转 排队中 → 解析中 → 下载中 → 入库中 → 已完成，非终态任务有进度条',
            '「状态过滤」下拉按状态筛；「刷新」拉最新；任务经 WebSocket 实时推送进度，不用手动刷',
            '「当前使用的解析 API 服务」Tab 看主力解析服务（智令 doc/107，约 0.01 元/次）与余量',
          ],
          cursor: [20, 300, 300, 150],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>下载任务</MockChip>　<MockTag color="processing" blink>下载中 60%</MockTag></div>
              <MockLines widths={['92%', '78%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="default">排队中</MockTag>
                <MockTag color="processing">解析中</MockTag>
                <MockTag color="success">已完成</MockTag>
              </div>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 3 步 · 反推提示词（可选）',
          sub: '用视频反推结构化提示词，一键复制',
          tips: [
            '「视频反推提示词（AI 提示词提取）」Tab：粘贴链接或上传本地视频，选计时上限（60/180/300/600 秒）',
            '点「开始反推」提交智令 doc/120；生成中每 4s 自动刷新，完成后「一键复制」markdown 提示词',
            '没有链接就拖本地视频：「没有链接？点此或拖拽本地视频到这里上传后反推」，单文件 ≤ 500MB，6 小时后自动删除',
          ],
          cursor: [20, 300, 320, 130],
          stage: (
            <MockPanel>
              <div style={{ marginBottom: 8 }}><b>视频反推提示词（AI 提示词提取）</b></div>
              <MockLines widths={['86%', '70%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="default">计时上限 180 秒（默认）</MockTag>
                <MockTag color="processing" blink>生成中…</MockTag>
              </div>
              <div style={{ marginTop: 10, textAlign: 'right' }}>
                <MockBtn kind="primary" pulse>开始反推</MockBtn>　<MockBtn>一键复制</MockBtn>
              </div>
            </MockPanel>
          ),
          ms: 9000,
        },
        {
          title: '第 4 步 · 一键入切片',
          sub: '下载完的素材直接投进切片队列',
          tips: [
            '下载任务行「入切片」按钮：一键把该素材投入切片队列（fast 模式），提示「已投入切片队列」',
            '或点「导入切片」开弹窗「一键导入切片」：选「新建切片项目」填名称，或「加入已有切片项目」选项目',
            '「确认导入」后页面自动跳转到对应的切片项目，无需再手动找项目',
          ],
          cursor: [20, 300, 340, 150],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>一键导入切片</MockChip></div>
              <MockLines widths={['80%']} />
              <div style={{ marginTop: 8 }}>
                <MockTag color="blue">新建切片项目</MockTag>
                <MockTag color="default">加入已有切片项目</MockTag>
              </div>
              <div style={{ marginTop: 10, textAlign: 'right' }}><MockBtn kind="primary" pulse>确认导入</MockBtn></div>
            </MockCard>
          ),
          ms: 9000,
        },
        {
          title: '第 5 步 · 失败重试',
          sub: '失败或超时卡死的任务，点「重试」重新投递',
          tips: [
            '失败任务行「重试」按钮：重新投递到下载队列，提示「任务已重新投递到下载队列」',
            '超时卡死（超 1 小时无更新）的非终态任务也会显示「重试」入口，点一下重新投递',
            '反推提示词失败同理：智令偶发空返回等瞬时故障，点「重试」用原参数重新提交',
          ],
          cursor: [20, 300, 360, 140],
          stage: (
            <MockCard>
              <div style={{ marginBottom: 6 }}><MockChip>下载任务</MockChip>　<MockTag color="error" blink>失败</MockTag></div>
              <MockLines widths={['84%', '68%']} />
              <div style={{ marginTop: 10, textAlign: 'right' }}><MockBtn kind="danger" pulse>重试</MockBtn></div>
              <MockCallout pos="bottom">重新投递到下载队列——超时卡死任务也可点重试</MockCallout>
            </MockCard>
          ),
          ms: 8000,
        },
      ]}
    />
  );
}
