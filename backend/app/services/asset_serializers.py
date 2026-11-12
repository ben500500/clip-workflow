"""素材库序列化器（2026-11-13 臃肿度席外移：零行为变化纯剪切）。

从 api/assets.py 外移的 5 个纯序列化函数——只依赖 ORM 模型字段与 utc_iso，
不碰 db、不读 settings。god file 减行第一步（其余外移组见后续提交）。
"""
from typing import Any, Dict, Optional

from app.models.asset import AssetBatch, AssetCategory, AssetItem, AssetProduction, AssetSummary
from app.utils.helpers import utc_iso


def _serialize_batch(b: AssetBatch) -> dict:
    return {
        "id": str(b.id),
        "code": b.code,
        "name": b.name,
        "source_kind": b.source_kind,
        "item_count": b.item_count,
        "prompt_max_duration": b.prompt_max_duration,
        "cost_estimate": b.cost_estimate,
        "cost_actual": b.cost_actual,
        "budget_cap": b.budget_cap,
        "budget_gate": b.budget_gate,
        "budget_note": b.budget_note,
        "created_at": utc_iso(b.created_at),
    }



def _serialize_item(a: AssetItem, agg: Optional[dict] = None) -> dict:
    data = {
        "id": str(a.id),
        "code": a.code,
        "batch_id": str(a.batch_id) if a.batch_id else None,
        "source_kind": a.source_kind,
        # 批 G：前端按这一列分流（图片走"角色卡"卡片、视频走播放器），并据此隐藏
        # 「反推/出文案/拼接」入口。存量行由 ADD COLUMN 的 DEFAULT 'video' 兜住。
        "media_kind": getattr(a, "media_kind", None) or MEDIA_VIDEO,
        # 批 G：图片在"挑卡"列表里要直接说画幅（这张 9:16 出竖屏 / 这张横版出横屏）。
        # 判据留在后端一处：前端自己另拼一张宽高比表，日后口径一改就是两边各说一套
        # ——而这条口径的来源是实测（卡决定成片画幅），不是显示偏好。
        #
        # 11-09 起视频也给：这批横屏原片要收进库并在界面标「横屏」（用户拍板），而
        # orientation 只能从 resolution 推。此前恒回 null，界面那一列对视频永远显示
        # 「画幅未知」——不是量不到，是这一行只喂图片。resolution 已补齐（文件上传
        # 当场量、链接素材下载后回写），所以这里不加新口径，只把已有的一列对两类摊开；
        # 量不到时仍是 null，界面照样显示「画幅未知」。
        "aspect": _card_ratio_fields(a.resolution),
        "source_url": a.source_url,
        "platform": a.platform,
        "file_name": a.file_name,
        "file_key": a.file_key,
        "bucket": a.bucket,
        "file_size": a.file_size,
        # 批 J：下载动作自己的状态（NULL=没有要下的/还没排到），前端画成小图标
        "download_status": getattr(a, "download_status", None),
        "project_id": str(a.project_id) if a.project_id else None,
        "episode_id": str(a.episode_id) if a.episode_id else None,
        "prompt_task_id": str(a.prompt_task_id) if a.prompt_task_id else None,
        "title": a.title,
        "cover_image_key": a.cover_image_key,
        "duration": a.duration,
        "resolution": a.resolution,
        "prompt_max_duration": a.prompt_max_duration,
        # 11-04 拍板①：钩子原型（category_name 由列表侧一次性批量补，避免逐行查）
        "category_id": str(a.category_id) if a.category_id else None,
        "category_name": None,
        "stage_import": a.stage_import,
        "stage_prompt": a.stage_prompt,
        "stage_summary": a.stage_summary,
        "stage_produce": a.stage_produce,
        "stage_compose": a.stage_compose,
        "status": a.status,
        "has_approved_copy": bool(a.has_approved_copy),
        "cost_prompt": a.cost_prompt,
        "cost_produce": a.cost_produce,
        "cost_parse": a.cost_parse,
        "note": a.note,
        "created_by": str(a.created_by) if a.created_by else None,
        "created_at": utc_iso(a.created_at),
        "updated_at": utc_iso(a.updated_at),
    }
    if agg:
        data.update(agg)
    return data



def _serialize_summary(
    s: AssetSummary, asset: Optional[AssetItem] = None, *, can_resubmit: bool = False,
    category_name: Optional[str] = None, output_count: Optional[int] = None,
    reviewer_name: Optional[str] = None,
    production_count: Optional[int] = None,
) -> dict:
    data = {
        "id": str(s.id),
        "asset_id": str(s.asset_id),
        "seq": s.seq,
        "text": s.text,
        "style_tag": s.style_tag,
        "formula_tag": s.formula_tag,
        # 11-04 拍板①：文案的原型（出稿时继承素材，审核台可逐条改）
        "category_id": str(s.category_id) if s.category_id else None,
        "category_name": category_name,
        "word_count": s.word_count,
        "is_recommended": bool(s.is_recommended),
        "consistency_ok": s.consistency_ok,
        "consistency_note": s.consistency_note,
        "risk_hit": s.risk_hit,
        # P1（评审定稿⑯）：已开过几张生产单（挑选器防重复开单白烧号池）
        "production_count": production_count,
        "audit_status": s.audit_status,
        "reviewed_by": str(s.reviewed_by) if s.reviewed_by else None,
        # A′：过审人显示名（12px 灰字标注用）；None=调用方没聚合（详情口）或无主
        "reviewed_by_name": reviewer_name,
        "reviewed_at": utc_iso(s.reviewed_at) if s.reviewed_at else None,
        "reject_reason": s.reject_reason,
        # P1（评审定稿⑩）：作者重提说明（改后重提时写，审核卡展示）
        "resubmit_note": s.resubmit_note,
        "text_before_edit": s.text_before_edit,
        # 批 J：过审后备好的豆包提示词预览（NULL=还没备好/没排上；备好了审核台直接能看）
        "prompt_preview": s.prompt_preview,
        "prompt_preview_at": utc_iso(s.prompt_preview_at) if s.prompt_preview_at else None,
        "cost_preview": float(s.cost_preview or 0.0),
        # 11-06 双产出：出文案时同步生成的豆包网页版完整提示词（NULL=失败/未生成，可单独补）
        "doubao_prompt": s.doubao_prompt,
        # 批 N（11-09）：**预取**好、还没用掉的钩子编号（不是已投出去的号——那种号钉在
        # 生产单行上，看 production 的 hook_code）。开单时后端自动顶到缺号槽位并清空，
        # 所以这个键有值＝这条文案还欠着一张没开的单、手里有个能用的号。
        "hook_code": s.hook_code,
        "created_at": utc_iso(s.created_at),
        # 「改后重提」按钮要不要亮：前端不猜权限，按后端给的行级判定画
        "can_resubmit": bool(can_resubmit),
    }
    if asset is not None:
        data["asset_code"] = asset.code
        data["asset_title"] = asset.title
        data["asset_source_url"] = asset.source_url
        data["asset_platform"] = asset.platform
        data["asset_status"] = asset.status
    if output_count is not None:
        # 批 F 卡片右侧「已产 N 条」：只有 list_summaries 会查（整页一次聚合），
        # 别的调用方不传 = 这个键**不存在**，而不是 0——0 和"没查"是两回事，
        # 卡片拿 0 会画成「这条还没产出」，那是假信息。
        data["output_count"] = int(output_count)
    return data



def _serialize_production(
    p: AssetProduction,
    output_count: int = 0,
    owner_name: Optional[str] = None,
    category_name: Optional[str] = None,
) -> dict:
    return {
        "id": str(p.id),
        "asset_id": str(p.asset_id),
        "summary_id": str(p.summary_id),
        "batch_id": str(p.batch_id) if p.batch_id else None,
        # 试产单（2026-11-12）：前端据此把成片标注「试产」，成片墙/交付包读侧过滤
        "is_trial": bool(getattr(p, "is_trial", False)),
        # A′：投产人显示名（谁投账算谁的灰字标注）；None=调用方没聚合
        "owner_name": owner_name,
        "seq": p.seq,
        "hook_code": p.hook_code,
        # 批 M（11-10）：这条单所属文案的钩子原型名（列表口一次性批量补，口径与审核台一致）。
        # 投产弹窗的「可替换元素」按原型筛槽位，靠的就是这一列——单行口为 null。
        "category_name": category_name,
        "project_title": p.project_title,  # 废弃：11-02 版取消项目标题行，只读历史
        "prompt_text": p.prompt_text,
        "dispatch_note": p.dispatch_note,  # 只给人看，不进 payload
        "prompt_snapshot": p.prompt_snapshot,
        "video_titles": p.video_titles or [],
        "variant_basis": p.variant_basis,
        "drift": bool(p.drift),
        "drift_reason": p.drift_reason,
        "duration": p.duration,
        "channel": p.channel,
        # 后台任务板对账字段
        "board_total": p.board_total,
        "board_tag": p.board_tag,
        "board_date": utc_iso(p.board_date) if p.board_date else None,
        "board_name": p.board_name,
        "board_tid": p.board_tid,
        "board_rgid": p.board_rgid,
        # 批 L（投放进度可视化）：板子侧最后看到的行状态＋检查时间。null=没投过板
        # /回收动作没走到轮询（人工回写、刚建未投）。前端拿它显示「板子：出片中·上轮检查 …」。
        "board_last_status": p.board_last_status,
        "board_last_check_at": utc_iso(p.board_last_check_at) if p.board_last_check_at else None,
        "character_card_key": p.character_card_key,
        # 批 G：多卡数组（顺序＝板上 picDatas 顺序）。旧单这里是 []——
        # 读侧要区分"没挂卡"和"挂了一张旧 key"，看 character_card_key 那一列。
        "card_asset_ids": [str(x) for x in (p.card_asset_ids or []) if str(x or "").strip()],
        # 批 Q（11-10 需求⑤）：这张单投板时点名「出片后自动和哪条素材拼、拼在前还是拼在后」。
        # NULL＝没勾过，回收完就停（存量单全是这个态，行为与今天一致）。
        "concat_asset_id": str(p.concat_asset_id) if p.concat_asset_id else None,
        "concat_order": p.concat_order,
        # 最近一次自动拼的结果（拼成几支／失败几支／成因）。**只给界面看**，不参与任何判定——
        # 判据在 asset_outputs.composed_from_output_id 那侧，这里坏了也不影响业务。
        "concat_last_result": p.concat_last_result,
        "status": p.status,
        "error": p.error,
        # 投递台账（11-03 第 4 条）：一线要知道「这条投了几次、什么时候投的、什么时候出片」
        "attempts": int(p.attempts or 0),
        "started_at": utc_iso(p.started_at) if p.started_at else None,
        "completed_at": utc_iso(p.completed_at) if p.completed_at else None,
        "created_at": utc_iso(p.created_at),
        # 批 I（链路收敛）：行上「成片」列的数字——本单已收进几段片。口径与审核台
        # 卡片「已产 N 条」一致：排除 package/copy 附属文件，拼接产物没挂生产单天然不计。
        "output_count": int(output_count),
    }


# ──────────────────────────────────────────────
# 成本预览（前端确认弹窗先调这个，不落库）
# ──────────────────────────────────────────────



def _serialize_category(c: AssetCategory, usage: Optional[dict] = None) -> dict:
    data = {
        "id": str(c.id),
        "name": c.name,
        "parent_id": str(c.parent_id) if c.parent_id else None,
        "sort": c.sort,
        "active": bool(c.active),
        "note": c.note,
        "created_at": utc_iso(c.created_at),
        "updated_at": utc_iso(c.updated_at),
    }
    if usage:
        data.update(usage)
    return data


