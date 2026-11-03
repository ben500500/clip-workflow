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
 *   → 审核 → 生产单（N 条差异化提示词）→ 导出 payload 投企微后台任务板 → 人工回写投递态
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
  | 'archived';

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

/** 原文件下载口返回形态：stored=自有桶 presigned / external=只有分享链接 */
export type AssetSourceDownloadMode = 'stored' | 'external';

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
  source_url: string | null;
  platform: AssetPlatform | null;
  file_name: string | null;
  file_key: string | null;
  bucket: string | null;
  file_size: number | null;
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
  /** 合成阶段态（P1 写入） */
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
  /** 一致性校验（文案实体能否在反推详规里命中）：null=未校验 */
  consistency_ok: boolean | null;
  consistency_note: string | null;
  /** 风险词命中串 `词|block,词|warn`；null=干净。block 拦过审/投产，warn 只预警 */
  risk_hit: string | null;
  audit_status: AuditStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
  /** 驳回/需改写的理由（必填才允许进这两个态） */
  reject_reason: string | null;
  /** 改后通过（passed_edited）的原文留痕，配合 AuditLog 供 admin 抽检 */
  text_before_edit: string | null;
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
  /** 角色卡在自有桶的 key → 板上 picDatas 来源（同剧同卡） */
  character_card_key: string | null;
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
  production_id: string;
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
  /** 反推详规正文（markdown），success 时有值 */
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

/** 复核拦下的单条问题（svc.recheck_copy 的 problems 项，只收 block 级） */
export interface AssetRecheckProblem {
  /** shape=超字数/首句过长 / risk=高风险词 / consistency=与反推详规对不上 */
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

/** GET /assets/outputs —— 只有 items，没有 total */
export interface AssetOutputListResult {
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
  /** 整批排队：不传 asset_ids，按批次取「还没反推」的下一段 */
  batch_id?: string | null;
  offset?: number;
  /** 本段条数，默认/上限 = ASSET_ANALYZE_MAX_PER_CALL */
  limit?: number | null;
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
  /** 角色卡在自有桶的 key → 板上 picDatas 来源（同剧同卡，按剧分组投） */
  character_card_key?: string | null;
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
  page?: number;
  /** 默认 100，后端封顶 300 */
  page_size?: number;
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
}

/** GET /assets/outputs */
export interface AssetOutputListParams {
  asset_id?: string;
  production_id?: string;
  kind?: AssetOutputKind | string;
  /** 默认 100，后端封顶 300 */
  limit?: number;
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
  message: string;
}

/** 上传口逐文件失败项 */
export interface AssetUploadFailure {
  file_name: string;
  error: string;
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
  /** 仅成功条目回：撤销过审时连带作废的未投递生产单张数 */
  superseded_productions?: number;
  error_code?: string;
  /** 复核未过的拦点（code/message） */
  problems?: AssetRecheckProblem[];
  error?: string;
}

/** POST /assets/summaries/review */
export interface AssetReviewResponse {
  results: AssetReviewResultItem[];
  message: string;
}

/** POST /assets/produce 的逐条文案结果 */
export interface AssetProduceResultItem {
  summary_id: string;
  created: number;
  code?: string;
  error_code?: string;
  problems?: AssetRecheckProblem[];
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

/** POST /assets/produce */
export interface AssetProduceResponse {
  created: number;
  results: AssetProduceResultItem[];
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
}

/** GET /assets/outputs/{id}/download（presigned 一次性外链，同时落 downloaded_at + 审计） */
export interface AssetOutputDownloadResult {
  url: string;
  file_name: string | null;
  kind: AssetOutputKind;
  qc_status: AssetQcStatus | null;
  downloaded_at: string;
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
  /** 反推详规正文（prompt_task.content）；null = 还没有 */
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

/** POST /assets/{asset_id}/prompt-refresh：轮询反推任务并收敛阶段态 */
export interface AssetPromptRefreshResponse {
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
    },
    onProgress?: (percent: number) => void,
  ) => {
    const form = new FormData();
    data.files.forEach((f) => form.append('files', f));
    if (data.name != null) form.append('name', data.name);
    if (data.project_id != null) form.append('project_id', data.project_id);
    if (data.batch_id != null) form.append('batch_id', data.batch_id);
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

  // 批量反推提示词（智令 doc/120）：按计时上限扣费，≥2 条必须 confirmed=true，否则 409 回确认单
  analyzeBatch: (data: AssetAnalyzeRequest) =>
    client.post('/assets/analyze/batch', data) as Promise<AssetAnalyzeResponse>,

  // 一次收敛整批在跑的反推任务（读操作、不扣费；200 条不该发 200 次单条请求）
  refreshAnalyzeBatch: (data: AssetRefreshBatchRequest) =>
    client.post('/assets/analyze/refresh-batch', data) as Promise<AssetRefreshResponse>,

  // 链接素材按需回源解析：显式点、显认、显付费的一次动作（没有 force 后门，blocked 只能充值或改直链）
  resolveAssets: (data: AssetResolveRequest) =>
    client.post('/assets/resolve', data) as Promise<AssetResolveResponse>,

  // 批量出钩子文案候选（默认 3 条：疑问式/陈述式/台词摘录式）；前置是反推已成功
  generateSummaries: (data: AssetSummaryGenerateRequest) =>
    client.post('/assets/summaries/generate', data) as Promise<AssetSummaryGenerateResponse>,

  // 文案审核队列（素材列表点「文案」也走这里）
  listSummaries: (params?: AssetSummaryListParams) =>
    client.get('/assets/summaries', { params }) as Promise<AssetSummaryListResult>,

  // 批量审核：生产者不得自审（admin 除外）、驳回必填理由、改后通过留痕、过审前必须过复核
  reviewSummaries: (data: AssetReviewRequest) =>
    client.post('/assets/summaries/review', data) as Promise<AssetReviewResponse>,

  // 过审文案 → N 条差异化提示词（生产单）；P0 到「生产单可导出」为止，投板是人工动作
  produce: (data: AssetProduceRequest) =>
    client.post('/assets/produce', data) as Promise<AssetProduceResponse>,

  // 投递状态回写：人投完板把真实结果写回台账（只改状态 + 补 board_tid + 记审计，不碰成本）
  updateProductionStatus: (data: AssetProductionStatusRequest) =>
    client.post('/assets/productions/status', data) as Promise<AssetProductionStatusResponse>,

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

  // 素材详情：含全部文案候选、生产单、反推任务与详规正文
  getAsset: (assetId: string) =>
    client.get(`/assets/${assetId}`) as Promise<AssetDetailResponse>,

  // 素材原文件下载（file=自有桶 presigned；link=只回显原始链接，url 为 null）
  downloadAssetSource: (assetId: string) =>
    client.get(`/assets/${assetId}/source-download`) as Promise<AssetSourceDownloadResult>,

  // 单条反推状态刷新并收敛阶段态（直链素材在这里顺带探一次时长，探不到仍是 null）
  refreshAssetPrompt: (assetId: string) =>
    client.post(`/assets/${assetId}/prompt-refresh`) as Promise<AssetPromptRefreshResponse>,

  // 批次列表（含成本预估/实扣，对账页用；只有 items，没有 total）
  listBatches: (params?: { limit?: number }) =>
    client.get('/assets/batches', { params }) as Promise<AssetBatchListResult>,
};

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

/** derive_status 的 12 个派生态（值以 models/asset.py 的 AS_* 为准） */
export const ASSET_STATUS_LABELS: Record<AssetStatus, string> = {
  draft: '草稿',
  importing: '导入中',
  waiting_prompt: '待反推',
  analyzing: '反推中',
  summarizing: '出文案中',
  awaiting_review: '待审核',
  ready_to_produce: '可投产',
  producing: '生产中',
  composing: '拼接中',
  ready: '可交付',
  failed: '失败',
  archived: '已归档',
};

export const AUDIT_STATUS_LABELS: Record<AuditStatus, string> = {
  pending: '待审',
  approved: '已过审',
  rejected: '已驳回',
  need_rewrite: '需改写',
  passed_edited: '改后通过',
};

export const PRODUCTION_STATE_LABELS: Record<ProductionState, string> = {
  order_ready: '待投放',
  queued: '已投上板',
  running: '出片中',
  awaiting_rewrite: '待改写',
  success: '成功',
  failed: '失败',
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
  question: '疑问式',
  statement: '陈述式',
  dialogue: '台词摘录',
};

/** 五段流水线（面板列头 + 详情抽屉共用） */
export const STAGE_FIELDS: Array<[keyof AssetItem, string]> = [
  ['stage_import', '导入'],
  ['stage_prompt', '反推'],
  ['stage_summary', '文案'],
  ['stage_produce', '生产'],
  ['stage_compose', '拼接'],
];

