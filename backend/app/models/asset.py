"""素材库（Asset Library）域 ORM 模型。

按《素材库模块-设计方案-20261103.md》P0 落地：团队每日把网上收集的素材（多平台
分享链接 / 直接视频文件）批量导入，串起「导入 → 反推提示词 → 钩子文案 → 审核 →
生产单 → 合成 → 交付」全链路，每一环可单独重试、可追溯、可对账。

5 张表：
- asset_batches      导入批次（含成本预估/实扣，用于熔断与对账）
- asset_items        素材主表（一行 = 一条素材；批次只是筛选维度，不做父行，
                     批量关系靠 asset_items.batch_id，不建中间表——一批一条没有多对多）
- asset_summaries    钩子文案（1:N 多候选 + 审核态；审核对象就是这张表）
- asset_productions  生产单条目（一条过审文案 × 第 i 个产物 = 一行，N 的 fan-out 单元）
- asset_outputs      产物文件（豆包成片 / 合成成片 / 交付包）

设计取舍（与设计方案一致，改动前先读）：
1. 挂主系统 `app.database.Base`（不是 WechatDownloadBase）：data_scope 隔离、AuditLog、
   RBAC 四角色、钩子拼接（SliceTask）全在主系统域；wechat_download 的"独立 Base"只是
   剥离装饰（其 base.py 已说明同库同 PG 实例、由主 alembic 建表），跨 Base 建
   relationship 会踩 mapper 未注册。依赖方向单向 app → wechat_download。
2. **5 个阶段字段 + 1 个派生 status**，不压成一个字段：单字段表达不了"文案 3 条已过审、
   生产 7/10 成功"，且重试没有落点——每一环都是真金白银（反推按计时上限扣费），
   整链重跑等于重复烧钱。派生口径见 `asset_service.derive_status`。
3. 成片**不落 SliceOutput**：该表 task_id NOT NULL 且 FK→slice_tasks，硬塞要造假 SliceTask。
4. 生产环节 P0 只到"生产单"（N 条差异化提示词 + 可导出投放 payload），**自动**投递属 P1；
   但投递**状态**在 P0 就有落点（11-03 拍板第 4 条）：人投完板用 `POST /assets/productions/status`
   回写 queued/running/success/failed，列表侧给「投了多少、成多少、败多少」——号池不做硬限，
   只报数。没有这个口，库里永远只有 order_ready，对账页回答不了"昨天那 120 条到手几条"。
   通道 = 企微自动化后台「创建 AI 视频」任务板（`wework_aivideo`，不扣现金、成片恒
   10.08s/720×1280、payload 七键），**不是**火山方舟 Seedance 官方 API，也不走豆包网页 RPA。
   P1 前置仍是队列拆分：`seedance_generate_task` 现在与视频号发布抢同一个 `--concurrency=1`
   的 publish 队列（设计方案 §5.1），不拆队列开批量接口生产＝自毁发布。
   方案 §5.3（同账号多 tab / per-account 锁 / 链式派发）随通道裁决**作废**——那是 CDP/DOM 的坑。
5. **不在 `wechat_dl_prompt_tasks` 上加 material_id 列**：P0 的反推是素材库侧主动建任务、
   主动按 `asset_items.prompt_task_id` 轮询，豆包文案侧不需要反查素材；往别人域的表加一列
   没人写就是死列（而且部署只 stamp，加列只能靠 compat 清单，多一处维护点）。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


def gen_asset_code() -> str:
    """素材可读唯一 ID：AS-<8位大写HEX>（沿用剧目 code=DR-<8HEX> 的运营可读约定）。"""
    return "AS-" + uuid.uuid4().hex[:8].upper()


def gen_batch_code() -> str:
    """批次可读唯一 ID：AB-<8位大写HEX>。"""
    return "AB-" + uuid.uuid4().hex[:8].upper()


# ─────────────────────────  来源形态  ─────────────────────────
SOURCE_LINK = "link"   # 多平台分享链接（30+ 平台，走智令 doc/107 解析）
SOURCE_FILE = "file"   # 直接视频文件（落自有 MinIO 桶，不借智令 temp 桶——6 小时自删）
SOURCE_KINDS = (SOURCE_LINK, SOURCE_FILE)

# ─────────────────────────  阶段状态（5 段共用）  ─────────────────────────
STAGE_PENDING = "pending"
STAGE_RUNNING = "running"
STAGE_SUCCESS = "success"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"
STAGE_STATES = (STAGE_PENDING, STAGE_RUNNING, STAGE_SUCCESS, STAGE_FAILED, STAGE_SKIPPED)

# 阶段名（asset_items 上的列名，也是 API 的 stage 取值）
STAGES = ("import", "prompt", "summary", "produce", "compose")

# ─────────────────────────  素材派生状态  ─────────────────────────
AS_DRAFT = "draft"
AS_IMPORTING = "importing"
# A4-6 拆态：`analyzing`=反推任务**已在智令侧跑**，`waiting_prompt`=导入完成但**还没提交反推**。
# 旧口径两者都派生成 analyzing，一线看列表分不清「谁在跑」和「谁卡着没人管」，
# 200 条的队列里这一下就是几十条白等。
AS_ANALYZING = "analyzing"
AS_WAITING_PROMPT = "waiting_prompt"
AS_SUMMARIZING = "summarizing"
AS_AWAITING_REVIEW = "awaiting_review"
AS_READY_TO_PRODUCE = "ready_to_produce"   # 有过审文案，可开生产单
AS_PRODUCING = "producing"
AS_COMPOSING = "composing"
AS_READY = "ready"                          # 产物齐备，可交付下载
AS_FAILED = "failed"
AS_ARCHIVED = "archived"                       # P0 无归档写入方；去重查询已按它排除，归档口属 P1

# ─────────────────────────  钩子文案审核态  ─────────────────────────
RV_PENDING = "pending"
RV_APPROVED = "approved"
RV_REJECTED = "rejected"
RV_NEED_REWRITE = "need_rewrite"
RV_PASSED_EDITED = "passed_edited"   # 审核人改后通过（必须 before/after 留痕 + admin 抽检）
REVIEW_STATES = (RV_PENDING, RV_APPROVED, RV_REJECTED, RV_NEED_REWRITE, RV_PASSED_EDITED)
# 可以发起豆包生产的审核态
REVIEW_PASSED_STATES = (RV_APPROVED, RV_PASSED_EDITED)

# ─────────────────────────  钩子文案候选风格  ─────────────────────────
STYLE_QUESTION = "question"     # 疑问式
STYLE_STATEMENT = "statement"   # 陈述式
STYLE_DIALOGUE = "dialogue"     # 台词摘录式
HOOK_STYLES = (STYLE_QUESTION, STYLE_STATEMENT, STYLE_DIALOGUE)

# ─────────────────────────  生产单状态  ─────────────────────────
# 建单只写 order_ready（生产单已排好、提示词已按权威模板展开、可导出）；
# queued/running/success/failed 由人**显式回写**（`POST /assets/productions/status`，
# 11-03 拍板第 4 条），P0 没有自动投递所以这四个态只能来自报数；
# awaiting_rewrite 尚无写入方（改写闭环属 P1）。
PR_ORDER_READY = "order_ready"
PR_QUEUED = "queued"          # 已投上板（回写口写入，attempts 在这里 +1）
PR_RUNNING = "running"        # 板上出片中
PR_AWAITING_REWRITE = "awaiting_rewrite"
PR_SUCCESS = "success"        # 成片到手；completed_at 由回写口落
PR_FAILED = "failed"          # 失败/不出片；error 必填（我们侧判读，板上失败行没有原因字段）
PR_CANCELLED = "cancelled"    # P0 无写入方（取消投递是 P1 队列的活）；列在这里是为了读口能判
PR_SKIPPED = "skipped"      # 被批次熔断挡下（额度/预算），未投递：P0 无写入方，P1 投递侧才产出
PR_SUPERSEDED = "superseded"  # 文案被撤销过审后作废的旧单：不许导出、不许投递（A2-2）
PRODUCTION_STATES = (
    PR_ORDER_READY, PR_QUEUED, PR_RUNNING, PR_AWAITING_REWRITE,
    PR_SUCCESS, PR_FAILED, PR_CANCELLED, PR_SKIPPED, PR_SUPERSEDED,
)
# 还能对外交付的状态：superseded/cancelled/skipped/failed 一律禁导出
# （failed 禁的是「把失败单再投一遍」，重投请显式回到 queued）
EXPORTABLE_PRODUCTION_STATES = (
    PR_ORDER_READY, PR_QUEUED, PR_RUNNING, PR_AWAITING_REWRITE, PR_SUCCESS,
)

# 生产通道：与 ShortdramaPrompt.gen_channel 保持同一套取值，便于跨模块对账
# wework_aivideo = 企微自动化后台「创建 AI 视频」任务板（http://mp.miwan.synology.me:8500）
#   —— 素材库 P0/P1 走的**就是这条**（2026-11-03 用户裁决：产能不限，走自己的接口，
#   不要用 codex 控制网页）。它不是火山方舟 Seedance 官方 API：payload 只有七个键、
#   不扣现金、成片恒 10.08s / 720×1280，详见下方 board_* 列注。
CH_WEWORK_AIVIDEO = "wework_aivideo"
CH_DOUBAO_RPA = "doubao_rpa"        # deprecated：网页 RPA 线仍在别处跑，素材库不走它
CH_SEEDANCE_API = "seedance_api"    # 保留取值，素材库暂不用（方舟按秒计费那条通道与本模块无关）
PRODUCTION_CHANNELS = (CH_WEWORK_AIVIDEO, CH_DOUBAO_RPA, CH_SEEDANCE_API)
# 素材库默认通道
DEFAULT_PRODUCTION_CHANNEL = CH_WEWORK_AIVIDEO


class AssetBatch(Base):
    """导入批次：批量动作的成本与熔断落点。

    预估计费口径（反推按**计时上限**扣费、不是按视频实际时长，这是最大的烧钱杠杆）：
    单条 ≈ 0.00054×max_duration + 0.01(解析，链接需入库时) [+0.1 文案提取可选]。
    实扣在终态回填，供与智令账单逐条对账。
    """
    __tablename__ = "asset_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(20), unique=True, nullable=False, index=True, default=gen_batch_code)
    name = Column(String(200), nullable=True)
    source_kind = Column(String(10), nullable=False, default=SOURCE_LINK, index=True)
    item_count = Column(Integer, nullable=False, default=0)
    # 本批反推计时上限（秒）：整批统一，落库便于对账
    prompt_max_duration = Column(Integer, nullable=True)
    # 成本：预估 / 实扣（元），以及本批预算上限（NULL=用全局默认）
    cost_estimate = Column(Float, nullable=True)
    cost_actual = Column(Float, nullable=True)
    budget_cap = Column(Float, nullable=True)
    # 熔断标记（超预算/余额不足时 blocked，附原因）
    budget_gate = Column(String(20), nullable=True)
    budget_note = Column(String(500), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    items = relationship(
        "AssetItem", back_populates="batch", cascade="all", order_by="AssetItem.created_at"
    )

    def __repr__(self) -> str:
        return f"<AssetBatch(code={self.code}, items={self.item_count})>"


class AssetItem(Base):
    """素材主表：一行 = 一条素材（链接或文件），列表页的主粒度。

    去重键是 `source_url_norm`（归一化链接，见 asset_service.normalize_source_url）。
    **不加库级唯一索引**：同一素材被不同人重复导入是常态，业务上要"提示 + 允许强制重复"，
    不是硬拒；所以走查询命中 + 确认放行的口径。
    """
    __tablename__ = "asset_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(20), unique=True, nullable=False, index=True, default=gen_asset_code)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("asset_batches.id", ondelete="SET NULL"), nullable=True, index=True)

    # 来源
    source_kind = Column(String(10), nullable=False, default=SOURCE_LINK, index=True)
    source_url = Column(String(2000), nullable=True)
    source_url_norm = Column(String(2000), nullable=True, index=True)   # 归一化去重键
    platform = Column(String(40), nullable=True, index=True)            # 归一化识别出的平台
    # 文件形态：落自有桶（raw-footage 的 asset/ 前缀），不借智令 temp 桶
    file_name = Column(String(255), nullable=True)
    file_key = Column(String(500), nullable=True)
    bucket = Column(String(50), nullable=True)
    file_size = Column(BigInteger, nullable=True)

    # 与主系统既有产线的挂接（全部可空，导入是渐进的）
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True, index=True)
    # 反推提示词任务（wechat_dl_prompt_tasks.id，跨 Base 只存 id 不建 relationship）
    prompt_task_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # 素材元信息
    title = Column(String(500), nullable=True)
    cover_image_key = Column(String(500), nullable=True)
    duration = Column(Float, nullable=True)
    resolution = Column(String(50), nullable=True)
    # 反推计时上限（本条实际使用的档位；NULL=未反推）
    prompt_max_duration = Column(Integer, nullable=True)

    # 5 个阶段态（列名 stage_<阶段>，取值见 STAGE_STATES）
    stage_import = Column(String(20), nullable=False, default=STAGE_PENDING)
    stage_prompt = Column(String(20), nullable=False, default=STAGE_PENDING)
    stage_summary = Column(String(20), nullable=False, default=STAGE_PENDING)
    stage_produce = Column(String(20), nullable=False, default=STAGE_PENDING)
    stage_compose = Column(String(20), nullable=False, default=STAGE_PENDING)
    # 派生态（由 5 个阶段重算，见 asset_service.derive_status；冗余存列供列表筛选/索引）
    status = Column(String(30), nullable=False, default=AS_DRAFT, index=True)

    # 审核概要：本条是否有过审文案（列表筛选高频用，避免每次 join）
    has_approved_copy = Column(Boolean, nullable=False, default=False)

    # 成本（元）：反推/解析/文案提取 实扣，与生产消耗分列
    cost_prompt = Column(Float, nullable=False, default=0.0)
    cost_produce = Column(Float, nullable=False, default=0.0)
    # D-5（11-03 拍板：解析费计入批次成本）：doc/107 每次 0.01 元，只在**真给了付费渠道**时记，
    # 走 yuanbao/preview 这类免费兜底记 0——否则对账页会看见一笔从没发生的钱。
    cost_parse = Column(Float, nullable=False, default=0.0)

    note = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    batch = relationship("AssetBatch", back_populates="items")
    summaries = relationship(
        "AssetSummary", back_populates="asset", cascade="all, delete-orphan",
        order_by="AssetSummary.seq",
    )
    productions = relationship(
        "AssetProduction", back_populates="asset", cascade="all, delete-orphan",
        order_by="AssetProduction.seq",
    )

    def __repr__(self) -> str:
        return f"<AssetItem(code={self.code}, status={self.status})>"


class AssetSummary(Base):
    """钩子文案（=用户所说"概要文案"）：1:N 多候选，审核对象就是这张表。

    为什么要候选：详略/句式不同的三条里，通常只有一条能钩人；三选一比"生成一条直接过"
    的返工率低得多（口径见设计方案 §2，与 short-drama-hook-writer 的钩子规矩对齐）。
    `is_recommended` 由模型标注，审核页默认只批量放推荐条，防"橡皮章式全过"。
    """
    __tablename__ = "asset_summaries"
    __table_args__ = (
        UniqueConstraint("asset_id", "seq", name="uq_asset_summary_seq"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("asset_items.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False, default=1)
    text = Column(Text, nullable=False)
    style_tag = Column(String(20), nullable=True)          # question/statement/dialogue
    formula_tag = Column(String(60), nullable=True)        # 命中的爆款公式（防同质化用）
    word_count = Column(Integer, nullable=True)            # 含标点不含空格
    is_recommended = Column(Boolean, nullable=False, default=False)
    # 一致性校验：文案里的实体是否能在反推脚本中命中（防反推失败却"像模像样"地编）
    consistency_ok = Column(Boolean, nullable=True)
    consistency_note = Column(String(300), nullable=True)
    risk_hit = Column(String(500), nullable=True)          # 风险词命中 `词|block,词|warn`（NULL=干净；block 拦过审/投产，warn 只预警）

    audit_status = Column(String(20), nullable=False, default=RV_PENDING, index=True)
    reviewed_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    reject_reason = Column(String(500), nullable=True)     # 驳回必填
    # 改后通过的原文留痕（配合 AuditLog 的 before/after，admin 抽检用）
    text_before_edit = Column(Text, nullable=True)

    source_prompt_task_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    asset = relationship("AssetItem", back_populates="summaries")
    productions = relationship(
        "AssetProduction", back_populates="summary", cascade="all", order_by="AssetProduction.seq"
    )

    def __repr__(self) -> str:
        return f"<AssetSummary(asset={self.asset_id}, seq={self.seq}, audit={self.audit_status})>"


class AssetProduction(Base):
    """生产单条目：一条过审文案 × 第 i 个产物 = 一行（N 的 fan-out 单元）。

    N 的语义（2026-11-03 定）= 同一条过审文案派生 **N 条差异化提示词**，不是重复投喂
    同一条——重复投喂产物近似且白烧额度。差异来源记在 `variant_basis`。

    ⚠️ **N 与板上 `total` 是两个量，混用会一次白烧 N×N**（B-1）：
    板上 `total` = 同一条 prompt 出 N 版（后台给每版派不同豆包号），所以
    「一批 N 份差异化」= **N 个任务、每个 `board_total=1`**；想"一条出 2~3 版挑最好"
    是另一个口径（09-09 定过），用 `board_total` 表达，接口层 min1/max20。

    `prompt_snapshot` 在过审发起生产时冻结，展开出的提示词按 `judge_drift`（A3-3）比对：
    归一后必须**唯一命中且前后不粘字**——前面被拼半句、整句塞进括号、原句复制两遍，
    都算"审的≠生产的"，标 `drift=true` 并把成因写进 `drift_reason`，不静默。

    board_* 六列 = 与企微后台 AI 视频任务板对账的主键（B-2/B-3/B-5）。板上失败行**没有
    原因字段**，`error` 只能记我们侧的判读，别当成豆包给的成因。

    投递台账（`status`/`error`/`attempts`/`started_at`/`completed_at`/`board_tid`）**不加新列**：
    11-03 拍板第 4 条要的「投了多少、成多少、败多少」全部由这几列 + 回写口
    （`POST /assets/productions/status`）算出来，写口受状态迁移表约束并逐条留审计。
    """
    __tablename__ = "asset_productions"
    __table_args__ = (
        UniqueConstraint("summary_id", "seq", name="uq_asset_production_seq"),
        UniqueConstraint("idempotency_key", name="uq_asset_production_idem"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("asset_items.id", ondelete="CASCADE"), nullable=False, index=True)
    summary_id = Column(UUID(as_uuid=True), ForeignKey("asset_summaries.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("asset_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    seq = Column(Integer, nullable=False, default=1)

    # 提示词（按 NAS《豆包文案生成模板与规则.md》11-02 版展开的成品提示词）
    hook_code = Column(String(10), nullable=True)           # 五位钩子编号：段头/推荐标题/产出清单三处必须带
    project_title = Column(String(300), nullable=True)      # 废弃：11-02 版「1020 起项目标题行已取消」，列留着不再写入
    prompt_text = Column(Text, nullable=True)               # 只含**可投给模型的正文**（B-9）
    dispatch_note = Column(Text, nullable=True)             # 改名/跳过二次确认/并行等投放要求：只给人看，绝不进 payload
    prompt_snapshot = Column(Text, nullable=True)           # 过审文案快照
    video_titles = Column(JSON, nullable=True)              # 推荐视频标题（条数=该剧发布号数 K，非固定 5）
    variant_basis = Column(String(120), nullable=True)      # 本条与同批其它条的差异来源
    drift = Column(Boolean, nullable=False, default=False)
    # 漂移成因（A3-3）：judge_drift 判的就是"怎么不像同一条"，光一个 bool 前端没法显示
    drift_reason = Column(String(500), nullable=True)

    duration = Column(Integer, nullable=True)               # 意图字段（B-4）：板上无时长开关，成片恒 10.08s；>10s 只能拆上下集两条
    channel = Column(String(20), nullable=True)             # wework_aivideo（默认）/ doubao_rpa / seedance_api
    account_id = Column(UUID(as_uuid=True), nullable=True, index=True)    # 保留列、P0 起不接受前端传（接口通道由后台派号）
    browser_port = Column(Integer, nullable=True)                          # 同上：CDP 时代遗留，接口通道不存在端口

    # ── 后台任务板对账字段（B-2/B-3/B-5）──
    board_total = Column(Integer, nullable=False, default=1)   # 同一提示词要几版（板上 total，1..20）；与 N 分列
    board_tag = Column(String(60), nullable=True, index=True)  # 拥有者标记；不填=无主任务，按天筛不到
    board_date = Column(DateTime, nullable=True, index=True)    # 建任务时**由后端生成**的完整时间戳；只写日期会「succ 但永久查不到」
    board_name = Column(String(200), nullable=True)            # 板上 name = 推荐视频标题第 1 条（剥非法字符、≤60 码点）
    board_tid = Column(String(60), nullable=True, index=True)  # 回读主键（info?date= 返回）
    board_rgid = Column(String(60), nullable=True)             # 回收组 id，拼 /data<outUrl> 用
    character_card_key = Column(String(500), nullable=True)    # 角色卡（自有桶 key）→ 板上 picDatas 的来源，数组顺序＝上传顺序

    status = Column(String(30), nullable=False, default=PR_ORDER_READY, index=True)
    provider_task_id = Column(String(100), nullable=True)
    celery_task_id = Column(String(100), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    # 幂等键：防同一文案同一序号被重复投递（重试新增 attempt 行，不改原行）
    idempotency_key = Column(String(120), nullable=True)
    error = Column(String(500), nullable=True)
    cost = Column(Float, nullable=True)                    # 额度类消耗记 0，成本走号池
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    asset = relationship("AssetItem", back_populates="productions")
    summary = relationship("AssetSummary", back_populates="productions")
    outputs = relationship(
        "AssetOutput", back_populates="production", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AssetProduction(summary={self.summary_id}, seq={self.seq}, status={self.status})>"


class AssetOutput(Base):
    """产物文件：豆包成片 / 合成成片 / 交付包。

    ⚠️ 不复用短片制作那条"新片上传成功即删旧片"的逻辑（shortdrama_tasks.py:172-178），
    批量重投会互踩、丢历史产物，所以每条产物一行、永不覆盖。
    验收结论存 `qc_result`（JSON），**不合格不得入交付包**（不静默）。
    """
    __tablename__ = "asset_outputs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    production_id = Column(UUID(as_uuid=True), ForeignKey("asset_productions.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("asset_items.id", ondelete="CASCADE"), nullable=False, index=True)
    # 产物类型：doubao_raw（豆包原片）/ composed（拼接成片）/ package（交付包 zip）/ copy（文案 txt）
    kind = Column(String(20), nullable=False, default="doubao_raw", index=True)
    file_key = Column(String(500), nullable=True)
    bucket = Column(String(50), nullable=True)
    file_name = Column(String(255), nullable=True)
    duration = Column(Float, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    resolution = Column(String(50), nullable=True)
    sha256 = Column(String(64), nullable=True)
    # 后台任务板回读的 outUrl（拼 GET /data<outUrl> 下载用；B-3）
    board_out_url = Column(String(500), nullable=True)
    # 钩子来源（拼接成的成片记录用了哪个 production 的素材，一对多追溯）
    hook_production_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    qc_status = Column(String(20), nullable=True)          # passed / warn / failed / NULL=未验
    qc_result = Column(JSON, nullable=True)                # 各项判据与证据（采样密度记在里面）
    qc_note = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    downloaded_at = Column(DateTime, nullable=True)
    expires_on = Column(Date, nullable=True)               # 交付包类临时产物的清理日

    production = relationship("AssetProduction", back_populates="outputs")

    def __repr__(self) -> str:
        return f"<AssetOutput(asset={self.asset_id}, kind={self.kind}, qc={self.qc_status})>"
