"""素材库（Asset Library）域 ORM 模型。

按《素材库模块-设计方案-20261103.md》P0 落地：团队每日把网上收集的素材（多平台
分享链接 / 直接视频文件）批量导入，串起「导入 → 反推提示词 → 钩子文案 → 审核 →
生产单 → 合成 → 交付」全链路，每一环可单独重试、可追溯、可对账。

9 张表（P0 建 6 张，11-04 补 categories/jobs/frames 三张）：
- asset_categories   钩子原型字典（11-04 拍板①：单层、原型 A–G 原名、软下线不硬删）
- asset_batches      导入批次（含成本预估/实扣，用于熔断与对账）
- asset_items        素材主表（一行 = 一条素材；批次只是筛选维度，不做父行，
                     批量关系靠 asset_items.batch_id，不建中间表——一批一条没有多对多）
- asset_summaries    钩子文案（1:N 多候选 + 审核态；审核对象就是这张表）
- asset_productions  生产单条目（一条过审文案 × 第 i 个产物 = 一行，N 的 fan-out 单元）
- asset_outputs      产物文件（豆包成片 / 合成成片 / 交付包）
- asset_jobs         后台任务台账（11-04 D-1：出文案/投产/抽帧，提交即回 + 轮询）
- asset_frames       抽帧图（11-04 批 F：审核台卡片与封面图，纯呈现层不参与判定）

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
from typing import Any, Dict, Tuple

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
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

# ─────────────────────────  媒体类型（11-05 批 G）  ─────────────────────────
# 与 `source_kind` **正交**：source_kind 说"怎么进来的"（链接/文件），media_kind 说
# "进来的是视频还是图"。链接口只产 video；文件口两种都有。
# 为什么要单独立一列而不是靠扩展名现判：图片是**生产输入**（角色卡），不参与反推、
# 出文案、拼接、抽帧任何一环——每一环都得先看这一列，用扩展名判断等于把口径散到六处。
MEDIA_VIDEO = "video"
MEDIA_IMAGE = "image"
MEDIA_KINDS = (MEDIA_VIDEO, MEDIA_IMAGE)

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
# 11-09 成稿导入暴露的同一条坑（照 A4-6 的手法再拆一次）：`prompt success + summary pending`
# 以前也派生成 summarizing（界面「出文案中」），但那一步**根本没人提交**。
# 86 条成稿一次进来，队列里几十条写着「出文案中」而实际一条都没跑——和 A4-6 修之前
# 「分不清谁在跑、谁卡着没人管」是同一个病，只是搬到了文案这一环。
# 拆开后：`waiting_summary`＝稿已就位、等你点「出文案」（免费）；`summarizing`＝任务真在跑。
AS_WAITING_SUMMARY = "waiting_summary"
AS_AWAITING_REVIEW = "awaiting_review"
AS_READY_TO_PRODUCE = "ready_to_produce"   # 有过审文案，可开生产单
AS_PRODUCING = "producing"
AS_COMPOSING = "composing"
AS_READY = "ready"                          # 产物齐备，可交付下载
AS_FAILED = "failed"
AS_ARCHIVED = "archived"                       # P0 无归档写入方；去重查询已按它排除，归档口属 P1
# 11-05 批 G：图片素材的**终点态**。图不进反推/文案/生产/拼接四环，派生链走不到任何
# 既有态；若不加这一支，`derive_status` 会一路落到 `waiting_prompt`，列表里每张角色卡
# 都显示「待反推」，看着像几十条卡着没人管的活，实际它们根本不该被提交。
AS_IMAGE_READY = "image_ready"

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
# 建单只写 order_ready（生产单已排好、提示词已按权威模板展开、可导出）。
# queued/running/success/failed 这两个来源**都**能写（11-05 批 H 之后）：
#   ① 人工回写口 `POST /assets/productions/status`（导出 payload → 人去板面投 → 报数）；
#   ② 自动投板 `POST /assets/productions/dispatch`（后端自己连板：建任务落 queued、
#      轮询到非终态落 running、succ＋下载到桶里才落 success，板面 fail 只重启一次再 failed）。
# 两条路的迁移、attempts、阶段收敛共用同一套判据（见 assets.py 的 `_DISPATCH_TRANSITIONS`
# 与 `_converge_produce_stage`），口径不会因为是机器投的就松一档。
# awaiting_rewrite 尚无写入方（改写闭环属 P1）。
PR_ORDER_READY = "order_ready"
PR_QUEUED = "queued"          # 已投上板（人工回写或自动投板写入，attempts 在这里 +1）
PR_RUNNING = "running"        # 板上出片中
PR_AWAITING_REWRITE = "awaiting_rewrite"
PR_SUCCESS = "success"        # 成片到手；completed_at 由回写口/投板协程落
PR_FAILED = "failed"          # 失败/不出片；error 必填（我们侧判读，板上失败行没有原因字段）
PR_CANCELLED = "cancelled"    # 仍无写入方：自动投板做的是"重启一次"而不是"取消"（11-05 口径）；
                              # 列在这里是为了读口能判
PR_SKIPPED = "skipped"      # 被批次熔断挡下（额度/预算），未投递：仍无写入方——熔断本身没做，
                            # 号池余量按用户拍板只提示不拦，所以这条态在 P0/P1 都不会自动产生
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


# ─────────────────────  钩子原型字典（11-04 拍板 ①）  ─────────────────────
# 初始 7 行照《钩子模版换皮参数设定.docx》（投放主流钩子类别及脚本换皮变量）的原型
# A–G **原名录入**——用户明确"我不改词、不加项"，G 在文档里写作「补充：原型 G」，
# 这里去掉"补充："这个段落标记，名称本身一字未动。
# `note` 是文档自带的「钩法内核」原话（D 另加它那行合规要求），**只作行内说明显示，
# 不进任何闸门**：分类是纯人工点选（拍板③），模型侧 `hook_copy.txt` 未改一字。
DEFAULT_ASSET_CATEGORIES: Tuple[Dict[str, Any], ...] = (
    {
        "name": "原型 A：非人物件 / 动物开口说话（报恩·预警·神谕）",
        "sort": 10,
        "note": "钩法内核：温情/无意善举 → 非人角色开口 → 给反直觉预言或指令 → 逼看后续。",
    },
    {
        "name": "原型 B：偷听泄密（获取关键情报）",
        "sort": 20,
        "note": "钩法内核：主角躲在某处摸鱼/藏身 → 意外听到大人物泄密（内部消息/阴谋）→ 得知将改变命运的信息 → 逼看后续。",
    },
    {
        "name": "原型 C：隐藏财富 / 秘境发现（反转爆发）",
        "sort": 30,
        "note": "钩法内核：日常场景 → 触发机关/暗格 → 财富或秘境曝光 → 归属悬念。",
    },
    {
        "name": "原型 D：虐待 / 冲突 / 不公反转（情绪引爆）",
        "sort": 40,
        "note": (
            "钩法内核：弱势者（老人/孕妇/妻）被当众打/推/弃 → 极致不公 → 留一句引爆情绪的台词 → 逼看后续（反转打脸）。"
            "合规（docx 原文要求）：必须加 本故事纯属虚构 + 请勿模仿，肢体冲突尽量侧拍/借位。"
        ),
    },
    {
        "name": "原型 E：超能力 / 异常 / 猎奇（设定反差）",
        "sort": 50,
        "note": "钩法内核：普通表象 → 异常初现 → 设定被点破 → 反差悬念。",
    },
    {
        "name": "原型 F：神力 / 温情 / 绝境反转（其他）",
        "sort": 60,
        "note": "钩法内核：绝境 → 神力介入 → 结果反转 → 爽点悬念。",
    },
    {
        "name": "原型 G：前置故事叙事（口播）",
        "sort": 70,
        "note": "钩法内核：生成一小段前置剧情 + 衔接原剧高光剧情 → 情绪或爽点爆发。",
    },
)


class AssetCategory(Base):
    """钩子原型字典（11-04 拍板 ①：单层字典，素材单选、文案继承）。

    为什么单开一张表，而不是复用已有两根轴：
    - `asset_summaries.formula_tag`（String(60) 自由文本、无字典、全靠模型自觉）是**文字层**
      （首句怎么写），没有字典也就没法筛选；
    - `asset_summaries.style_tag`＝question/statement/dialogue 是**句式层**；
    - 运营要的 A–G 是**结构层**（整条片子四镜怎么排），且要能同时描述"素材视频本身属于哪一类"
      ——所以只有它配当"素材＋文案共用"的那根分类轴。三者并存、不合并、不重叠。
    - 用户明确**不碰 `dramas.tags`**（现网 655 行该列全为 JSON null，是个从没填过的空位），
      也不回填、不共典。

    `parent_id` 按拍板"留着不填"：列先建、恒 NULL，日后要分层不用再动表结构。
    行只做 `active=false` 软下线，**不硬删**——素材/文案上的 category_id 是 FK(SET NULL)，
    真删了会把一线已经点好的分类静默清空。
    """
    __tablename__ = "asset_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 原型名（docx 原名，唯一：种入靠这个键判重）
    name = Column(String(100), unique=True, nullable=False, index=True)
    # 单层字典：列留着不填（11-04 拍板①第 1 条）
    parent_id = Column(UUID(as_uuid=True), ForeignKey("asset_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    # 展示顺序（docx 里 A→G 的次序，列表与下拉都按它排）
    sort = Column(Integer, nullable=False, default=0)
    # 软下线标记：false＝不再供新条目挑选，但历史条目的分类仍显示、仍可筛
    active = Column(Boolean, nullable=False, default=True)
    # 行内说明（docx 的钩法内核原文；纯展示，不参与任何判定）
    note = Column(String(500), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<AssetCategory(name={self.name}, sort={self.sort}, active={self.active})>"


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
    # 媒体类型（11-05 批 G）：video | image。**默认 video，存量行不改语义**。
    # 图片只当生产输入（角色卡），四环闸门都按这一列拒它（见 assets.py `_reject_image`）。
    # **故意不建索引**：只有两个取值、库里 99% 是 video，Postgres 会直接走 seq scan；
    # 更要紧的是 `create_all` 不给已存在的表补索引，现网加列只走 database.py 那张
    # ADD COLUMN 清单，留着 index=True 只会得到一个"以为有索引"的假象。
    media_kind = Column(String(10), nullable=False, default=MEDIA_VIDEO)
    # 文件形态：落自有桶（raw-footage 的 asset/ 前缀），不借智令 temp 桶
    file_name = Column(String(255), nullable=True)
    file_key = Column(String(500), nullable=True)
    bucket = Column(String(50), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    # 批 J（11-05）：反推时把链接素材的**原片**拉回自有桶（用户口径：反推默认顺带下载，
    # 一线回看不用再回源翻直链）。NULL=没有要下的（文件素材本来就在桶里、图片不是视频）；
    # running/success/failed 是**下载动作自己**的状态——刻意不进五阶段：下载是"回看用"
    # 的副本动作，不是流水线的一环，塞进 stage_import 会把「导」这个字的口径搅浑。
    download_status = Column(String(10), nullable=True)

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
    # 时效直链缓存（11-06）：resolve 解析成功后把 play_url + 取链时间落库。
    # 直链是源站的时效链接（约 6 小时），缓存只在 ASSET_PLAY_URL_TTL_HOURS 内免费回放，
    # 过期不作数——resolve 会重新解析（该扣 0.01 扣 0.01），这是「直链失效后自愈」的出口。
    # 之前 play_url 只活在当次响应里，用户付了钱取到的直链一关抽屉就没了，再点也拿不回来。
    play_url = Column(Text, nullable=True)
    play_url_at = Column(DateTime, nullable=True)
    # 反推计时上限（本条实际使用的档位；NULL=未反推）
    prompt_max_duration = Column(Integer, nullable=True)
    # 钩子原型分类（11-04 拍板①）：单层字典、**纯人工点选**、可不填（不设为必填，
    # 但列表页要显示"未分类 N 条"让人看见欠账）。文案侧默认继承本列。
    category_id = Column(UUID(as_uuid=True), ForeignKey("asset_categories.id", ondelete="SET NULL"), nullable=True, index=True)

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
    # 钩子原型分类（11-04 拍板①）：出文案时默认**继承所属素材的 category_id**，
    # 审核台可逐条改；改过要留痕（手法同 `text_before_edit`：改前值进 AuditLog before）。
    # 与上面两根轴并存不合并：style_tag＝句式层、formula_tag＝文字层、本列＝结构层。
    category_id = Column(UUID(as_uuid=True), ForeignKey("asset_categories.id", ondelete="SET NULL"), nullable=True, index=True)
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
    # P1（评审定稿⑩）：改后重提时作者写给审核人的说明（resubmit 口落列，审核卡展示；
    # 此前只进 AuditLog，复审时对不上话）
    resubmit_note = Column(Text, nullable=True)
    # 改后通过的原文留痕（配合 AuditLog 的 before/after，admin 抽检用）
    text_before_edit = Column(Text, nullable=True)

    # 批 J（11-05）：过审后**顺手**把豆包生产提示词展开一遍存下来（预览）。它是「看」的：
    # 让审核人过审那一刻就知道这条文案能不能展开成像样的提示词，而不是等投产才发现。
    # ⚠️ 绝不把它当投产产物用——投产时仍按当时的钩子编号/角色卡/剧名**重新展开**，
    # 一字不抄这里（预览取的是最保守参数，两边抄来抄去迟早抄出一条过期的）。
    prompt_preview = Column(Text, nullable=True)
    prompt_preview_at = Column(DateTime, nullable=True)
    # 展开预览与投产同一模型同一模板，P0 **不单记钱**（投产展开也不单记，口径一致）；
    # 列先立着，将来要对账时不用再动表。
    cost_preview = Column(Float, nullable=False, default=0.0)

    # 11-06 双产出：出文案时每条候选同步带一份**豆包网页版**完整提示词（NAS 模板网页版
    # 裁剪：无段头编号/推荐标题/发布标签，10s/15s 按文案逐条判断）。与 prompt_preview 的
    # 分工：那列是任务板通道的过审后预览（恒 10s、无执行要求行），这列是网页版正文，
    # 出文案时就生成、复制整段进 doubao.com 对话框直接用。NULL=生成失败/未生成
    # （文案本身不受影响），用 POST /assets/summaries/prompt-web 单独补。
    doubao_prompt = Column(Text, nullable=True)

    # 批 N（11-09 用户口径「现有已经导入的那些文案，你都去取一个编号放着吧」）：
    # **预取**好、还没用掉的钩子编号。为什么要在文案上存一份：取号是「一发即烧」的
    # 外部动作（hook_id.py 写共享台账），过去只能在开单那一屏现取现贴，一线慢一步
    # 就得回头再取；批量导入的 85 条更是每条都得手动粘。现在号先钉在文案上等着，
    # 开单时后端自动顶上去（见 `create_productions` 的 parked_code），顶掉就当场清空
    # ——不清空就等于允许同一个号被第二次开单复用，而拍板③ 明确禁止（一钩一号，
    # 已用号在 `asset_productions` 那侧当场 400）。NULL＝没预取 / 已被某张单吃掉。
    hook_code = Column(String(10), nullable=True)

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
    # 批 L（11-06 投放进度可视化）：板子侧状态写回。自动投板的后台协程每 45s 回读一轮
    # 板面，把看到的行状态（waiting/running/succ…）连同检查时间钉在生产单行上——
    # 不写回的话投放后界面只能停在「投放中」干等，看不出板子在排队还是真在出片。
    # 全部可空不回填：没投过板的单/老单＝NULL，语义就是「没有板侧信息」。
    board_last_status = Column(String(60), nullable=True)
    board_last_check_at = Column(DateTime, nullable=True)
    character_card_key = Column(String(500), nullable=True)    # 旧：单张卡的 MinIO key（前端手填那条野路子的存证）→ 板上 picDatas 的回退来源
    # 批 G（11-05 拍板③）：**多卡保序**。存 asset_items.id 字符串数组，
    # 顺序＝板上 `picDatas` 数组顺序（一部剧多张定妆照时，谁是第一张谁就是主形象）。
    # 与上一列的分工：这一列是**正路**（挑图口写它，能按 id 回溯到素材行、量过尺寸），
    # `character_card_key` 是**历史**（旧前端手填 MinIO key 那条野路子的唯一存证）。
    # 读侧永远「有数组用数组、没数组回退单值」——存量单不许因为加了新列就丢卡，
    # 那条卡是花钱传上来的（见 `_card_sources_for`）。JSON 而非 UUID[]：sqlite 也认，
    # 且这里从不按卡 id 反查生产单（要反查得走 jsonb 包含算子，PG 才有），没索引可谈。
    card_asset_ids = Column(JSON, nullable=True)

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
    # production_id 可空（11-04 改）：拼接产物是「两段视频拼一条」，用户明确要求
    # 第二段可以来自素材库另一条 / 现网切片产物 / 本地上传，**不必挂生产单**。
    # 原先 NOT NULL 会逼着每次拼接先造一条生产单——那是造台账噪音，不是业务。
    # 生产单派生的产物照旧带上 production_id，列表与成本口径不变。
    production_id = Column(UUID(as_uuid=True), ForeignKey("asset_productions.id", ondelete="CASCADE"), nullable=True, index=True)
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


# ──────────────────────────────────────────────
# 抽帧（11-04 批 F：审核台卡片与封面图，纯呈现层）
# ──────────────────────────────────────────────

FRAME_THUMB = "thumb"                 # 单张缩略帧（一条素材 3 张，卡片左侧横排）
FRAME_GRID = "grid"                   # 九宫格（一张图 3×3 tiled，点开看整片节奏）
FRAME_OUTPUT_THUMB = "output_thumb"   # 产物自己的第 1 帧（豆包成片／拼接成片）
ASSET_FRAME_KINDS = (FRAME_THUMB, FRAME_GRID, FRAME_OUTPUT_THUMB)


class AssetFrame(Base):
    """一条素材/产物的抽帧图。

    ⚠️ **纯呈现层，不参与任何业务判定**：审核过不过、风险词命不命中、一致性判不判得过，
    全都不看这张表。它存在的唯一理由是——一线审文案时只能读字，读不出"这条片子
    到底是不是那个画面"，抽三帧挂到卡片上就能。所以：

    - 抽不出来（链接素材桶里没文件、ffmpeg 失败、片子长过 `ASSET_FRAME_MAX_SOURCE_SECONDS`）
      **不报错、不拦任何步骤**，卡片显示"没有预览图"就完了；
    - 也不写 AuditLog：翻卡片看图不是交付动作，记进去只会把审计页淹掉。

    幂等键是**两条部分唯一索引**，不是一条 `UniqueConstraint(asset_id, kind, seq)`：
    后者会把产物的帧撞死——一条素材拼过 3 版就有 3 个产物，它们全都要占
    `(asset_id, 'output_thumb', 0)` 这一个键（每版产物只抽 1 张首帧，seq 都是 0）。
    所以按「挂在哪」分两把锁：素材级帧看 `(asset_id, kind, seq)`、产物级帧看
    `(output_id, kind, seq)`，两边各自幂等。重投同一条素材（upload/retry／手动重抽）
    走"先删同键旧行再插"覆盖，不会长出第二份帧。
    """
    __tablename__ = "asset_frames"
    __table_args__ = (
        Index(
            "uq_asset_frames_asset_kind_seq",
            "asset_id", "kind", "seq",
            unique=True,
            postgresql_where=text("output_id IS NULL"),
            sqlite_where=text("output_id IS NULL"),
        ),
        Index(
            "uq_asset_frames_output_kind_seq",
            "output_id", "kind", "seq",
            unique=True,
            postgresql_where=text("output_id IS NOT NULL"),
            sqlite_where=text("output_id IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 帧一定挂在素材上（thumb/grid）；output_thumb 挂产物时 asset_id 同样必填——
    # 不然「按素材取卡片图」这一条查询要分两条路径走，前端多判一次空。
    asset_id = Column(UUID(as_uuid=True), ForeignKey("asset_items.id", ondelete="CASCADE"), nullable=False, index=True)
    output_id = Column(UUID(as_uuid=True), ForeignKey("asset_outputs.id", ondelete="CASCADE"), nullable=True, index=True)
    kind = Column(String(20), nullable=False, index=True)
    seq = Column(Integer, nullable=False, default=0)        # 同 kind 内第几张（grid 恒 0）
    # 这一帧取自原片第几秒；九宫格取整片中段那帧的时间点，探不到就留 NULL
    t_offset = Column(Float, nullable=True)
    file_key = Column(String(500), nullable=False)
    bucket = Column(String(50), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    # 抽帧当时读的是桶里哪个对象：回头查"帧和视频对不上"不用猜（重导过就是新 key）
    source_file_key = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<AssetFrame(asset={self.asset_id}, kind={self.kind}, seq={self.seq})>"


# ──────────────────────────────────────────────
# 后台任务（D-1 队列化：出文案 / 投产 提交即回 + 轮询）
# ──────────────────────────────────────────────

JOB_SUMMARY_GENERATE = "summary_generate"
JOB_PRODUCE = "produce"
# 批 F：抽帧也是活，但它是**导入成功后系统自己排的**，不是人点的慢活——
# 所以 `GET /assets/jobs` 默认不列它（见 list_asset_jobs），任务横幅才不会被人人都有的
# 抽帧任务把「我刚才点的那批还在不在跑」挤出视野。
JOB_FRAMES = "frames"
# 批 H（11-05）：投板。它是这三类里**唯一会往外花钱/花号池额度**的活，所以
# ① 权限跟 `_REVIEW_ROLES`（与建单/投产/回写同一侧）；② 必须带 `confirm=true`
# （P0 拍板口径「可自动投板，但逐批人工确认」）；③ 一个 job 里包含"建任务＋轮询＋
# 回收下载"整段，跑几十分钟，同步等必然顶穿超时链——只能走这里。
JOB_DISPATCH = "dispatch"
# 批 J（11-05）新增两类，都是「跟着主动作顺手排」的分钟级慢活，同步等必然顶穿超时链：
# - download：反推提交后把链接素材原片拉回自有桶（拉流下载，一条几十秒到几分钟）；
# - prompt_preview：文案过审后把豆包提示词展开一遍存起来（模型 90~150s/条）。
# 两者都复用 D-1 同一套台账/防重复/进度口径，不另造机制。
JOB_DOWNLOAD = "download"
JOB_PROMPT_PREVIEW = "prompt_preview"
# 11-06 用户三连投诉后升级为正式任务：反推提交后**收敛只靠前端轮询**（页面一关就没人收，
# 状态永远「反推中」、失败看不见也没法重试）。JOB_ANALYZE = 提交 + 后台原地等收敛 +
# 快速失败自动重试一次，与出文案同一套台账/防重复/进度口径，不另造机制。
JOB_ANALYZE = "analyze"
ASSET_JOB_KINDS = (JOB_SUMMARY_GENERATE, JOB_PRODUCE, JOB_FRAMES, JOB_DISPATCH, JOB_DOWNLOAD, JOB_PROMPT_PREVIEW, JOB_ANALYZE)

JB_QUEUED = "queued"          # 已落库、协程已排上，还没开跑
JB_RUNNING = "running"        # 正在逐条调模型（开始跑时落一次 started_at，跑中间不回报心跳）
JB_SUCCEEDED = "succeeded"    # 整批跑完（**个别条失败也算跑完**，明细在 result 里）
JB_FAILED = "failed"          # 整批没跑成（编排自身炸了，不是单条失败）
JB_INTERRUPTED = "interrupted"  # 进程重启把在跑的协程带走了：结果不可信，人工重试


class AssetJob(Base):
    """素材库的「慢活」台账：一条 = 一次后台批量出文案 / 批量投产。

    为什么要有这张表（11-04 第二轮审核 D-1）：出文案与投产是**同步等模型**的
    （单条 ~95s，一批 10 条串跑就是 15 分钟），一线只能靠浏览器干等。四层超时
    （nginx 3600s > 前端 960s > 后端单条 900s > autoclip 600s）只保证"不被半路掐"，
    不保证"人敢点"：刷新页面、切走标签、网关抖动，一次 15 分钟的等待就白扔，
    而钱和号池编号在那一次已经花掉了。所以：提交即回一个 job_id，前端轮询台账。

    ⚠️ 这不是 Celery 队列，是**同进程 asyncio 后台任务 + 数据库台账**：
    现网 backend 跑 `--workers 1`，也没有任何 celery worker 订阅素材库队列，
    真上 Celery 要新队列、新 worker、新部署件，属 P1。这里刻意只做三件事——
    ① 提交当场落库并回 job_id；② 结果整份存进 `result`（含逐条明细），
    刷新页面/换浏览器都还查得到；③ 进程重启时把 queued/running 一律标
    `interrupted`（协程没了，结果不可信，绝不假装还在跑）。
    多 worker 部署时 `running` 只代表"某个 worker 认为它在跑"，别当分布式锁用。

    `params` 存的是**原请求体**（含 `waive_reason` / `waive_codes` 这类豁免入参）：
    重放与追溯必须走一模一样的闸门口径，否则"后台再跑一次"就把 admin 的豁免理由丢了，
    或反过来把一次没豁免的提交偷偷变成永久豁免。
    """
    __tablename__ = "asset_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(String(30), nullable=False, index=True)
    status = Column(String(20), nullable=False, default=JB_QUEUED, index=True)
    # 归属批次（整批排队时才有；按 id 列表提交时为 NULL，靠 params 里的 asset_ids 追溯）
    batch_id = Column(UUID(as_uuid=True), ForeignKey("asset_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    params = Column(JSON, nullable=False, default=dict)
    # 整份接口响应（results/queue/message/…）。跑完才有；跑废了则为已拿到的部分或 NULL
    result = Column(JSON, nullable=True)
    error = Column(String(1000), nullable=True)
    # 计划/完成条数：提交时按请求体算一次，读取时按台账现算一次（见 API 里的 progress 口径）
    planned_units = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<AssetJob(kind={self.kind}, status={self.status}, batch={self.batch_id})>"
