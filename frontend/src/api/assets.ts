import client from './client';

/**
 * 素材库（Asset Library）API 客户端。
 *
 * 唯一真相来源是 `backend/app/api/assets.py`（21 个路由，router 挂在 `/api` 前缀下，
 * 而 client.ts 的 baseURL 已是 `/api`，所以本文件里的路径一律不带 /api）。
 * 响应是后端手写 dict 返回，字段以函数末尾的 `return {...}` 为准。
 *
 * 链路（每一环可单独重试，且每一环都是真金白银）：
 *   导入 → 反推提示词（智令 doc/120，按**计时上限**扣费）→ 钩子文案（AutoClip）
 *   → 审核 → 生产单（N 条差异化提示词）→ 导出任务文件投企微后台任务板 → 人工补记投板结果
 */

// ──────────────────────────────────────────────
// 枚举字面量（取值以 models/asset.py + asset_service.py 为准）
// ──────────────────────────────────────────────

/**
 * 阶段态：素材 5 段流水线（stage_import/stage_prompt/stage_summary/stage_produce/stage_compose）
 * 共用同一套取值（后端 STAGE_STATES，5 个值，skipped 是真实筛选值不是异常态）。
 */
export type AssetStage = 'pending' | 'running' | 'success' | 'failed' | 'skipped';

/** 素材派生态（由 5 个阶段重算，见 asset_service.derive_status；archived 属 P1，暂无写入方） */
export type AssetStatus =
  | 'draft'
  | 'importing'
  | 'analyzing'
  | 'waiting_prompt'
  | 'summarizing'
  | 'awaiting_review'
  | 'ready_to_produce'
  | 'producing'
  | 'composing'
  | 'ready'
  | 'failed'
  | 'archived'
  /**
   * 11-05 批 G：图片素材的**终点态**。图只当生产输入（角色卡），四环（反推/出文案/
   * 生产/拼接）对它全是 skipped，派生链走不到任何既有态——所以后端单立这一支。
   * 少了它，每张角色卡都会显示「等读视频」，看着像一堆卡着没人管的活，
   * 实际正确动作恰恰是**别提交**（提交会白扣一次反推钱）。
   */
  | 'image_ready';

/**
 * 生产单状态（PRODUCTION_STATES）。
 * order_ready = 建单落库的唯一初态；queued/running/success/failed 只能由人经
 * `POST /assets/productions/status` 回写（P0 无自动投递）；
 * superseded/cancelled/skipped 是**系统态**，回写口拒绝外部写入。
 */
export type ProductionState =
  | 'order_ready'
  | 'queued'
  | 'running'
  | 'awaiting_rewrite'
  | 'success'
  | 'failed'
  | 'cancelled'
  | 'skipped'
  | 'superseded';

/** 钩子文案审核态（REVIEW_STATES） */
export type AuditStatus = 'pending' | 'approved' | 'rejected' | 'need_rewrite' | 'passed_edited';

/** 审核动作（review 接口 action 入参；驳回/需改写必填 reason，pass_edited 必填 new_text） */
export type AssetReviewAction = 'approve' | 'reject' | 'need_rewrite' | 'pass_edited';

/** 来源形态：link=分享链接（走 doc/107 解析）/ file=视频文件（落自有桶） */
export type AssetSourceKind = 'link' | 'file';

/**
 * 媒体类型（asset_items.media_kind，批 G）。
 * 业务分流只看这一列，**不许拿扩展名当口径**（后端把这条口径散到六处就是当初的坑）。
 */
export type AssetMediaKind = 'video' | 'image';

/**
 * 图片画幅判读（后端 `_serialize_item.aspect`，只对 media_kind=image 回，视频回 null）。
 * 口径来自**实测**：成片画幅由角色卡宽高比决定，提示词写 9:16 压不住一张横版卡。
 * 判据留在后端一处——前端再拼一张比例表，日后口径一改就是两边各说一套。
 */
export interface AssetImageAspect {
  width: number | null;
  height: number | null;
  /** '9:16' | '16:9' | '1:1' | '3:4' | '4:3'，量不到尺寸 = null */
  ratio: string | null;
  /** 量不到尺寸时也是 null（老数据或探失败，界面要显示「量不到」而不是猜一个） */
  orientation: 'portrait' | 'landscape' | 'square' | null;
}

/** 平台标签字面量（asset_service._PLATFORM_BY_HOST 的归一化结果，中文/品牌原名） */
export type AssetPlatformLabel =
  | '抖音'
  | '快手'
  | '小红书'
  | '微信视频号'
  | 'B站'
  | '微博'
  | '西瓜视频'
  | '头条'
  | '好看视频'
  | '腾讯视频'
  | '即梦'
  | '豆包'
  | 'YouTube';

/** 平台标签：未命中任何 host 时后端回 null；列宽 String(40) 且别处也可能写入新值，故保留 string 兜底 */
export type AssetPlatform = AssetPlatformLabel | (string & {});

/** 成本熔断闸门档位（svc.budget_gate 的 level） */
export type AssetBudgetGate = 'ok' | 'need_approval' | 'blocked';

/** 生产通道（素材库默认 wework_aivideo = 企微后台「创建 AI 视频」任务板） */
export type AssetProductionChannel = 'wework_aivideo' | 'doubao_rpa' | 'seedance_api';

/** 产物类型（asset_outputs.kind） */
export type AssetOutputKind = 'doubao_raw' | 'composed' | 'package' | 'copy';

/** 产物验收结论（null = 未验；不合格不得入交付包） */
export type AssetQcStatus = 'passed' | 'warn' | 'failed';

/** 钩子文案候选风格（HOOK_STYLES） */
export type AssetHookStyle = 'question' | 'statement' | 'dialogue';

/**
 * 反推任务态。processing/success/failed 来自 wechat_download，
 * `persist_failed` 是素材库特有的**危险态**：已提交并扣费但状态没落库，重试会重复扣费。
 */
export type AssetPromptTaskStatus = 'processing' | 'success' | 'failed' | 'persist_failed';

/** 原文件下载口返回形态：stored=自有桶 presigned / external=只有分享链接；
 * cached=11-06 播放直链修复：source-preview 回的是上次取的时效直链（缓存期内免费回放） */
export type AssetSourceDownloadMode = 'stored' | 'external' | 'cached';

/** 导出形态：json=只 items[]；txt=追加 export_text；payload=追加可直接 POST 的七键 */
export type AssetExportFormat = 'json' | 'txt' | 'payload';

// ──────────────────────────────────────────────
// 实体（四个 serializer：_serialize_batch / _serialize_item / _serialize_summary / _serialize_production）
// ──────────────────────────────────────────────

/** 导入批次（_serialize_batch）：批量动作的成本与熔断落点 */
export interface AssetBatch {
  id: string;
  /** 可读唯一 ID：AB-<8位大写HEX> */
  code: string;
  name: string | null;
  source_kind: AssetSourceKind;
  item_count: number;
  /** 本批反推计时上限档位（秒），NULL=未定档 */
  prompt_max_duration: number | null;
  /** 预估计费（元）：按**计时上限**算，不是按视频实际时长 */
  cost_estimate: number | null;
  /** 实扣（元）——实为「按档位推算的额度」，列名保留只为不丢历史，对账以它为准绳而非精确值 */
  cost_actual: number | null;
  /** 本批预算上限（元），null=用全局默认 */
  budget_cap: number | null;
  budget_gate: AssetBudgetGate | null;
  budget_note: string | null;
  created_at: string;
}

/**
 * 素材主表（_serialize_item）：一行 = 一条素材，列表页的主粒度。
 * 末尾 4 个计数字段只在列表（list_assets）与详情（getAsset）里回；
 * 单条 prompt-refresh 口用同一个 serializer 但不带 agg，所以是可选。
 */
export interface AssetItem {
  id: string;
  /** 可读唯一 ID：AS-<8位大写HEX> */
  code: string;
  batch_id: string | null;
  source_kind: AssetSourceKind;
  /**
   * 批 G：video=走四环流水线的素材；image=**只当角色卡**的图。
   * 列表/详情按这一列分流（图片显示缩略图、不显示播放器），并据此**隐藏**
   * 「反推 / 出文案 / 拼接」入口——对图提交任何一个都是白花钱或 400。
   */
  media_kind: AssetMediaKind;
  /** 批 G：图片才有（视频恒 null）；挑卡列表直接显示「这张 9:16 出竖屏」就是它 */
  aspect?: AssetImageAspect | null;
  source_url: string | null;
  platform: AssetPlatform | null;
  file_name: string | null;
  file_key: string | null;
  bucket: string | null;
  file_size: number | null;
  /**
   * 批 J：链接素材的原片下载三态。null=没有要下的（文件素材/图片/没链接）；
   * running=后台正在下；success=已进自有桶（此时 file_key 一定有值）；
   * failed=没下成（可再点「下载原片」重试）。**不入五段阶段**——下载是搭车动作，
   * 失败只影响「离线看原片/内联预览」，不拦反推文案。
   */
  download_status: string | null;
  project_id: string | null;
  episode_id: string | null;
  /** 反推提示词任务 id（wechat_dl_prompt_tasks，跨域只存 id） */
  prompt_task_id: string | null;
  title: string | null;
  cover_image_key: string | null;
  /**
   * 真实时长（秒）。⚠️ 探不到时长后端回 **null 而不是 0**（"没探到"和"0 秒"是两件事），
   * 前端必须按「未知」渲染占位，写 0 会显示 0:00 让人以为素材是空的。
   */
  duration: number | null;
  resolution: string | null;
  /** 本条实际使用的反推档位（秒），null=未反推 */
  prompt_max_duration: number | null;
  /** 导入阶段态（5 段之一：登记地址 / 落盘落桶是否完成） */
  stage_import: AssetStage;
  /** 反推提示词阶段态（花钱的一步） */
  stage_prompt: AssetStage;
  /** 钩子文案阶段态 */
  stage_summary: AssetStage;
  /** 生产单阶段态（由投递状态回写口收敛） */
  stage_produce: AssetStage;
  /** 合成阶段态（11-04 起由 POST /assets/concat 写入：拼成功＝success） */
  stage_compose: AssetStage;
  status: AssetStatus;
  has_approved_copy: boolean;
  /** 反推实扣（元，按档位推算的额度） */
  cost_prompt: number;
  /** 生产消耗（额度类消耗记 0，成本走号池） */
  cost_produce: number;
  /** 回源解析实扣（元，doc/107 每次 0.01；走免费兜底渠道记 0） */
  cost_parse: number;
  note: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /**
   * 钩子原型分类（11-04 拍板①）。null＝未分类——**不设为必填**，不填也能走完全链。
   * `category_name` 只有列表（list_assets）与详情（getAsset）带，单条口为 null。
   */
  category_id?: string | null;
  category_name?: string | null;
  /** 候选文案条数（列表聚合，非列表口缺省） */
  summary_count?: number;
  /** 已过审条数 */
  approved_count?: number;
  /** 待审核条数 */
  pending_review_count?: number;
  /** 生产单条数 */
  production_count?: number;
}

/** 钩子文案候选（_serialize_summary）；带 asset_* 时是列表口 join 出来的素材概要 */
export interface AssetSummary {
  id: string;
  asset_id: string;
  /** 候选序号（同素材内唯一，1..N） */
  seq: number;
  text: string;
  style_tag: AssetHookStyle | null;
  /** 命中的爆款公式（防同质化用） */
  formula_tag: string | null;
  /** 字数：含标点不含空格 */
  word_count: number | null;
  /** 模型标注的推荐条：审核页默认只批量放推荐条，防橡皮章式全过 */
  is_recommended: boolean;
  /** 一致性校验（文案实体能否在反推文案稿里命中）：null=未校验 */
  consistency_ok: boolean | null;
  consistency_note: string | null;
  /** 风险词命中串 `词|block,词|warn`；null=干净。block 拦过审/投产，warn 只预警 */
  risk_hit: string | null;
  audit_status: AuditStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
  /** 驳回/需改写的理由（必填才允许进这两个态） */
  reject_reason: string | null;
  /**
   * 改前原文留痕，两种来路都会写：① 审核人「改后通过」（passed_edited）；
   * ② 作者驳回后自己改完重提（resubmit）。所以**光看这列非空不能断定是审核人改的**，
   * 要配合 audit_status 判：passed_edited＝审核人改后过；approved＝作者重提后原样过。
   */
  text_before_edit: string | null;
  /**
   * 这条文案的原型（11-04 拍板①）：出稿时**继承所属素材**的 category_id，
   * 之后素材重新归类**不回写**已出候选——已定性的文案不该被带走。
   * `category_name` 只有审核台列表口带。
   */
  category_id?: string | null;
  category_name?: string | null;
  /** 这条文案现在能不能「改后重新提审」：被驳回/需改写 且 你是素材负责人或 admin */
  can_resubmit?: boolean;
  /**
   * 已产条数（批 F 卡片右侧徽标）：这条文案派生的生产单出了几条视频。
   * **只有 `listSummaries` 会带这个键**（整页一次聚合）；详情口不带＝"没查"，
   * 和 0（查了、确实一条没产）是两回事，所以类型是 optional 而不是 number。
   */
  output_count?: number;
  /**
   * 批 J：豆包生产提示词**预览**（过审即自动备好）。⚠️ 预览≠投产稿——
   * 投产时会按钩子编号/角色卡/剧名/档位重新展开，这里只是让你先看个大概，
   * 直接复制它去投板会缺钩子编号等信息。null=还没备好（没过审，或备的过程中
   * 失败了——失败不拦投产，投产时会重新展开）。
   */
  prompt_preview: string | null;
  /** 预览生成时间（null=同上） */
  prompt_preview_at: string | null;
  /** 备预览的实扣（元）。当前口径预览不单独计费，恒 0；保留列是为了对账 */
  cost_preview: number;
  /**
   * 11-06 双产出：出文案时同步生成的**豆包网页版**完整提示词（NAS 模板网页版裁剪，
   * 无段头编号/推荐标题/发布标签，复制整段进 doubao.com 对话框直接用）。
   * null=生成失败/没生成——文案不受影响，用 promptWebSummaries 单独补。
   * 与 prompt_preview 的分工：那列是任务板通道（恒 10s）的过审后预览。
   */
  doubao_prompt: string | null;
  created_at: string;
  // ── 仅 list_summaries 回（join 素材行）；getAsset 的 summaries 不带这些键 ──
  asset_code?: string;
  asset_title?: string | null;
  asset_source_url?: string | null;
  asset_platform?: AssetPlatform | null;
  asset_status?: AssetStatus;
}

/**
 * 生产单条目（_serialize_production）：一条过审文案 × 第 i 个产物 = 一行。
 * board_* 六列 = 与企微后台 AI 视频任务板的对账主键（缺一个就对不上账）。
 */
export interface AssetProduction {
  id: string;
  asset_id: string;
  summary_id: string;
  batch_id: string | null;
  seq: number;
  /** 五位钩子编号（只能来自 hook_id.py 取号，后端绝不编号） */
  hook_code: string | null;
  /** 已废弃：11-02 版取消项目标题行，只读历史 */
  project_title: string | null;
  /** 只含**可投给模型的正文**（投放要求另存 dispatch_note） */
  prompt_text: string | null;
  /** 改名/跳过二次确认/并行等投放要求：只给人看，绝不进 payload */
  dispatch_note: string | null;
  /** 发起生产时冻结的过审文案 */
  prompt_snapshot: string | null;
  /** 推荐视频标题（条数 = 该剧发布号数 K，非固定 5） */
  video_titles: string[];
  /** 本条与同批其它条的差异来源 */
  variant_basis: string | null;
  /** 漂移标记：展开后的提示词与过审文案不是同一条（审的 ≠ 生产的） */
  drift: boolean;
  /** 漂移成因（judge_drift 判的「怎么不像同一条」，只有一个 bool 前端没法显示） */
  drift_reason: string | null;
  /** 意图字段（秒）：板上无时长开关，成片恒 10.08s；更长内容只能拆上/下集两条 */
  duration: number | null;
  channel: AssetProductionChannel | null;
  // ── 任务板对账列 ──
  /** 板上 total = **同一条提示词出几版**（1..20）；与 n（几条差异化提示词）是两个量，混用白烧 n×total */
  board_total: number;
  /** 拥有者标记；不填=无主任务，按天筛不到 */
  board_tag: string | null;
  /** 建任务时由后端生成的完整时间戳（只写日期会「succ 但永久查不到」） */
  board_date: string | null;
  /** 板上 name = 推荐视频标题第 1 条（剥非法字符、≤60 码点） */
  board_name: string | null;
  /** 回读主键（info?date= 返回的 tid） */
  board_tid: string | null;
  /** 回收组 id，拼 /data<outUrl> 用 */
  board_rgid: string | null;
  /**
   * 批 L（投放进度可视化）：板子侧最后看到的行状态（waiting/running/succ…，
   * 多版单可能是「waiting/running」这种拼串；刚认领时是「已投板」）。
   * null = 没投过板 / 人工回写没走到轮询。
   */
  board_last_status: string | null;
  /** 上次板面检查时间（自动投板协程每 45s 一轮）；判断「轮询还活着吗」就看它新不新 */
  board_last_check_at: string | null;
  /** 角色卡在自有桶的 key → 板上 picDatas 来源（同剧同卡）。批 G 后是**历史列**：新单由 card_asset_ids 派生（＝第一张＝主卡），旧单只有这一列 */
  character_card_key: string | null;
  /**
   * 批 G：**多卡保序**（asset_items.id 数组，顺序＝板上 picDatas 顺序）。
   * 一部剧多张定妆照时「谁是第一张」就是主形象——顺序不能由后端 sort 或去重打乱。
   * 空数组/null = 这单没走新口径，读侧回退 character_card_key（存量单不许因为加列就丢卡）。
   */
  card_asset_ids: string[];
  /** 批 I（链路收敛）：本单已收进的成片段数（排除 package/copy 附属文件），生产单列表口才有 */
  output_count?: number;
  status: ProductionState;
  /** 板上失败行**没有原因字段**：这里只能记我们侧的判读，别当成豆包给的成因 */
  error: string | null;
  /** 投了几次（queued 每报一次 +1，重投也计） */
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

/** 产物文件（list_outputs 的逐条字典；不含 qc_result/sha256 等未出口列） */
export interface AssetOutput {
  id: string;
  asset_id: string;
  /** 11-04 起可空：拼接产物（composed）按用户口径不必挂生产单 */
  production_id: string | null;
  kind: AssetOutputKind;
  file_name: string | null;
  file_key: string | null;
  bucket: string | null;
  /** 同样：探不到 = null */
  duration: number | null;
  file_size: number | null;
  resolution: string | null;
  qc_status: AssetQcStatus | null;
  qc_note: string | null;
  created_at: string;
  /** null = 还没人在素材库下过（板侧交付不算） */
  downloaded_at: string | null;
  /** 批 K（素材墙）：归属素材编号 / 生产单钩子号，卡片标注用 */
  asset_code: string | null;
  hook_code: string | null;
  /** 产物首帧直链（1 小时过期）；没帧 = null，卡片画「没有预览图」占位 */
  thumb_url: string | null;
}

/** 反推提示词任务（wechat_download.serialize_prompt_task，详情口透出） */
export interface AssetPromptTask {
  id: string;
  created_by: string | null;
  /** url=粘贴链接，upload=本地视频上传（doc/125 中转） */
  source_type: 'url' | 'upload';
  source_url: string | null;
  file_name: string | null;
  provider_task_id: string | null;
  status: 'processing' | 'success' | 'failed';
  /** 反推文案稿正文（markdown），success 时有值 */
  content: string | null;
  error: string | null;
  max_duration: number | null;
  created_at: string | null;
  updated_at: string | null;
}

// ──────────────────────────────────────────────
// 共用子结构（成本 / 闸门 / 投递计数 / 队列 / 板面 payload）
// ──────────────────────────────────────────────

/** svc.estimate_batch_cost 的预估块 */
export interface AssetCostEstimate {
  count: number;
  prompt_max_duration: number;
  /** 单条预估（元） */
  unit_cost: number;
  total_cost: number;
  breakdown: {
    prompt: number;
    parse: number;
    copy_extract: number;
    upload: number;
  };
  /** 档位 → 整批预估；键是字符串 '60' | '180' | '300' | '600' */
  tiers: Record<string, number>;
}

/** svc.budget_gate 的闸门结论（level=ok 时才有 note 键；blocked/need_approval 分支不带） */
export interface AssetBudgetGateInfo {
  allowed: boolean;
  level: AssetBudgetGate;
  reason: string | null;
  note?: string | null;
  estimate: number;
  /** null = 余额查询失败：此时闸门**按放行处理但带 note**（余额接口有波动，不能因抖动挡死业务） */
  balance: number | null;
}

/** 余额三态：查得到 / 查不到 / 单位换算不到元，三种都必须能区分（否则是假保险） */
export interface AssetBalanceInfo {
  balance: number | null;
  /** 余量原始单位（元/cny/点/…）；未配置或换算失败时可能是 null */
  balance_unit: string | null;
  balance_note: string | null;
}

/**
 * 导入/上传侧的预算预警（_apply_import_budget）。
 * ⚠️ 这里 `gate` 是**闸门档位字符串**，不是 svc.budget_gate 那个 dict（别按 AssetBudgetGateInfo 取值）。
 * 导入本身不扣费，算的是「这批若全按 tier 档反推要多少钱」，所以只可能 ok / need_approval。
 */
export interface AssetImportBudget {
  tier: number;
  cost_estimate: number;
  gate: AssetBudgetGate;
  note: string | null;
  unit_cost: number;
  /** 单批预算上限（元） */
  cap: number;
}

/** 逐批成本（import 口 budgets[]：每条 = AssetImportBudget + 批次标识） */
export interface AssetBatchBudget extends AssetImportBudget {
  batch_id: string;
  batch_code: string;
}

/** 整批汇总成本（import 口 budget：取最坏闸门 + 批数 + 合并预估） */
export interface AssetImportBudgetSummary extends AssetImportBudget {
  batches: number;
}

/** svc.estimate_production_days：按号池把「生产数量 N」折成天数（瓶颈是额度不是工时） */
export interface AssetProductionDaysPlan {
  count: number;
  account_count: number;
  per_account_per_day: number;
  capacity_per_day: number;
  days: number;
}

/** svc.board_capacity_hint：当日投放量软提示（**不硬限**，只把实测说清楚） */
export interface AssetBoardCapacity {
  planned: number;
  /** 含未投单的「今天打算投多少」口径，与 dispatch.today.board_rows 不等价，别互相换算 */
  already_today: number;
  total_today: number;
  soft_cap: number;
  over_cap: number;
  advisory: string | null;
  /**
   * 批 H：这个数**只含素材库自己**今天投的，不含同日在板子上跑的解压线（那条线库里没台账）。
   * 号池是共用池，所以真实余量比这里显示的小——这句是给一线排量看的，别当注释。
   */
  note?: string | null;
}

/** 当日号池事实（不受 batch_id/asset_id 过滤影响——按批次过滤就答不了「今天还能不能再投」） */
export interface AssetDispatchToday {
  /** 板面本地时区切日，'YYYY-MM-DD' */
  day: string;
  /** 生产单行数 */
  tasks: number;
  /** Σ board_total＝号池真正吃掉的条数（软提示线比的是这个，不是 tasks） */
  board_rows: number;
  by_status: Partial<Record<ProductionState, number>>;
  succeeded: number;
  failed: number;
  dispatched: number;
  soft_cap: number;
  over_cap: number;
  note: string;
}

/**
 * 生产单投递计数：`/assets/productions`、`/assets/produce`、`/assets/productions/status` 三处都返回。
 * 两个口径必须分开看：scope 计数（跟 batch_id/asset_id）答「这批投得怎么样」，
 * today 答「今天号池吃进去多少、到手多少」。
 */
export interface AssetDispatchCounts {
  total: number;
  /** 全量分布（含**未投的 order_ready**）；筛 status= 时此列仍是过滤前口径 */
  by_status: Partial<Record<ProductionState, number>>;
  order_ready: number;
  /** 已投 = queued+running+success+failed */
  dispatched: number;
  succeeded: number;
  failed: number;
  /** 分母只算已终态（success+failed）；**没有终态时是 null，不是 0**（0 会被读成「一条都没成」） */
  success_rate: number | null;
  scope_note: string;
  today: AssetDispatchToday;
}

/**
 * 整批排队的段位信息（analyze / summaries-generate / resolve 三处同形）。
 * 提交成功的条会自己离开 eligible 集合，所以 offset 平时就该留 0；
 * 它唯一有用的场景是「队列头部某条反复失败，用它跳过」，不是分页浏览器。
 */
export interface AssetQueueSegment {
  batch_id: string;
  offset: number;
  /** 本段条数（受 ASSET_ANALYZE_MAX_PER_CALL / ASSET_SUMMARY_MAX_PER_CALL 封顶） */
  limit: number;
  /** 本段实际取到并提交的条数 */
  picked: number;
  /** 队列剩余条数（= 全队 − offset − picked） */
  remaining: number;
  hint: string;
}

/**
 * 后台任务台账（D-1 队列化）。出文案与投产都要等模型（单条 ~95s，一批十几条就是十几分钟），
 * 同步等会一路撞上浏览器/nginx 超时，所以带 `async_mode: true` 提交时接口**当场回一个任务号**，
 * 结果靠 `getAssetJob` 轮询取——刷新页面、换浏览器都还查得到（台账在库里，不在前端内存里）。
 */
/**
 * 后台任务类型。六类都有写入方（批 F 加 `frames`、批 H 加 `dispatch`、批 J 加
 * `download`/`prompt_preview`）：`dispatch` 是唯一**往外花钱/花号池额度**的那一类，
 * 所以提交口另带 `confirm`；`download`/`prompt_preview` 是批 J 的搭车动作——
 * 反推时顺带下载原片、过审后自动备提示词，也开放手工批量（重试失败行用）。
 */
export type AssetJobKind =
  | 'summary_generate'
  | 'produce'
  | 'frames'
  | 'dispatch'
  | 'download'
  | 'prompt_preview';
export type AssetJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted';

/** 进度是**现算的粗口径**（协程不回报中间态），别当成百分比看 */
export interface AssetJobProgress {
  total: number | null;
  done: number | null;
  note: string;
}

/** GET /assets/jobs/{id} 与 GET /assets/jobs 的条目 */
export interface AssetJobInfo {
  id: string;
  kind: AssetJobKind;
  /** 白话名称：出钩子文案 / 生成生产单 / 抽帧 / 投板 */
  kind_label: string;
  status: AssetJobStatus;
  status_label: string;
  /** true = queued/running（还没完事），轮询就按这个判停 */
  running: boolean;
  batch_id: string | null;
  planned_units: number | null;
  progress: AssetJobProgress | null;
  /** 提交时的原请求体（追溯/重放口径，含 waive 理由这类一次性入参） */
  params: Record<string, unknown> | null;
  error: string | null;
  /**
   * 终态时是**整份接口响应**（`summary_generate` → AssetSummaryGenerateResponse，
   * `produce` → AssetProduceResponse）；没跑完一定是 null——半份清单会让人误判已完事。
   */
  result: unknown;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** 带 `async_mode: true` 提交时的回执（与同步响应是两种形状，靠 `'queued' in res` 分岔） */
export interface AssetJobAck {
  job_id: string;
  status: AssetJobStatus;
  status_label: string;
  queued: true;
  planned_units: number | null;
  poll_url: string;
  list_url: string;
  message: string;
}

export interface AssetJobListResult {
  items: AssetJobInfo[];
  note: string;
}

/** 后台任务的状态中文名（后端只回英文枚举 + status_label，这里兜底给列表筛选用） */
export const ASSET_JOB_STATUS_LABELS: Record<AssetJobStatus, string> = {
  queued: '排队中',
  running: '正在跑',
  succeeded: '已完成',
  failed: '失败',
  interrupted: '已中断（服务重启，结果不可信）',
};

/** 复核的一条问题（svc.recheck_copy）：problems＝真拦点，warnings＝只留痕不拦 */
export interface AssetRecheckProblem {
  /** shape=超字数/首句过长（拦）/ risk=高风险词（拦）/ consistency=和原视频对不上（只预警） */
  code: string;
  message: string;
}

/** 可直接 POST 企微后台 `/api-g/aivideo/create` 的**七键** payload（多一键板侧不认） */
export interface AssetBoardPayload {
  tag: string;
  /** 用生产单 id 当 reqID（重复导出不换号，回收时直接回指这张单） */
  reqID: string;
  total: number;
  /** 完整时间戳（后端生成）；null=该单没有 board_date */
  date: string | null;
  prompt: string;
  name: string;
  /** 未缩放的原始字节 base64（后端没有 Pillow，超限请先压卡） */
  picDatas: string[];
}

// ──────────────────────────────────────────────
// 列表信封
// ──────────────────────────────────────────────

/** GET /assets */
export interface AssetListResult {
  items: AssetItem[];
  total: number;
  page: number;
  page_size: number;
  /** 后端回显实际生效的排序键（不传 sort 时是 'created_desc'） */
  sort: AssetListSortKey;
}

/** GET /assets/batches —— 只有 items，没有 total */
export interface AssetBatchListResult {
  items: AssetBatch[];
}

/** GET /assets/summaries */
export interface AssetSummaryListResult {
  items: AssetSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** GET /assets/productions */
export interface AssetProductionListResult {
  items: AssetProduction[];
  total: number;
  page: number;
  page_size: number;
  dispatch: AssetDispatchCounts;
}

/** GET /assets/outputs —— 批 K 起带 total（墙要计数翻页） */
export interface AssetOutputListResult {
  total: number;
  items: AssetOutput[];
}

// ──────────────────────────────────────────────
// 请求体（字段名与后端 Pydantic 模型逐字一致，snake_case 保留）
// ──────────────────────────────────────────────

/** ImportBatchRequest */
export interface AssetImportBatchRequest {
  /** 分享链接列表（可含中文文案，后端自动提取第一个 http(s) token） */
  links?: string[];
  /** 批次名，默认「链接导入 <tier>s」；超上限拆批时自动加「（第i/k批）」 */
  name?: string | null;
  project_id?: string | null;
  /** 本批反推计时上限档位（秒），只认 60/180/300/600，默认取配置 180 */
  prompt_max_duration?: number | null;
  /** 跨批次重复**整批**强制入库（默认只提示不建） */
  force_duplicates?: boolean;
  /** 逐条放行：只放行点名的这几条（传 dup.source_url 或原链接都认），别拿整批陪跑 */
  force_urls?: string[] | null;
  /**
   * 11-04 拍板①：导入抽屉的「整批默认原型」——一次点好，这一批每条素材都带上它。
   * 留空＝未分类（**不设为必填**）；入库后每条仍可单独改，改后出稿的文案跟着这一列走。
   */
  category_id?: string | null;
  /** 11-06 用户拍板：默认 true＝导入后自动下载原片（解析 0.01 元/条照记账）；不用管 */
  auto_download?: boolean;
}

/** AnalyzeRequest（真金白银的一步，必须带成本确认） */
export interface AssetAnalyzeRequest {
  /** 点名若干条素材（与 batch_id 二选一，混传 400） */
  asset_ids?: string[];
  /** 计时上限档位 60/180/300/600 */
  max_duration?: number | null;
  /** ≥2 条时必须为 true，否则回 409 确认单 */
  confirmed?: boolean;
  /** 仅 admin：余额闸门 blocked 时强行提交 */
  force?: boolean;
  /** 重跑 stage_prompt=failed 的素材（默认跳过已跑过的，重跑＝重复烧钱） */
  retry_failed?: boolean;
  /**
   * 批 J：反推时顺带把链接素材的原片下载进自有桶（默认 true）。
   * 付费渠道一条 0.01 元解析费；文件素材/图片/已下载过的自动跳过。
   */
  download?: boolean;
  /** 整批排队：不传 asset_ids，按批次取「还没反推」的下一段 */
  batch_id?: string | null;
  offset?: number;
  /** 本段条数，默认/上限 = ASSET_ANALYZE_MAX_PER_CALL */
  limit?: number | null;
  /** 11-06 拍板②：涉及别人导入的批次时必须 true（界面确认「替他人批次花钱」后带上） */
  cross_person_confirm?: boolean;
  /**
   * D-1：true＝闸门与成本确认全过之后当场回任务号（AssetJobAck），提交＋收敛在后台跑，
   * 页面关闭不影响（11-06 前收敛只靠前端轮询，页面一关就卡「反推中」）。页面按钮走 true。
   */
  async_mode?: boolean;
}

/** SummaryGenerateRequest */
export interface AssetSummaryGenerateRequest {
  asset_ids?: string[];
  /** 每条候选数，默认 3，只支持 1~6 */
  count?: number | null;
  /** 给模型的补充要求（如题材/口吻） */
  extra_requirements?: string | null;
  /** 已有文案时是否重生成（默认保留历史候选，只补差额） */
  overwrite?: boolean;
  /** 整批排队：按批次取「反推已成功但还没出文案」的下一段 */
  batch_id?: string | null;
  offset?: number;
  /** 本段条数，默认/上限 = ASSET_SUMMARY_MAX_PER_CALL */
  limit?: number | null;
  /** 整批排队时把 stage_summary=failed 的也捞回 */
  retry_failed?: boolean;
  /** D-1：true＝提交即回任务号（后台跑，轮询取结果）。页面按钮一律走 true */
  async_mode?: boolean;
  /** 11-06 拍板②：涉及别人导入的批次时必须 true（界面确认「替他人批次花钱」后带上） */
  cross_person_confirm?: boolean;
}

/** RefreshBatchRequest（一次收敛整批在跑的反推任务） */
export interface AssetRefreshBatchRequest {
  /** 按批次收敛 stage_prompt=running 的那批（与 asset_ids 二选一） */
  batch_id?: string | null;
  asset_ids?: string[];
  /** 单次最多收敛多少条，默认/上限 = ASSET_ANALYZE_MAX_PER_CALL */
  limit?: number | null;
}

/** ResolveRequest（链接素材**按需回源解析**：显式点、显认、显付费的一次动作，没有 force 后门） */
export interface AssetResolveRequest {
  asset_ids?: string[];
  /** 整批排队：按批次取「链接素材且还没有时长且没付过一次费」的下一段 */
  batch_id?: string | null;
  offset?: number;
  limit?: number | null;
  /** ≥2 条时必须为 true */
  confirmed?: boolean;
  /** 11-06 拍板②：涉及别人导入的批次时必须 true（界面确认「替他人批次花钱」后带上） */
  cross_person_confirm?: boolean;
  /** 11-06 播放直链修复：缓存直链过期后强制重新解析（0.01 元/次）——直链打不开时的自愈出口 */
  retake?: boolean;
}

/** 批 J：链接素材原片下载（反推默认顺带排上；这里也开放手工批量/失败行重试） */
export interface AssetDownloadRequest {
  asset_ids?: string[];
  /** D-1：true＝提交即回任务号（AssetJobAck）。页面按钮一律走 true */
  async_mode?: boolean;
  /** 11-06 拍板②：涉及别人导入的批次时必须 true（界面确认「替他人批次花钱」后带上） */
  cross_person_confirm?: boolean;
}

/** 下载逐条明细：失败原因/error 里写了「失败不记账」还是「已按渠道记账」 */
export interface AssetDownloadItemResult {
  asset_id: string;
  code: string;
  ok: boolean;
  /** 本条实扣解析费（元）；付费渠道 0.01，免费渠道 0 */
  charged: number;
  channel: string | null;
  error: string | null;
  file_key?: string;
  size?: number;
  note?: string;
}

export interface AssetDownloadResponse {
  results: AssetDownloadItemResult[];
  /** 没干活就被跳过的（图片/文件素材/已在桶里/没链接），reason 是白话 */
  skipped: { code: string; reason: string }[];
  downloaded: number;
  charged: number;
  channels: Record<string, number>;
  message: string;
}

/** 批 J：过审文案 → 豆包提示词**预览**（过审自动备；这里也开放手工重跑） */
export interface AssetPromptPreviewRequest {
  summary_ids?: string[];
  /** D-1：true＝提交即回任务号（AssetJobAck）。页面按钮一律走 true */
  async_mode?: boolean;
}

export interface AssetPromptPreviewItemResult {
  summary_id: string;
  ok: boolean;
  /** true=已有预览原样复用，没重新等模型 */
  reused: boolean;
  error: string | null;
  code?: string;
  /** 模型是否自报原样保住了钩子文案；false 时投产会按漂移判拦截重试 */
  kept_verbatim?: boolean;
  note?: string;
}

export interface AssetPromptPreviewResponse {
  results: AssetPromptPreviewItemResult[];
  message: string;
}

/** ReviewRequest */
export interface AssetReviewRequest {
  summary_ids?: string[];
  action: AssetReviewAction;
  /** reject / need_rewrite 必填 */
  reason?: string | null;
  /** pass_edited 必填（改后文案，原文进 text_before_edit） */
  new_text?: string | null;
  /** 仅 admin：复核未过但确需过审时的豁免理由，会写进 AuditLog */
  waive_reason?: string | null;
  /**
   * 仅 admin：**只豁免这几类拦点**（shape / risk / consistency 里挑）。
   * 留空＝整条全放过（旧行为）。勾了 shape 就别想把同条里的违禁词一起带走。
   */
  waive_codes?: string[] | null;
}

/** ProduceRequest（过审文案 → N 条差异化提示词） */
export interface AssetProduceRequest {
  summary_ids?: string[];
  /** 每条文案派生的份数（N 份差异化提示词 = N 个任务），默认 ASSET_PRODUCE_DEFAULT_N */
  n?: number | null;
  /**
   * **意图字段**：板上无时长开关，成片恒 10.08s，通道=wework_aivideo 时只接受 10，
   * 更长请拆上/下集两条各 10s。
   */
  duration?: number | null;
  channel?: AssetProductionChannel | null;
  /** 准备用几个豆包号跑（仅折算天数；后台派号，本系统无号池表），导出/建单都只报数 */
  accounts?: number | null;
  /** 是否调 AutoClip 按 11-02 权威模板展开成可投提示词（默认 true；false 的裸单不许投） */
  expand?: boolean;
  /** 板上 total＝**同一条提示词出几版**（1..20，默认 1）。与 n 是两个量，混用会白烧 n×total */
  board_total?: number | null;
  /** 板上 tag（拥有者标记），缺省用 ASSET_BOARD_TAG；不填=无主任务、按天筛不到 */
  board_tag?: string | null;
  /** 五位钩子编号（hook_id.py 取来的，按 n 的顺序对应）；后端不自己编号 */
  hook_codes?: string[] | null;
  /** 角色卡在自有桶的 key → 板上 picDatas 来源（同剧同卡，按剧分组投）。批 G 起只作**兼容入参**：新单子用 card_asset_ids 挑图 */
  character_card_key?: string | null;
  /**
   * 批 G：**从素材库挑角色卡**（asset_items.id 数组，顺序＝板上 picDatas 顺序）。
   * 取代旧的手填 MinIO key——那个框里打错一个字符，后端照样建单，只是静默出无卡任务。
   * 只收 media_kind=image 的行；传视频 id／已删的 id／桶里没文件的 id，后端在建单**之前**就 400 点名。
   */
  card_asset_ids?: string[] | null;
  /** K＝该剧发布号数，决定推荐视频标题条数（1..20，11-02 版：不再固定 5 条） */
  recommended_title_count?: number | null;
  /**
   * 剧名缩写（NAS《剧名缩写表.json》，全团队统一、禁止临时造）。
   * 推荐标题按 3.1 精简规范要写「剧缩·编号·精简钩子」；不传则模板降级写「编号·精简钩子」
   * 并在偏差说明里标注缺剧缩——缩写表在容器里读不到，只能由一线带进来。
   */
  drama_abbr?: string | null;
  /** 仅 admin：投产前复核未过仍要投递时的豁免理由，写进 AuditLog */
  waive_reason?: string | null;
  /** 仅 admin：只豁免这几类拦点（留空＝整条全放过），与审核台同一口径 */
  waive_codes?: string[] | null;
  /** D-1：true＝提交即回任务号（展开提示词要等模型，后台跑完再轮询取结果） */
  async_mode?: boolean;
}

/** ProductionStatusRequest（投递状态回写：只改状态、补 board_tid、记审计） */
export interface AssetProductionStatusRequest {
  /** 生产单 id 列表（单次上限 = ASSET_ANALYZE_MAX_PER_CALL） */
  ids?: string[];
  /** 只允许人报这四个态；superseded/cancelled/skipped 是系统态，写进来一律 400 */
  status: 'queued' | 'running' | 'success' | 'failed';
  /** 判 failed 必填（我们侧判读，板上失败行没有原因字段） */
  error?: string | null;
  /** 回读主键：逐条钉上，**多条不许批量传**（会把所有单钉成同一个 tid） */
  board_tid?: string | null;
}

// ──────────────────────────────────────────────
// query 参数
// ──────────────────────────────────────────────

/** list_assets 的 sort 取值（failed_first = 任一阶段 failed 顶到最前） */
export type AssetListSortKey = 'created_desc' | 'created_asc' | 'failed_first';

/** GET /assets 的筛选（stage_* 是**阶段级**：status=failed 只说"失败了"，stage_prompt=failed 才说得出是哪一环挂的） */
export interface AssetListParams {
  /**
   * 以下筛选项后端签名都是裸 `Optional[str]`（未知值不报错，只是查不到行），
   * 所以用 `字面量 | (string & {})`：保留枚举值的自动补全，又不拦掉 UI 里的裸 string 状态。
   */
  status?: AssetStatus | string;
  batch_id?: string;
  platform?: string;
  source_kind?: AssetSourceKind | (string & {});
  has_approved_copy?: boolean;
  /** 命中 code / title / source_url */
  keyword?: string;
  created_by?: string;
  /** YYYY-MM-DD，含端点、按 CST 自然日（别的格式 400） */
  date_from?: string;
  /** YYYY-MM-DD，含端点、按 CST 自然日 */
  date_to?: string;
  /** 命中「这条素材的候选里有该审核态」 */
  audit_status?: AuditStatus | string;
  stage_import?: AssetStage | (string & {});
  stage_prompt?: AssetStage | (string & {});
  stage_summary?: AssetStage | (string & {});
  stage_produce?: AssetStage | (string & {});
  stage_compose?: AssetStage | (string & {});
  sort?: AssetListSortKey;
  page?: number;
  /** 默认 50，后端封顶 200 */
  page_size?: number;
  /**
   * 11-04 拍板①：按钩子原型筛。传原型 id；传 `'none'` 只看**未分类**
   * ——列表页顶部那句「未分类 N 条」就是拿这个筛选的 `total`，后端不另开口。
   */
  category_id?: string;
  /**
   * 批 G：`image` 是投产「挑卡」列表的唯一入口参数（只该看见图）。
   * 没有它就得让前端把整批拉回来自己按扩展名筛——那等于把 media_kind 的口径散到前端去。
   */
  media_kind?: AssetMediaKind;
}

/** GET /assets/summaries */
export interface AssetSummaryListParams {
  audit_status?: AuditStatus | string;
  asset_id?: string;
  batch_id?: string;
  /** 只看风险词命中的 */
  only_risk?: boolean;
  /** 只看一致性不过的 */
  only_inconsistent?: boolean;
  /** 只看模型标注的推荐条（审核页默认勾它） */
  recommended_only?: boolean;
  /** 只看「轮到我改」的：被驳回/需改写且是我负责的素材（admin 看全部） */
  only_resubmittable?: boolean;
  page?: number;
  /** 默认 100，后端封顶 300 */
  page_size?: number;
  /**
   * 11-04 拍板①：按**文案自己**那列的原型筛（不是素材的）。
   * 素材重新归类不该把已定性文案带走，所以这里筛的是 `asset_summaries.category_id`。
   * 传 `'none'` ＝只看未分类。
   */
  category_id?: string;
  /** 批 N（评审二 P1）：关键词搜索——正文/素材码模糊匹配（后端 ILIKE，已转义 %/_） */
  q?: string;
}

/** GET /assets/productions（注意：dispatch.by_status 不受 status= 影响） */
export interface AssetProductionListParams {
  status?: ProductionState | string;
  batch_id?: string;
  asset_id?: string;
  page?: number;
  /** 默认 100，后端封顶 300 */
  page_size?: number;
}

/** GET /assets/productions/export */
export interface AssetExportParams {
  batch_id?: string;
  asset_id?: string;
  /** ⚠️ 逗号拼接的**单个字符串**（不是数组），后端自己 split(',') */
  ids?: string;
  /** 准备用几个豆包号跑（只用于折算天数），后端夹在 1..50 */
  accounts?: number;
  format?: AssetExportFormat;
  /** 带违禁词放行（**只有 admin**，且必须同时带 force_reason） */
  force_risk?: boolean;
  /** 放行的那句话理由；后端写进审计，事后要能回答「凭什么放的」 */
  force_reason?: string;
}

/** GET /assets/outputs */
export interface AssetOutputListParams {
  asset_id?: string;
  production_id?: string;
  /** 批 K：按素材的导入批次收敛（走 asset_items 侧，拼接产物也查得到） */
  batch_id?: string;
  kind?: AssetOutputKind | string;
  /** 默认 100，后端封顶 300 */
  limit?: number;
  /** 批 K：翻页偏移，配 total 用 */
  offset?: number;
}

// ──────────────────────────────────────────────
// 各端点响应
// ──────────────────────────────────────────────

/** GET /assets/cost/estimate 的响应（不落库，供批量按钮的二次确认单） */
export interface AssetCostEstimateResponse extends AssetCostEstimate, AssetBalanceInfo {
  gate: AssetBudgetGateInfo;
}

/** 跨批次重复命中（默认只提示不建，放行靠 force_urls / force_duplicates） */
export interface AssetImportDuplicate {
  source_url: string;
  source_url_norm: string;
  existing: {
    code: string;
    title: string | null;
    /** ⚠️ 无导入时间时后端回**空串**（utc_iso(None) → ""），不是 null */
    created_at: string;
    imported_by: string;
    imported_by_user_id: string | null;
    /** 「几月几日 谁 导入（AS-XXXX）」，CST 口径 */
    hint: string;
  };
  hint: string;
}

/** 超单批上限时服务端自动拆批的回显（没拆批 = null） */
export interface AssetImportSplitInto {
  shards: number;
  limit: number;
  per_shard: number[];
  note: string;
}

/** POST /assets/import/batch */
export interface AssetImportBatchResponse {
  /** 第一个批次（兼容单批调用方） */
  batch: AssetBatch;
  batches: AssetBatch[];
  split_into: AssetImportSplitInto | null;
  items: AssetItem[];
  duplicates: AssetImportDuplicate[];
  /** 入参清洗提示（空链接/同批内重复/无法识别的链接），**字符串数组**不是对象数组 */
  skipped: string[];
  budget: AssetImportBudgetSummary;
  budgets: AssetBatchBudget[];
  /** 11-06：导入后自动下载的排队回执（每拆批一条）；没排上时为 null */
  download?: { queued: boolean; job_id: string | null; queued_count: number; note?: string | null }[] | null;
  message: string;
}

/** 上传口逐文件失败项 */
export interface AssetUploadFailure {
  file_name: string;
  error: string;
  /** 批 G：失败项也带分流依据（图片被拒时界面要说「这张图」而不是「这个文件」） */
  media_kind?: AssetMediaKind;
}

/**
 * 批 G：图片入库时的尺寸/画幅提醒（**只列明、不拒收**）。
 * 每条 notes 是后端写好的人话，例如「长边 4200 超过建议上限 2048」。
 * 超限照样入库——一线可能就想用大图，但那必须是他看见这条信息之后选的。
 */
export interface AssetImageNote {
  file_name: string | null;
  resolution: string | null;
  ratio: string | null;
  notes: string[];
}

/** POST /assets/upload/batch 与 POST /assets/upload/retry 同形 */
export interface AssetUploadResponse {
  /** 一个都没成功且批次是本次新建 → 回滚不留孤儿行，此时为 null */
  batch: AssetBatch | null;
  batch_id: string | null;
  items: AssetItem[];
  failed: AssetUploadFailure[];
  /** 失败文件名清单，供一键走 /assets/upload/retry 补投 */
  failed_files: string[];
  budget: AssetImportBudget | null;
  /** 批 G：要留意的图片逐张列（没提醒时是空数组，不是 null） */
  image_notes: AssetImageNote[];
  message: string;
}

/** POST /assets/analyze/batch 的逐条结果 */
export interface AssetAnalyzeResultItem {
  asset_id: string;
  code: string;
  /** null = 没建成任务 */
  prompt_task_id: string | null;
  /** 'persist_failed' 时=已扣费但状态未落库，重试会重复扣费，须人工核对 */
  prompt_task_status: AssetPromptTaskStatus;
  error: string | null;
}

/** 被跳过的素材（已 success/running 的不重复提交；failed 要带 retry_failed=true 才重试） */
export interface AssetSkippedItem {
  code: string;
  reason: string;
}

/** POST /assets/analyze/batch */
export interface AssetAnalyzeResponse {
  estimate: AssetCostEstimate;
  /** 批次累计预估（元）：同批未提交的兄弟条按本次档位×本次单价一起算，闸门按它判 */
  cumulative_cost: number;
  balance: number | null;
  balance_note: string | null;
  gate: AssetBudgetGateInfo;
  results: AssetAnalyzeResultItem[];
  skipped: AssetSkippedItem[];
  /** 点名 asset_ids 形态时为 null */
  queue: AssetQueueSegment | null;
  message: string;
}

/** POST /assets/analyze/refresh-batch 的逐条收敛结果 */
export interface AssetRefreshResultItem {
  asset_id: string;
  code: string;
  stage_prompt: AssetStage;
  status: AssetStatus;
  /** 智令侧任务态；轮询抖动/任务行缺失时可能是 null */
  prompt_task_status: string | null;
  error: string | null;
}

/** 收敛统计：stuck = 在跑却查不到任务行（提交瞬间进程中断的残留）；poll_error = 保持 running 下轮再来 */
export interface AssetRefreshTally {
  success: number;
  failed: number;
  running: number;
  stuck: number;
  poll_error: number;
}

/** POST /assets/analyze/refresh-batch */
export interface AssetRefreshResponse {
  results: AssetRefreshResultItem[];
  refreshed: number;
  tally: AssetRefreshTally;
  /** 点名 asset_ids 形态时为 null（读操作、不扣费） */
  remaining_running: number | null;
  message: string;
}

/** POST /assets/summaries/generate 的逐条结果 */
export interface AssetSummaryGenerateResultItem {
  asset_id: string;
  code: string;
  /** 新建候选条数；0 表示这条没出文案（原因看 error / note） */
  created: number;
  /** 保留的既有候选条数（未勾 overwrite 时只补差额） */
  kept?: number;
  /** AutoClip 回显的模型名 */
  model?: string | null;
  note?: string;
  /** 缺的候选条数（要 3 条只出 1 条 = 审核缺横向对照） */
  candidates_short?: number;
  error?: string;
}

/** POST /assets/summaries/generate */
export interface AssetSummaryGenerateResponse {
  results: AssetSummaryGenerateResultItem[];
  queue: AssetQueueSegment | null;
  message: string;
}

/** POST /assets/summaries/review 的逐条结果 */
export interface AssetReviewResultItem {
  summary_id: string;
  ok: boolean;
  code?: string;
  audit_status?: AuditStatus;
  /** 仅成功条目回；true = 管理员豁免放行（已入审计） */
  waived?: boolean;
  /** 仅成功条目回：这条文案是不是推荐条（模型标注）。藏卡提示的「非推荐」统计吃这里，
   *  不吃当前页 items——豁免重放/跨页勾选时目标行不在当前页，数当前页会漏报。 */
  is_recommended?: boolean;
  /** 仅成功条目回：撤销过审时连带作废的未投递生产单张数 */
  superseded_productions?: number;
  error_code?: string;
  /** 复核未过的拦点（code/message）：只有 shape / risk 会进这里 */
  problems?: AssetRecheckProblem[];
  /**
   * R-6：**拦人的只有超字数和违禁词**，「和原视频对不上」降级成预警放这里。
   * ok=true 也可能带预警——过了，但审核人该看一眼。
   */
  warnings?: AssetRecheckProblem[];
  /** 复核未过时回：这条被拦的问题有哪几类，管理员放行时可按类只放一部分 */
  waivable_codes?: string[];
  error?: string;
}

/** POST /assets/summaries/review */
export interface AssetReviewResponse {
  results: AssetReviewResultItem[];
  message: string;
}

/** ResubmitRequest：被驳回/需改写的文案，改完交回待审队列 */
export interface AssetResubmitRequest {
  summary_ids: string[];
  /** 改后的文案；留空＝不改文案直接回队列重审 */
  new_text?: string | null;
  /** 给审核人的说明（进审计） */
  note?: string | null;
}

/**
 * GET /assets/risk-lexicon：当前生效的风险词表。
 *
 * `effective` 是**真正在拦人**的那份（闸门用的就是它）；
 * `override` 是运营自己配的覆盖值，`defaults` 是内置默认表——
 * 三者分开显示，才看得出「我加的词」和「出厂就有的词」分别是什么。
 */
export interface AssetRiskLexicon {
  effective: { block: string[]; warn: string[] };
  exempt: Record<string, string>;
  defaults: { block: string[]; warn: string[]; exempt: Record<string, string> };
  override: { block: string[]; warn: string[]; exempt: Record<string, string>; inherit: boolean };
  has_override: boolean;
  updated_at: string;
  ttl_seconds: number;
  can_edit: boolean;
}

/** PUT /assets/risk-lexicon 的入参 */
export interface AssetRiskLexiconUpdate {
  block: string[];
  warn: string[];
  exempt: Record<string, string>;
  /** true=在默认表上追加；false=整体替换默认表 */
  inherit: boolean;
}

export interface AssetRiskLexiconUpdateResult {
  ok: boolean;
  effective: { block: string[]; warn: string[] };
  exempt: Record<string, string>;
  updated_at: string;
  notes: string[];
}

// ──────────────────────────────────────────────
// 钩子原型字典（11-04 拍板①：单层、A–G 原名、读全员写仅 admin）
// ──────────────────────────────────────────────

/**
 * 一行原型（`asset_categories`）。
 *
 * 名称**照《钩子模版换皮参数设定.docx》原名录入**，初始 7 行由后端种入，
 * 前端不要自己拼「原型 A」这类短名去比——一律按后端回的字面串显示。
 * `parent_id` 是拍板"留着不填"的单层字典，恒为 null。
 */
export interface AssetCategory {
  id: string;
  name: string;
  parent_id: string | null;
  /** 展示顺序（docx 里 A→G 的次序）；新增不给就排到最后 */
  sort: number;
  /** false＝已下线：不再供新条目挑选，但历史条目仍显示、仍可筛 */
  active: boolean;
  /** 行内说明（docx 的钩法内核原文）。纯展示，不参与任何判定 */
  note: string | null;
  created_at: string;
  updated_at: string;
  /** 引用计数（读口带）：这条挂着多少条素材 / 多少条文案 */
  asset_count?: number;
  copy_count?: number;
}

/** GET /assets/categories */
export interface AssetCategoriesResult {
  items: AssetCategory[];
  /** 列表页那句「未分类 N 条」的数据源（也是 `category_id=none` 的 total） */
  unclassified: { asset_count: number; copy_count: number };
  can_edit: boolean;
  note: string;
}

/** PUT /assets/categories 的一条：带 id＝改，不带 id＝增 */
export interface AssetCategoryUpsert {
  id?: string | null;
  name: string;
  sort?: number | null;
  active?: boolean;
  note?: string | null;
}

/**
 * PUT /assets/categories 的入参。⚠️ **整单语义**：这次没列出来的既有行＝下线
 * （后端不硬删，历史引用留着），所以前端提交必须把要保留的行**全量**带上。
 */
export interface AssetCategoriesUpdate {
  items: AssetCategoryUpsert[];
}

export interface AssetCategoriesUpdateResult {
  ok: boolean;
  added: number;
  updated: number;
  retired: number;
  items: AssetCategory[];
  notes: string[];
}

/** POST /assets/categories/assign：点分类。`category_id` 留空＝清成未分类（不是"不改"） */
export interface AssetCategoryAssignRequest {
  asset_ids?: string[];
  summary_ids?: string[];
  category_id?: string | null;
}

export interface AssetCategoryAssignResult {
  ok: boolean;
  asset_changed: number;
  summary_changed: number;
  category_id: string | null;
  /** 库里查不到的 id：如实回传，不许"看起来改成功了" */
  not_found: string[];
  notes: string[];
}

/** POST /assets/produce 的逐条文案结果 */
export interface AssetProduceResultItem {
  summary_id: string;
  created: number;
  code?: string;
  error_code?: string;
  problems?: AssetRecheckProblem[];
  /** 复核未过时回：被拦的问题有哪几类，管理员放行可按类只放一部分（与审核台同口径） */
  waivable_codes?: string[];
  /** 后端在这一条上显式回 null（成功时） */
  error?: string | null;
}

/** 建单当场的板面口径（date 由后端生成，绝不用前端传的日期） */
export interface AssetProduceBoard {
  channel: AssetProductionChannel;
  tag: string;
  /** 板面本地时区的完整时间戳（isoformat 秒精度） */
  date: string;
  board_total: number;
  /** 任务数（= 生产单条数） */
  tasks: number;
  /** 本批真实投放量 = tasks × board_total（号池当天要吃的条数） */
  planned_rows: number;
  /** 出片规格声明（不可改） */
  output: string;
}

/** 被投产前复核拦下的文案（未生成生产单，钩子编号没被烧掉，可原号重投） */
export interface AssetProduceRecheckFailedItem {
  summary_id: string;
  code: string;
  problems: AssetRecheckProblem[];
}

/** 管理员豁免放行的文案 */
export interface AssetProduceWaivedItem {
  summary_id: string;
  code: string;
  waived: {
    problems: AssetRecheckProblem[];
    reason: string;
    /** 展开后的提示词新命中（admin 豁免的是整条投递，这里一并留痕） */
    prompt_problems?: AssetRecheckProblem[];
  };
}

/** 展开提示词缺十行骨架（**只警示不拦**：缺「负面约束」会出怪片、缺「音频与字幕」会被加字幕） */
export interface AssetProduceSkeletonGap {
  code: string;
  seq: number;
  missing: string[];
}

/** 展开结果与过审文案不是同一条（单子照常生成、不静默丢弃，但逐条点名） */
export interface AssetProduceDriftItem {
  summary_id: string;
  code: string;
  seq: number;
  reason: string | null;
}

/**
 * 推荐标题正文超预算（P1 #19 **软校验**：只提示一线去改，不拦投产、不改状态）。
 * 板面/报表标题列只显示前 22 字（发布侧补 4 字【账号】前缀），展开导出的正文不带前缀
 * → 上限 18 字；字数口径＝含标点不含空白（与后端 count_copy_chars 同一把尺）。
 */
export interface AssetProduceTitleWarning {
  asset_code: string;
  summary_id: string;
  seq: number;
  hook_code: string | null;
  /** 超预算的标题原文 */
  title: string;
  /** 实测字数 */
  chars: number;
  /** 正文字数上限（18） */
  limit: number;
}

/**
 * 批 G：建单当场回显的逐张卡判读（后端 `_card_shape_notes`）。
 * 「哪张卡会出横屏」必须在**建单这一屏**看到——投出去以后账上看不出来。
 * 文案（hint）由后端拼，前端原样显示：口径来自实测（卡决定成片画幅），不是显示偏好。
 */
export interface AssetCardShapeNote {
  asset_id: string;
  code: string | null;
  file_name: string | null;
  width: number | null;
  height: number | null;
  ratio: string | null;
  orientation: 'portrait' | 'landscape' | 'square' | null;
  hint: string;
}

/** 批 G：payload 交付单里的逐张卡（读取结果 + 画幅），一张一行，缺哪张点哪张的名 */
export interface AssetPayloadCard {
  /** 旧口径单值 key 回退出来的卡没有 asset_id */
  asset_id: string | null;
  /** 人话标签：`AS-XXXX（原名）` 或 `旧口径单值 key ...`；读不到时也是它 */
  label: string;
  key: string | null;
  bucket?: string | null;
  resolution?: string | null;
  ratio: string | null;
  orientation: 'portrait' | 'landscape' | 'square' | null;
  /** true = 走的是历史单值 key（没有 card_asset_ids 的存量单） */
  legacy: boolean;
  /** false = 这张卡 base64 没取到 → picDatas 里缺它，投出去就是少一张卡 */
  loaded: boolean;
}

/** 批 G：导出侧卡体检汇总（问题逐条在 payloads[].cards / warnings 里，这里只给条数） */
export interface AssetCardCheck {
  /** 有卡问题的单条数（缺卡／横版／方向不一都算），0 = 这批卡都没毛病 */
  rows_with_card_issues: number;
  note: string;
}

/** POST /assets/produce */
export interface AssetProduceResponse {
  created: number;
  results: AssetProduceResultItem[];
  /** 批 I（链路收敛）：这次新建的生产单 id——投产结果页「顺势投去出片」点名投板用 */
  production_ids?: string[];
  board: AssetProduceBoard;
  /** 按号池折算的天数（accounts 由调用方声明） */
  capacity_hint: AssetProductionDaysPlan;
  /** 当日板面投放量软提示（含**未投单**的口径，与 dispatch.today 不等价） */
  board_capacity: AssetBoardCapacity;
  /** 建单当场就把「今天号池已经吃掉多少、成几条败几条」摆出来 */
  dispatch: AssetDispatchCounts;
  recheck_failed: AssetProduceRecheckFailedItem[];
  recheck_waived: AssetProduceWaivedItem[];
  prompt_skeleton_gaps: AssetProduceSkeletonGap[];
  drifted: AssetProduceDriftItem[];
  /** 推荐标题正文超 18 字的逐条清单（只警示，单子是建成的） */
  title_warnings: AssetProduceTitleWarning[];
  /**
   * 批 G：本次投产挂的角色卡逐张判读（**顺序＝picDatas 顺序**）。
   * D-1 队列化后台跑完才有的结果同样带这一份（job 结果就是本响应原样落库）。
   */
  cards: AssetCardShapeNote[];
  /** 批 G：本次投产实际挂上的卡 id 数组（旧口径单值 key 进来时是空数组） */
  card_asset_ids: string[];
  /** 缺编号/缺标题/豁免/拦下/缺骨架/漂移等提醒（要逐条显示，别只看 message） */
  warnings: string[];
  message: string;
}

/** POST /assets/productions/status 的逐条结果（results 含幂等未动的，blocked 是迁移规则挡下的） */
export interface AssetProductionStatusResultItem {
  id: string;
  hook_code: string | null;
  seq: number;
  asset_id: string;
  batch_id: string | null;
  /** 回写前状态 */
  from: ProductionState;
  /** 本次请求的目标状态 */
  to: ProductionState;
  /** 有 reason = 这条没被改（同态幂等跳过 / 被迁移规则挡下） */
  reason?: string;
  /** 仅真正写入的条目回 */
  attempts?: number;
}

/** POST /assets/productions/status */
export interface AssetProductionStatusResponse {
  updated: number;
  results: AssetProductionStatusResultItem[];
  /** 同态重报的 id 列表 */
  unchanged: string[];
  blocked: AssetProductionStatusResultItem[];
  /**
   * 素材 id → 收敛后的**派生 status**（后端局部变量虽叫 stage_by_asset，
   * 存的却是 apply_stage 的返回值 asset.status，不是阶段态）。
   */
  asset_status: Record<string, AssetStatus>;
  dispatch: AssetDispatchCounts;
  message: string;
}

// ──────────────────────────────────────────────
// 批 H（11-05）：自动投板。口径是「可自动投板，但**逐批人工确认**」
// ──────────────────────────────────────────────

/** POST /assets/productions/dispatch 的请求体 */
export interface AssetDispatchRequest {
  /** 点名要投的生产单 id（单次上限由后端 `ASSET_DISPATCH_MAX_PER_CALL` 管，默认 20） */
  ids: string[];
  /** 人工确认位：后端没有 true 就 400，脚本代签不算确认 */
  confirm?: boolean;
  /** 仅 admin：文案过审后词表又加过词、仍要投这几张（与导出侧 R-4 同一道闸） */
  force_risk?: boolean;
  force_reason?: string;
  /** true＝一个都不新建，只把已经投上板的片子回读＋收回来（不烧额度，所以不看 confirm） */
  recover_only?: boolean;
  /** 默认 true（几十分钟的活，页面按钮一律走后台任务）；false 只给脚本与用例 */
  async_mode?: boolean;
  /** 11-06 拍板②：新建板任务涉及别人导入的批次时必须 true（回收已投的单不花钱，不用这个字段） */
  cross_person_confirm?: boolean;
  /**
   * 11-06 拍板：投递稿可改。生产单 id → 这一次投出去的提示词正文。
   * 只改投出去的那份：库里的 prompt_text／过审文案不动，漂移判定不受影响；
   * 改后的正文照走 block 级风险词重扫（命中 400，或 admin force+理由）。
   */
  prompt_overrides?: Record<string, string>;
}

/** 闸门挡下/拒投的逐条说明（三堆里除"要投的"以外都是这个形状） */
export interface AssetDispatchBlockedItem {
  id: string;
  seq: number;
  hook_code: string | null;
  reason: string;
}

/** 建任务这一步的逐张结果：`to` 是落库后的目标态，`recovered_after_error` 说明 POST 报错但板子其实建上了 */
export interface AssetDispatchCreatedItem {
  id: string;
  hook_code: string | null;
  tids: string[];
  to: ProductionState;
  recovered_after_error?: string;
}

/** 预检（异步回执里随任务号一起给）：闸门分完三堆的结果，跑之前就能看见 */
export interface AssetDispatchPrecheck {
  will_create: number;
  will_recover: number;
  /** Σ board_total＝本批会吃掉多少条号池额度，不是张数 */
  planned_board_rows: number;
  blocked: AssetDispatchBlockedItem[];
  card_warnings: { id: string; hook_code: string | null; warnings: string[] }[];
  capacity: AssetBoardCapacity;
  /** 11-06 拍板：投递稿可改——这次真的带着改稿投出去的生产单 id 列表 */
  prompt_overrides?: string[];
  note: string;
}

/** 投板的异步回执：任务号 + 预检（整份执行结果将来在任务台账里） */
export interface AssetDispatchAck extends AssetJobAck {
  precheck: AssetDispatchPrecheck;
}

/** 同步档的逐张结果（异步档没有这一份，去任务台账的 result 里看） */
export interface AssetDispatchResultItem {
  id: string;
  hook_code: string | null;
  asset_id: string;
  board_total: number;
  tids: string[];
  status: ProductionState;
  board_status: string | null;
  outputs: string[];
  restarted: boolean;
  error?: string;
  note?: string;
  last_read_error?: string;
  download_errors?: { tid: string; error: string }[];
}

/** POST /assets/productions/dispatch 的同步结果（异步档请判 `isAssetJobAck`） */
export interface AssetDispatchResponse {
  /** 本次真建上的板任务张数 */
  dispatched: number;
  /** 本次接续回收（只回读不重建）的张数 */
  recovered: number;
  succeeded?: number;
  failed?: number;
  still_running?: number;
  results?: Record<string, AssetDispatchResultItem>;
  outputs?: Array<{ production_id: string; file_key: string; file_name?: string; resolution?: string | null }>;
  created: AssetDispatchCreatedItem[];
  blocked: AssetDispatchBlockedItem[];
  errors: Array<{ id: string; hook_code: string | null; stage?: string; error: string }>;
  /** 板子回了成功却按日期/tag 认不回来——**绝不能自动重投**，要点名让人去板面对 */
  uncertain: Array<{ id: string; hook_code: string | null; error: string }>;
  card_warnings: { id: string; hook_code: string | null; warnings: string[] }[];
  asset_status?: Record<string, AssetStatus>;
  capacity: AssetBoardCapacity;
  dispatch: AssetDispatchCounts;
  message: string;
}

/** 导出列表的逐条（作废/失败单**状态照实回显、正文不外泄**：prompt_text 置 null） */
export interface AssetExportItem {
  id: string;
  asset_id: string;
  seq: number;
  hook_code: string | null;
  project_title: string | null;
  prompt_text: string | null;
  dispatch_note: string | null;
  video_titles: string[];
  variant_basis: string | null;
  drift: boolean;
  drift_reason: string | null;
  status: ProductionState;
  /** false = superseded/cancelled/skipped/failed，不许投也不许导正文 */
  exportable: boolean;
  board_name: string | null;
  board_total: number;
  board_tag: string | null;
  board_date: string | null;
  character_card_key: string | null;
  /** 批 G：多卡顺序（＝picDatas 顺序）；空数组＝这单只有旧口径单值 key */
  card_asset_ids: string[];
  /** R-4：按**当前**违禁词表重扫正文的命中（只有 block 级；没命中就没这个键） */
  risk_hits?: { word: string; level: string }[];
  /** true = 这条被词表点了名，但 admin 带理由放行了（命中信息照实留着） */
  risk_forced?: boolean;
}

/** R-4：导出前重扫违禁词表的结论（后端每次导出都重扫，不只看当初过审那一刻的表） */
export interface AssetExportRiskRecheck {
  /** 命中几张（0 = 这批都干净） */
  hit_count: number;
  /** 因命中被挡下的单 id */
  blocked: string[];
  /** admin 带理由放行的单 id */
  forced: string[];
  forced_reason: string | null;
  note: string;
}

/** 被挡下不给正文的单 */
export interface AssetExportBlockedItem {
  id: string;
  seq: number;
  status: ProductionState;
  /** 挡下成因（回显给前端，别让一线猜） */
  reason: string;
}

/** GET /assets/productions/export 的公共信封（format=json 时只有这些） */
export interface AssetExportJson {
  format: AssetExportFormat;
  items: AssetExportItem[];
  count: number;
  /** 有正文（可直接投）的条数 */
  ready: number;
  blocked_count: number;
  blocked: AssetExportBlockedItem[];
  /** R-4：导出前按当前词表重扫正文的结论（每次都回，hit_count=0 表示这批干净） */
  risk_recheck: AssetExportRiskRecheck;
  capacity: AssetProductionDaysPlan;
  note: string;
}

/** format=txt：追加「每条一整块 + 批次级产出清单」的整段文本，粘进豆包就够 */
export interface AssetExportTxt extends AssetExportJson {
  format: 'txt';
  /** 只吃「可交付 + 有正文」的单（与 items 的置空口径同一道闸） */
  delivery_count: number;
  /** 产出清单文本；null = 没有可交付单 */
  manifest: string | null;
  /** 被排除（作废/失败/裸单）的条数 */
  excluded: number;
  export_text: string;
}

/** format=payload 的逐条可直接投 */
export interface AssetBoardPayloadItem {
  id: string;
  seq: number;
  hook_code: string | null;
  /** 素材短码（别让一线拿 UUID 去对文件） */
  asset_code: string | null;
  payload: AssetBoardPayload;
  /** 缺角色卡 / 缺推荐标题等提醒：逐条点名，不整批失败 */
  warnings: string[];
  /** 批 G：这条单实际带上板的卡（含 loaded=false 的缺卡，投之前必须处理掉）。逐张点名，必有 */
  cards: AssetPayloadCard[];
}

/** format=payload：追加可直接 POST /api-g/aivideo/create 的七键 */
export interface AssetExportPayload extends AssetExportJson {
  format: 'payload';
  delivery_count: number;
  manifest: string | null;
  excluded: number;
  payloads: AssetBoardPayloadItem[];
  /** 角色卡未缩放的统一提醒（板侧收到超大 picData 会静默建失败） */
  card_advisory: string;
  /** 批 G：这批里有几张单卡有问题（缺卡／横版／方向不一），0 = 干净。只 payload 格式有 */
  card_check: AssetCardCheck;
}

/** GET /assets/outputs/{id}/download（presigned 一次性外链，同时落 downloaded_at + 审计） */
export interface AssetOutputDownloadResult {
  url: string;
  file_name: string | null;
  kind: AssetOutputKind;
  qc_status: AssetQcStatus | null;
  downloaded_at: string;
}

/**
 * 拼接顺序（11-04 用户口径：「可以拼在前或者拼在后」，这就是全部控制粒度）。
 * ⚠️ 顺序同时决定**画幅**：后端按排在最前那段定宽/高/帧率，后一段 scale+pad 进去。
 */
export type AssetConcatOrder = 'asset_first' | 'second_first';

/** B 段来源：素材库里另一条 / 现网已有的切片产物（本地文件先 uploadBatch 成素材再走 asset） */
export type AssetConcatSecondSource = 'asset' | 'slice';

/** POST /assets/concat —— 两段直拼，不选点、不剪切 */
export interface AssetConcatRequest {
  /** A 段：产物挂在这条素材名下，stage_compose 也写它 */
  asset_id: string;
  second_source: AssetConcatSecondSource;
  /** asset_items.id 或 slice_outputs.id */
  second_id: string;
  order?: AssetConcatOrder;
  /** 可选：挂回某条生产单；不传就是无主产物（拼接不强制要有生产单） */
  production_id?: string | null;
  /** 产物文件名前缀，默认用素材编号 */
  title?: string | null;
}

/** POST /assets/concat 的响应（每条一行不覆盖，可反复拼不同顺序） */
export interface AssetConcatResult {
  id: string;
  kind: AssetOutputKind;
  asset_id: string;
  production_id: string | null;
  file_name: string | null;
  file_key: string | null;
  bucket: string | null;
  duration: number | null;
  file_size: number | null;
  /** 实际产出画幅，如 720x1280 —— 由排在最前那段决定 */
  resolution: string | null;
  /** 拼完后的素材状态（通常从 composing 收敛到 ready） */
  asset_status: AssetStatus;
  order: AssetConcatOrder;
  /** 两段的可读标签，按实际拼接顺序排 */
  segments: string[];
  elapsed_seconds: number;
  message: string;
}

/** POST /assets/resolve 的逐条结果 */
export interface AssetResolveResultItem {
  asset_id: string;
  code: string;
  ok: boolean;
  /** 命中渠道：ffprobe（直链本地探测，0 元）/ 免费兜底 yuanbao、preview / 其余按 0.01 元记账 */
  channel: string | null;
  /** 探不到时长仍是 null——「解析成功但源站没给时长」也判 ok=true，只是时长仍为空 */
  duration: number | null;
  /** 本条实扣（元）：发出去就记，与拿不拿得到时长无关；免费渠道记 0 */
  charged: number;
  /** 时效直链（会过期，只作回看用） */
  play_url?: string | null;
  title?: string | null;
  note?: string;
  error?: string;
}

/**
 * POST /assets/resolve。
 * ⚠️ 「没有一条需要回源」时后端**提前 return**，响应里没有 balance / balance_note / gate
 * （estimate 回 null），排队轮询到队尾是 200 不是 400，所以这三键在类型上是可选。
 */
export interface AssetResolveResponse {
  results: AssetResolveResultItem[];
  /** 拿到时长的条数 */
  resolved: number;
  /** 本批实扣合计（元） */
  charged: number;
  skipped: AssetSkippedItem[];
  /** 渠道 → 命中条数 */
  channels: Record<string, number>;
  queue: AssetQueueSegment | null;
  estimate: AssetCostEstimate | null;
  balance?: number | null;
  balance_note?: string | null;
  gate?: AssetBudgetGateInfo;
  message: string;
}

/** GET /assets/{asset_id}：一条素材的全链路（列表点开即看，不用再发三次请求） */
export interface AssetDetailResponse {
  asset: AssetItem;
  summaries: AssetSummary[];
  productions: AssetProduction[];
  /** 反推任务详情；没提交过反推 = null */
  prompt_task: AssetPromptTask | null;
  /** 反推文案稿正文（prompt_task.content）；null = 还没有 */
  prompt_script: string | null;
}

/** GET /assets/{asset_id}/source-download：两种形态分开回，不硬凑 */
export interface AssetSourceDownloadResult {
  mode: AssetSourceDownloadMode;
  /** external 形态为 null（我们侧没有原片） */
  url: string | null;
  asset_code: string;
  file_name: string | null;
  size: number | null;
  /** 同样：探不到 = null */
  duration: number | null;
  downloaded_at: string;
  /** presigned 有效期（秒）；external = null */
  expires_in: number | null;
  /** 非 presigned 时的说明（告诉调用方走 /assets/resolve 才有时效直链） */
  note: string | null;
  /** 仅 external 形态回显原始链接 */
  source_url: string | null;
}

/**
 * GET /assets/{asset_id}/source-preview（批 E）：给抽屉里 `<video>` 用的**内联**地址。
 *
 * 与 `source-download` 的区别只在后端 presign 时不挂 `response-content-disposition`
 * ——挂了 attachment 的链接浏览器只会存盘，`<video>` 拿到是黑屏。
 * Range（拖进度条）由对象存储直接响应，前端不用管。
 */
export interface AssetSourcePreviewResult {
  mode: AssetSourceDownloadMode;
  url: string | null;
  asset_code: string;
  file_name: string | null;
  source_kind: AssetSourceKind;
  platform: string | null;
  size: number | null;
  duration: number | null;
  resolution: string | null;
  expires_in: number | null;
  source_url: string | null;
  /** 11-06 播放直链修复：true＝url 是上次取的时效直链（缓存回放，非桶内文件） */
  cached?: boolean;
  /** 上次取直链的时间（仅 cached 时有） */
  play_url_taken_at?: string | null;
  note: string | null;
}

/** GET /assets/outputs/{output_id}/preview（批 E）：产物内联预览，验收不合格的也能看 */
export interface AssetOutputPreviewResult {
  url: string;
  file_name: string | null;
  kind: string | null;
  size: number | null;
  duration: number | null;
  resolution: string | null;
  qc_status: string | null;
  qc_note: string | null;
  expires_in: number;
}

/** 帧类型：thumb=素材单帧 / grid=九宫格（点开才看）/ output_thumb=产物首帧 */
export type AssetFrameKind = 'thumb' | 'grid' | 'output_thumb';

/** 一张抽出来的帧（批 F）。`url` 是**内联** presign，挂了 attachment 卡片就是黑块 */
export interface AssetFrameItem {
  id: string;
  asset_id: string;
  /** 产物级帧（output_thumb）才有；素材级帧为 null */
  output_id: string | null;
  kind: AssetFrameKind;
  kind_label: string;
  seq: number;
  /** 这一帧取自原片第几秒（10%/45%/80%，不取 t=0） */
  t_offset: number | null;
  width: number | null;
  height: number | null;
  file_size: number | null;
  url: string | null;
  expires_in: number | null;
}

/** 一条素材的卡片图位：三张单帧按 seq 排好，九宫格可空（老数据/坏文件没抽出来） */
export interface AssetFrameSlot {
  thumbs: AssetFrameItem[];
  grid: AssetFrameItem | null;
}

/** GET /assets/frames：一次最多 50 个对象，所以按 50 一块分批拉（见 useAssetFrames） */
export interface AssetFramesResult {
  frames: AssetFrameItem[];
  by_asset: Record<string, AssetFrameSlot>;
  /** 封面＝第 1 张单帧的 presign；素材没帧时为 null */
  cover_url: Record<string, string | null>;
  /** 一张图都没有的素材 id：卡片画「没有预览图」，不是报错 */
  missing: string[];
  note: string;
}

/** POST /assets/frames/extract：手动重抽（只补图，不改任何业务字段） */
export interface AssetFramesExtractResult {
  results: Array<{
    target: 'asset' | 'output';
    id: string;
    code: string | null;
    result: 'extracted' | 'skipped' | 'failed';
    frames: number;
    /** 素材级抽出成功时回封面 key */
    cover?: string | null;
    reason: string | null;
  }>;
  extracted: number;
  skipped: number;
  failed: number;
  /** 这次真落库的**张数**（一个对象 4 张：3 单帧 + 1 九宫格） */
  frames: number;
  note: string;
  message: string;
}

/** POST /assets/{asset_id}/prompt-refresh：轮询反推任务并收敛阶段态 */export interface AssetPromptRefreshResponse {
  /** ⚠️ 这一口的 asset **不带** summary_count 等 4 个计数字段 */
  asset: AssetItem;
  prompt_task: AssetPromptTask;
  /** 仅「链接素材且时长仍为 null」时回：分享页链接拿不到时长，要显式走 /assets/resolve */
  duration_note?: string;
}

// ──────────────────────────────────────────────
// API
// ──────────────────────────────────────────────

/**
 * 上传超时设 0（不掐）：200 个视频文件走一次 multipart，client.ts 默认的 60 秒必然把请求掐死在半路，
 * 而那时文件其实已经落库了——前端只会看到「请求失败」，实际却多了一批素材。
 *
 * Content-Type 沿用本仓库其它上传口（upload.ts / slice.ts / watermark.ts）的写法显式写
 * `multipart/form-data`：axios 1.19 的 transformRequest 只在检测到 JSON 类型时才把 FormData
 * JSON.stringify（写死 JSON 会直接坏掉），而 multipart 这个值会让 adapter 侧的 resolveConfig
 * 把缺 boundary 的 header 清掉，交给浏览器自己带 boundary 重设——所以既不会被序列化坏，也不会丢 boundary。
 */
const UPLOAD_TIMEOUT = 0;

/**
 * 同步等模型的口一律显式带下面的 960s（R-1，11-04 四席位第二轮审核）：
 * client.ts 的默认超时是 **60 秒**，而反推/出文案/投产/解析这四类是「点一下、后端同步
 * 等外部接口」的请求——出文案单条实测 mimo-v2.6-flash **93.6 秒**，同一批里还连续两次
 * 卡到 autoclip 自己的 240s 上限才第三次成功（见 backend `_call_autoclip` 的注释）。
 * 也就是说：**一线点「出文案」必看到「失败」，而后端其实还在跑、钱照扣、候选照落库**。
 * 后端那侧写的是「超时从外到内递减」，前端 60s 是这条口径唯一的破口，所以按 concat
 * 的既有写法统一覆盖成一个常量（新增同步口就加到这里，别再用默认 60s）。
 *
 * ⚠️ 顶穿风险已在批 C（D-1）收掉一半：出文案 / 投产这两个最慢的口，页面按钮一律带
 * `async_mode: true`——后端**提交即回任务号**，前端靠 AssetJobBanner 轮询台账，不再让浏览器
 * 干等十几分钟，所以大 N 投产不用「分次提交」了。下面的 960s 于是只剩两种用处：
 * ① 反推（analyze/batch、refresh-batch）与按需解析（resolve）——这两个仍是同步等外部接口；
 * ② 出文案 / 投产不带 async_mode 的调用（脚本、手工跑），保留原来的同步语义。
 * 换句话说：**新增同步口才需要加到这里；走异步台账的口不需要**（它只等一个任务号，秒回）。
 *
 * 为什么是 960s 而不是照抄后端的 900s：两层**同值**等于掷硬币——后端还在等模型时浏览器
 * 同时到点报错，而请求其实没取消、后端跑完照样落库扣钱。所以浏览器这层必须**比后端那一层长**
 * （900s + 60s 收尾余量），又比 nginx 短。完整链（请求路径从外到内严格递减）：
 * 仓库根 `nginx.conf` 3600s（**现网 /api/ 实际走这份**，clip-nginx 直连 backend:8080）
 * > `frontend/nginx.conf` 1200s（镜像内代理，预览栈/直连 frontend 容器才生效）
 * > 本常量 960s > 后端 `_call_autoclip` 900s > autoclip 单次 `API_TIMEOUT` 600s。
 * 详见 backend `app/api/assets.py::_call_autoclip` 的超时链注释；契约测试
 * `tests/integration/test_asset_library_api.py::test_autoclip_timeout_chain_and_single_inner_retry`
 * 会把这几层钉死，改一层就要改另几层。
 */
const MODEL_WAIT_TIMEOUT = 960000;

export const assetApi = {
  // 素材列表：一行 = 一条素材（批次只是筛选维度，不做批次父行页）
  listAssets: (params?: AssetListParams) =>
    client.get('/assets', { params }) as Promise<AssetListResult>,

  // 链接批量导入：跨批次去重只提示不硬拒，超单批上限由服务端自动拆批
  importBatch: (data: AssetImportBatchRequest) =>
    client.post('/assets/import/batch', data) as Promise<AssetImportBatchResponse>,

  // 视频文件批量上传（multipart，可多文件）→ 落自有桶 raw-footage/asset/ 前缀
  // Content-Type 只给不带 boundary 的 multipart/form-data：axios 在 adapter 里会把它清掉，
  // 交给浏览器补 boundary（完全不设则命中实例默认 application/json，FormData 会被 JSON.stringify）。
  // 单请求整包上限 500MB（nginx），60s 默认超时会掐断大视频，故 timeout 关闭。
  uploadBatch: (
    data: {
      files: File[];
      name?: string;
      project_id?: string;
      /** 本批反推计时上限档位（秒）——注意这个口的 Form 字段叫 max_duration，不是 prompt_max_duration */
      max_duration?: number;
      /** 传已有批次 id 可把多次提交并进同一批（前端一次建批次、分批投） */
      batch_id?: string;
      /**
       * 11-04 拍板①：文件上传同样吃「整批默认原型」。
       * ⚠️ 补投口（retryUpload）**不收**这个参数——它的语义是"把上次没成功的补回同一批"，
       * 后端按原批里出现过的那一个原型自动继承（原批混了两个原型就不猜、落未分类）。
       */
      category_id?: string;
    },
    onProgress?: (percent: number) => void,
  ) => {
    const form = new FormData();
    data.files.forEach((f) => form.append('files', f));
    if (data.name != null) form.append('name', data.name);
    if (data.project_id != null) form.append('project_id', data.project_id);
    if (data.batch_id != null) form.append('batch_id', data.batch_id);
    if (data.category_id != null) form.append('category_id', data.category_id);
    if (data.max_duration != null) form.append('max_duration', String(data.max_duration));
    return client.post('/assets/upload/batch', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: UPLOAD_TIMEOUT,
      onUploadProgress: (progressEvent) => {
        if (!onProgress) return;
        const total = progressEvent.total || 0;
        if (total > 0) onProgress(Math.min(100, Math.round((progressEvent.loaded / total) * 100)));
      },
    }) as Promise<AssetUploadResponse>;
  },

  // 失败文件补投进**同一批次**（文件字节不在服务端留存，必须由前端把原文件再传一次）
  retryUpload: (data: { batch_id: string; files: File[] }, onProgress?: (percent: number) => void) => {
    const form = new FormData();
    form.append('batch_id', data.batch_id);
    data.files.forEach((f) => form.append('files', f));
    return client.post('/assets/upload/retry', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: UPLOAD_TIMEOUT,
      onUploadProgress: (progressEvent) => {
        if (!onProgress) return;
        const total = progressEvent.total || 0;
        if (total > 0) onProgress(Math.min(100, Math.round((progressEvent.loaded / total) * 100)));
      },
    }) as Promise<AssetUploadResponse>;
  },

  // 成本预览：批量按钮的二次确认单先调这个（不落库，只给预估+余额+闸门结论）
  estimateCost: (params?: {
    count?: number;
    max_duration?: number;
    /** 文件形态反推要经 doc/125 中转上传一次 */
    need_upload?: boolean;
    /** 把 doc/107 的 0.01 元/次计进预估（回源解析前先拿这个数） */
    need_parse?: boolean;
  }) => client.get('/assets/cost/estimate', { params }) as Promise<AssetCostEstimateResponse>,

  // 批量反推提示词（智令 doc/120）：按计时上限扣费，≥2 条必须 confirmed=true，否则 409 回确认单。
  // 带 async_mode:true 时当场回任务号（AssetJobAck），收敛在后台跑，结果去 getAssetJob / 列表阶段标签看
  analyzeBatch: (data: AssetAnalyzeRequest) =>
    client.post('/assets/analyze/batch', data, { timeout: MODEL_WAIT_TIMEOUT }) as Promise<
      AssetAnalyzeResponse | AssetJobAck
    >,

  // 一次收敛整批在跑的反推任务（读操作、不扣费；200 条不该发 200 次单条请求）
  refreshAnalyzeBatch: (data: AssetRefreshBatchRequest) =>
    client.post('/assets/analyze/refresh-batch', data, { timeout: MODEL_WAIT_TIMEOUT }) as Promise<AssetRefreshResponse>,

  // 链接素材按需回源解析：显式点、显认、显付费的一次动作（没有 force 后门，blocked 只能充值或改直链）
  resolveAssets: (data: AssetResolveRequest) =>
    client.post('/assets/resolve', data, { timeout: MODEL_WAIT_TIMEOUT }) as Promise<AssetResolveResponse>,

  // 批 J：把链接素材的原片拉回自有桶（四件套：解析→拉流→落桶→补时长）。
  // 幂等：已在桶里的自动跳过；付费渠道按 0.01 元/条记账。失败行改完原因可重跑。
  downloadSources: (data: AssetDownloadRequest) =>
    client.post('/assets/download', data, { timeout: MODEL_WAIT_TIMEOUT }) as Promise<
      AssetDownloadResponse | AssetJobAck
    >,

  // 批 J：过审文案备豆包提示词预览（预览≠投产稿，投产时会重新展开）。
  // 幂等：已有预览的复用不重复等模型；失败不拦投产。
  previewPrompt: (data: AssetPromptPreviewRequest) =>
    client.post('/assets/summaries/preview-prompt', data, { timeout: MODEL_WAIT_TIMEOUT }) as Promise<
      AssetPromptPreviewResponse | AssetJobAck
    >,

  // 批量出钩子文案候选（默认 3 条：疑问式/陈述式/台词摘录式）；前置是反推已成功。
  // 带 `async_mode: true` 时**当场回任务号**（AssetJobAck），结果去 getAssetJob 轮询取；
  // 不带则同步等到模型跑完（给脚本/手动跑用，页面按钮一律走异步，别让一线干等十几分钟）。
  generateSummaries: (data: AssetSummaryGenerateRequest) =>
    client.post('/assets/summaries/generate', data, { timeout: MODEL_WAIT_TIMEOUT }) as Promise<
      AssetSummaryGenerateResponse | AssetJobAck
    >,

  // 文案审核队列（素材列表点「文案」也走这里）
  listSummaries: (params?: AssetSummaryListParams) =>
    client.get('/assets/summaries', { params }) as Promise<AssetSummaryListResult>,

  // 批量审核：生产者不得自审（admin 除外）、驳回必填理由、改后通过留痕、过审前必须过复核
  reviewSummaries: (data: AssetReviewRequest) =>
    client.post('/assets/summaries/review', data) as Promise<AssetReviewResponse>,

  // 改后重新提审：驳回后文案作者改完交回待审队列（素材负责人或 admin）
  resubmitSummaries: (data: AssetResubmitRequest) =>
    client.post('/assets/summaries/resubmit', data) as Promise<AssetReviewResponse>,

  // 11-06 双产出补口：给缺网页版提示词的候选单独补/重出（一次最多 10 条，同步等模型）
  promptWebSummaries: (data: { summary_ids: string[]; force?: boolean }) =>
    client.post('/assets/summaries/prompt-web', data) as Promise<{ results: Array<{ summary_id: string; code?: string | null; seq?: number; ok?: boolean; note?: string; error?: string }>; filled: number; message: string }>,

  // 风险词库：读当前生效词表（block=拦 / warn=警 / exempt=豁免正则），admin 可改
  getRiskLexicon: () =>
    client.get('/assets/risk-lexicon') as Promise<AssetRiskLexicon>,

  updateRiskLexicon: (data: AssetRiskLexiconUpdate) =>
    client.put('/assets/risk-lexicon', data) as Promise<AssetRiskLexiconUpdateResult>,

  // 钩子原型字典（11-04 拍板①）：读全员、写仅 admin，形态与风险词库一致。
  // 字典是**表**不是 system_config——素材/文案要按它筛选，JSON 名单没法 join，
  // 也没法给每行挂「下线」状态与引用计数。
  listCategories: () =>
    client.get('/assets/categories') as Promise<AssetCategoriesResult>,

  updateCategories: (data: AssetCategoriesUpdate) =>
    client.put('/assets/categories', data) as Promise<AssetCategoriesUpdateResult>,

  // 点原型：素材/文案各自留痕；`category_id` 留空＝清成未分类（不是"不改"）
  assignCategory: (data: AssetCategoryAssignRequest) =>
    client.post('/assets/categories/assign', data) as Promise<AssetCategoryAssignResult>,

  // 过审文案 → N 条差异化提示词（生产单）；P0 到「生产单可导出」为止，投板是人工动作。
  // 带 `async_mode: true` 时当场回任务号（展开提示词按 n 逐条调模型，30 条就是十几分钟）。
  produce: (data: AssetProduceRequest) =>
    client.post('/assets/produce', data, { timeout: MODEL_WAIT_TIMEOUT }) as Promise<
      AssetProduceResponse | AssetJobAck
    >,

  // 11-06 拍板③ 回显口：查一批钩子编号哪些已经被钉在生产单上（≤100 个）。
  // 只做回显，不代取号——取号仍走 hook_id.py，后端不预占不代发。
  hookCodesUsed: (codes: string[]) =>
    client.get('/assets/hook-codes/used', { params: { codes: codes.join(',') } }) as Promise<{
      used: { code: string; asset_code: string; seq: number; status: string }[];
    }>,

  // 后台任务台账：刷新页面/换浏览器后靠这两个口找回「我刚才点的那批还在不在跑」
  listAssetJobs: (params?: {
    kind?: AssetJobKind;
    status?: AssetJobStatus;
    batch_id?: string;
    only_open?: boolean;
    include_frames?: boolean;
    limit?: number;
  }) => client.get('/assets/jobs', { params }) as Promise<AssetJobListResult>,

  getAssetJob: (jobId: string) =>
    client.get(`/assets/jobs/${jobId}`) as Promise<AssetJobInfo>,

  // 投递状态回写：人投完板把真实结果写回台账（只改状态 + 补 board_tid + 记审计，不碰成本）
  updateProductionStatus: (data: AssetProductionStatusRequest) =>
    client.post('/assets/productions/status', data) as Promise<AssetProductionStatusResponse>,

  /**
   * 自动投板（批 H）：把点名的生产单真投上企微后台任务板，轮询出片并把成片收进产物。
   *
   * 默认 `async_mode: true` → 当场回 `AssetDispatchAck`（任务号 + **预检**），
   * 因为一次投板＝建任务＋等板子出片（实测单条 25 分钟起）＋下载落桶，
   * 同步等必然顶穿超时链。跑完的整份结果在任务台账 `/assets/jobs/{id}` 里。
   * 用 `isAssetJobAck(res)` 分岔，别判 `results`（异步回执里就是没有它，故意的）。
   */
  dispatchProductions: (data: AssetDispatchRequest) =>
    client.post('/assets/productions/dispatch', data) as Promise<
      AssetDispatchResponse | AssetDispatchAck
    >,

  // 生产单列表 + 投递计数（by_status 走过滤前口径，不跟 status= 一起筛）
  listProductions: (params?: AssetProductionListParams) =>
    client.get('/assets/productions', { params }) as Promise<AssetProductionListResult>,

  // 导出提示词（GET 带审计是有意为之：交付动作必须可追溯）
  // 返回形态按 format 分岔：json=AssetExportJson；txt=AssetExportTxt（带 export_text）；payload=AssetExportPayload（带 payloads）
  exportProductions: (params?: AssetExportParams) =>
    client.get('/assets/productions/export', { params }) as Promise<
      AssetExportJson | AssetExportTxt | AssetExportPayload
    >,

  // 产物列表（P0 通常为空；豆包成片 / 合成成片由 P1/P2 写入）
  listOutputs: (params?: AssetOutputListParams) =>
    client.get('/assets/outputs', { params }) as Promise<AssetOutputListResult>,

  // 产物下载：presigned 外链（验收 failed 的会被 409 挡住，不静默交付）
  downloadOutput: (outputId: string) =>
    client.get(`/assets/outputs/${outputId}/download`) as Promise<AssetOutputDownloadResult>,

  // 简单拼接：两段按人选顺序直拼（不选点不剪切）。同步等 ffmpeg——
  // 两条短片实测几秒到几十秒，但"从桶里取回两段 + 重编码"最坏会超过 client.ts 默认的 60 秒，
  // 那时后端其实还在跑、前端先报超时。上限与后端 autoclip 的 900s 同口径（同一个常量）。
  concat: (data: AssetConcatRequest) =>
    client.post('/assets/concat', data, { timeout: MODEL_WAIT_TIMEOUT }) as Promise<AssetConcatResult>,

  // 素材详情：含全部文案候选、生产单、反推任务与反推文案稿正文
  getAsset: (assetId: string) =>
    client.get(`/assets/${assetId}`) as Promise<AssetDetailResponse>,

  // 素材原文件下载（file=自有桶 presigned；link=只回显原始链接，url 为 null）
  downloadAssetSource: (assetId: string) =>
    client.get(`/assets/${assetId}/source-download`) as Promise<AssetSourceDownloadResult>,

  // 批 E：抽屉里直接播原片（内联，不存盘）
  previewAssetSource: (assetId: string) =>
    client.get(`/assets/${assetId}/source-preview`) as Promise<AssetSourcePreviewResult>,

  // 11-06 素材删除：本人删自己的、admin 删任意；挂着文案/生产单/产物默认 409，
  // admin 带 force+reason 连坐强删（理由进审计）。
  deleteAsset: (assetId: string, opts?: { force?: boolean; reason?: string }) =>
    client.delete(`/assets/${assetId}`, {
      params: { force: opts?.force || undefined, reason: opts?.reason || undefined },
    }) as Promise<{ deleted: string; force: boolean; removed_outputs: number; removed_frames: number; removed_objects: number; message: string }>,

  // 批 E：产物内联预览（验收不合格的也给看——看一眼为什么废，和"能不能投出去"是两件事）
  previewOutput: (outputId: string) =>
    client.get(`/assets/outputs/${outputId}/preview`) as Promise<AssetOutputPreviewResult>,

  // 卡片图（批 F）：按素材/产物**批量**取帧。后端一次最多 50 个对象，
  // 所以别把整页 id 直接塞进来——用 assetFramesChunked 按 50 切块再合并。
  frames: (params: { asset_ids?: string[]; output_ids?: string[]; kind?: AssetFrameKind }) =>
    client.get('/assets/frames', {
      params: {
        asset_ids: params.asset_ids?.join(','),
        output_ids: params.output_ids?.join(','),
        kind: params.kind,
      },
    }) as Promise<AssetFramesResult>,

  /**
   * 一页素材的卡片图：按 50 个对象一块发（后端硬上限），逐块合并。
   * 某一块失败就跳过——卡片没图是"这条没预览"，不该把整页审核台变成红叉。
   */
  framesForAssets: async (assetIds: string[]): Promise<AssetFramesResult> => {
    const merged: AssetFramesResult = { frames: [], by_asset: {}, cover_url: {}, missing: [], note: '' };
    const uniq = Array.from(new Set(assetIds.filter(Boolean)));
    for (let i = 0; i < uniq.length; i += 50) {
      const chunk = uniq.slice(i, i + 50);
      try {
        // 直接打 client，不绕 `assetApi.frames`：对象字面量里自引用会让 TS 把 assetApi
        // 推成循环 any（这个文件是全站类型最密的入口，别给它留这个洞）。
        const res = (await client.get('/assets/frames', {
          params: { asset_ids: chunk.join(',') },
        })) as AssetFramesResult;
        merged.frames.push(...res.frames);
        Object.assign(merged.by_asset, res.by_asset);
        Object.assign(merged.cover_url, res.cover_url);
        merged.missing.push(...res.missing);
      } catch {
        // 这块整体失败：当作「这些素材没图」，卡片自己画空位，别把整页审核台搞红
        merged.missing.push(...chunk);
      }
    }
    return merged;
  },

  // 手动重抽（只补图）：默认同步跑，超过单批上限后端会 400 提示走 async_mode
  extractFrames: (data: { asset_ids?: string[]; output_ids?: string[]; force?: boolean; async_mode?: boolean }) =>
    client.post('/assets/frames/extract', data) as Promise<AssetFramesExtractResult | AssetJobAck>,

  // 单条反推状态刷新并收敛阶段态（直链素材在这里顺带探一次时长，探不到仍是 null）
  refreshAssetPrompt: (assetId: string) =>
    client.post(`/assets/${assetId}/prompt-refresh`) as Promise<AssetPromptRefreshResponse>,

  // 批次列表（含成本预估/实扣，对账页用；只有 items，没有 total）
  listBatches: (params?: { limit?: number }) =>
    client.get('/assets/batches', { params }) as Promise<AssetBatchListResult>,
};

// ──────────────────────────────────────────────
// 后台任务（D-1）的前端配套
// ──────────────────────────────────────────────

/**
 * 提交回执到底是「同步结果」还是「任务号」——两种形状靠 `queued` 分岔。
 * 后端故意让异步回执**不带** `results`，所以这里判 `queued === true` 就够，
 * 不要写成 `'results' in res`（异步回执里将来加了字段就会误判成同步）。
 */
export const isAssetJobAck = (res: unknown): res is AssetJobAck =>
  !!res && typeof res === 'object' && (res as AssetJobAck).queued === true && !!(res as AssetJobAck).job_id;

/**
 * 轮询一个后台任务到终态。
 *
 * 节奏 3s：出文案单条 ~95s、投产一批几分钟，3s 足够跟手又不至于刷爆接口。
 * 上限默认 30 分钟——比后端单条 900s 长，但**不能无限等**：真的卡住了要报错让人去看台账，
 * 而不是让按钮转圈转到人关页面。
 */
export async function waitForAssetJob(
  jobId: string,
  opts?: { intervalMs?: number; timeoutMs?: number; onTick?: (job: AssetJobInfo) => void },
): Promise<AssetJobInfo> {
  const interval = opts?.intervalMs ?? 3000;
  const deadline = Date.now() + (opts?.timeoutMs ?? 30 * 60 * 1000);
  // 第一次先等一下再查：刚提交的 1 秒内查到的必然是 queued，白跑一个请求
  for (;;) {
    await new Promise((r) => setTimeout(r, interval));
    const job = await assetApi.getAssetJob(jobId);
    opts?.onTick?.(job);
    if (!job.running) return job;
    if (Date.now() > deadline) {
      throw new Error(
        `后台任务跑了超过 ${Math.round((opts?.timeoutMs ?? 30 * 60 * 1000) / 60000)} 分钟还没完，` +
          '前端不再干等——任务号 ' + jobId + '，到任务台账里看它现在的状态',
      );
    }
  }
}

// ──────────────────────────────────────────────
// 展示口径（后端只回英文枚举，中文名统一放这里，四个面板共用一套）
// ──────────────────────────────────────────────

/** 反推计时上限档位（秒）：只认这四档，默认 180。600 档一条 0.324 元，不是笔小钱 */
export const DURATION_TIERS = [60, 180, 300, 600] as const;
export const DEFAULT_TIER = 180;

export const ASSET_STAGE_LABELS: Record<AssetStage, string> = {
  pending: '未开始',
  running: '进行中',
  success: '成功',
  failed: '失败',
  skipped: '跳过',
};

/** derive_status 的 13 个派生态（值以 models/asset.py 的 AS_* 为准） */
export const ASSET_STATUS_LABELS: Record<AssetStatus, string> = {
  draft: '草稿',
  importing: '导入中',
  waiting_prompt: '等读视频',
  analyzing: '读视频中',
  summarizing: '出文案中',
  awaiting_review: '等审核',
  ready_to_produce: '可以出生产单',
  producing: '正在出生产单',
  composing: '拼接中',
  ready: '可交付',
  failed: '失败',
  archived: '已归档',
  /** 批 G：图片素材的终点态——它的「下一步」不是提交，是**被投产挑走** */
  image_ready: '图片已入库（只当角色卡）',
};

/**
 * 复核问题类型 → 一线看得懂的说法（后端 problems/warnings 里的 code）。
 * 后端给的是英文枚举（shape/risk/consistency），一线看不懂，界面一律走这张表。
 */
export const RECHECK_CODE_LABELS: Record<string, string> = {
  shape: '字数或断句超限',
  risk: '含违禁词',
  consistency: '和原视频对不上',
};

export const AUDIT_STATUS_LABELS: Record<AuditStatus, string> = {
  pending: '等审核',
  approved: '已过审',
  rejected: '已驳回',
  need_rewrite: '要求改写',
  passed_edited: '改后通过',
};

export const PRODUCTION_STATE_LABELS: Record<ProductionState, string> = {
  order_ready: '还没投',
  queued: '已投上板',
  running: '正在出片',
  awaiting_rewrite: '要求改写',
  success: '出片成功',
  failed: '投板失败',
  cancelled: '已取消',
  skipped: '已跳过',
  superseded: '已作废',
};

/**
 * 人**只能报**这四个态；superseded/cancelled/skipped/awaiting_rewrite 是系统态，
 * 从回写口写进来等于让人手改台账，后端一律 400。
 */
/**
 * 人工回写允许的四个态（＝AssetProductionStatusRequest.status 的取值域）。
 * 系统态 superseded/cancelled/skipped 走这个口会被后端 400，所以选择器里根本不给它们。
 */
export type DispatchReportStatus = AssetProductionStatusRequest['status'];

export const DISPATCH_REPORT_STATUSES: DispatchReportStatus[] = ['queued', 'running', 'success', 'failed'];

/** 候选风格（HOOK_STYLES）：审核台用来标三条的差别 */
export const HOOK_STYLE_LABELS: Record<AssetHookStyle, string> = {
  question: '问句式',
  statement: '陈述句',
  dialogue: '台词摘录',
};

/** 五段流水线（面板列头 + 详情抽屉共用） */
export const STAGE_FIELDS: Array<[keyof AssetItem, string]> = [
  ['stage_import', '导入'],
  ['stage_prompt', '反推文案'],
  ['stage_summary', '文案'],
  ['stage_produce', '生产单'],
  ['stage_compose', '拼接'],
];

