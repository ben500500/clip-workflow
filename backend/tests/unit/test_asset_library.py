"""素材库纯逻辑层单测（app/services/asset_service.py）。

覆盖批量导入最容易出事的四个口径（设计方案 §3/§6/§7）：
1. 链接归一化去重：跨写法要合、不同素材绝不能误合（误合＝静默丢素材）
2. 成本预估与熔断：反推按**计时上限**扣费，档位选错一次烧几十块
3. 阶段派生：5 个阶段态 → 1 个 status 的 first-match 规则表
4. 审核：状态机、形态校验、高风险词、一致性（防「反推失败但文案编得像模像样」）

运行：cd backend && python -m pytest tests/unit/test_asset_library.py -v
"""

import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# app.config 是模块级单例，导入即校验必填项 —— 必须在 import 业务模块前置好测试 env
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_asset_library.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from app.services import asset_service as svc


# ─────────────────────────  1. 链接归一化  ─────────────────────────


@pytest.mark.parametrize("url", [
    "https://v.douyin.com/iAbCdEf/",
    "https://www.douyin.com/video/7123456789012345678",
    "https://www.iesdouyin.com/share/video/7123456789012345678/?region=CN",
])
def test_normalize_is_idempotent_for_douyin_video_id(url):
    """同一 video ID 的多种写法必须收敛到同一个去重键（跨批次去重的根基）。"""
    norm, platform = svc.normalize_source_url(url)
    assert norm is not None
    assert norm == svc.normalize_source_url(url)[0]
    if "7123456789012345678" in url:
        assert norm == "douyin:7123456789012345678"
        assert platform == "抖音"


def test_normalize_strips_tracking_params():
    """埋点参数（utm_/share_/scene…）不许进去重键，否则同素材每次都判新。"""
    a = "https://www.douyin.com/video/7000000000000000001?utm_source=copy&scene=1&share_from=userlinked"
    b = "https://www.douyin.com/video/7000000000000000001"
    assert svc.normalize_source_url(a)[0] == svc.normalize_source_url(b)[0]


def test_normalize_keeps_identity_params():
    """身份类 query（vid/id/note_id）必须保留 —— 有的平台视频 ID 只在 query 里。"""
    a = "https://haokan.baidu.com/v/?vid=123456789"
    b = "https://haokan.baidu.com/v/?vid=987654321"
    assert svc.normalize_source_url(a)[0] != svc.normalize_source_url(b)[0]


def test_normalize_never_false_merges_different_videos():
    """不同视频 ID 绝不能被归一成同一个键（误合＝静默丢素材，比漏合严重得多）。"""
    urls = [
        "https://www.xiaohongshu.com/discovery/item/64f1a2b3000000000100ffff",
        "https://www.xiaohongshu.com/explore/64f1a2b3000000000100fffe",
        "https://www.bilibili.com/video/BV1xx411c7mD?p=1",
        "https://www.bilibili.com/video/BV1xx411c7mE",
        "https://weixin.qq.com/sph/AAAhhhh",
        "https://weixin.qq.com/sph/BBBjjjj",
    ]
    norms = [svc.normalize_source_url(u)[0] for u in urls]
    assert len(set(norms)) == len(norms), f"出现误合：{norms}"


def test_bv_case_is_preserved_but_others_lowercased():
    """B 站 BV 号大小写敏感（不同 BV 只差大小写会撞车），其余平台 ID 统一小写。"""
    upper = svc.normalize_source_url("https://www.bilibili.com/video/BV1xx411c7mD")[0]
    lower = svc.normalize_source_url("https://www.bilibili.com/video/bv1xx411c7md")[0]
    assert upper != lower
    dy_a = svc.normalize_source_url("https://www.iesdouyin.com/share/video/7000000000000000002")[0]
    dy_b = svc.normalize_source_url("https://www.iesdouyin.com/share/video/7000000000000000002?u=ABC")[0]
    assert dy_a == dy_b == "douyin:7000000000000000002"


def test_normalize_extracts_url_from_share_text():
    """分享文案夹中文（抖音复制链接常见）也要能提出链接。"""
    raw = "7.33 复制打开抖音，看看作品 https://v.douyin.com/iZzZzZz/ 长按此条消息 查看链接"
    norm, platform = svc.normalize_source_url(raw)
    assert norm and norm.startswith("https://v.douyin.com/iZzZzZz")
    assert platform == "抖音"


@pytest.mark.parametrize("bad", ["", None, "没有链接的一段话", "ftp://x/y", "javascript:alert(1)"])
def test_normalize_rejects_non_http(bad):
    assert svc.normalize_source_url(bad) == (None, None)


def test_platform_labels():
    assert svc.normalize_source_url("https://www.kuaishou.com/short-video/3xw2qmn4b7y9pzk")[1] == "快手"
    assert svc.normalize_source_url("https://www.bilibili.com/video/av12345678")[1] == "B站"
    assert svc.guess_platform("xhslink.com") == "小红书"


def test_direct_url_detection():
    assert svc.looks_like_direct_url("https://cdn.example.com/a/b.mp4?sign=1")
    assert not svc.looks_like_direct_url("https://www.douyin.com/video/123")


# ─────────────────────────  2. 成本与熔断  ─────────────────────────


def test_unit_cost_uses_timer_cap_not_actual_duration():
    """0.00054 元/秒 × 计时上限：档位就是成本杠杆，600 档 100 条 = 32.4 元。"""
    assert svc.estimate_unit_cost(180) == pytest.approx(0.0972, abs=1e-6)
    assert svc.estimate_batch_cost(100, 600)["total_cost"] == pytest.approx(32.4, abs=1e-6)


def test_default_tier_is_not_max():
    """默认档位绝不能是 600（采集席位硬性反对过：100 条误选 600 档一次烧 32.4 元）。"""
    assert svc.DEFAULT_PROMPT_MAX_DURATION == 180
    assert svc.DEFAULT_PROMPT_MAX_DURATION != max(svc.PROMPT_MAX_DURATION_TIERS)


def test_optional_services_add_up():
    """解析/文案提取/上传的加价口径（手册计费表）。"""
    assert svc.estimate_unit_cost(60) < svc.estimate_unit_cost(60, need_parse=True) <= svc.estimate_unit_cost(60, need_parse=True) + 0.01
    assert svc.estimate_unit_cost(60, need_copy_extract=True) - svc.estimate_unit_cost(60) == pytest.approx(0.1, abs=1e-9)
    est = svc.estimate_batch_cost(10, 300, need_parse=True, need_upload=True)
    assert est["breakdown"]["parse"] == pytest.approx(0.1, abs=1e-9)
    assert est["breakdown"]["upload"] == pytest.approx(0.01, abs=1e-9)
    assert est["total_cost"] == pytest.approx(est["unit_cost"] * 10, abs=1e-6)


def test_estimate_exposes_all_tiers_for_confirm_dialog():
    """确认弹窗要能当场换档位看到钱，否则用户不知道自己刚点了什么。"""
    est = svc.estimate_batch_cost(50, 180)
    assert set(est["tiers"]) == {"60", "180", "300", "600"}
    assert est["tiers"]["60"] < est["tiers"]["180"] < est["tiers"]["600"]


def test_budget_gate_blocked_when_balance_low():
    gate = svc.budget_gate(40.0, balance=40.0, batch_cap=50.0, safety_ratio=1.2)
    assert gate["allowed"] is False and gate["level"] == "blocked"


def test_budget_gate_need_approval_over_cap():
    gate = svc.budget_gate(60.0, balance=1000.0, batch_cap=50.0)
    assert gate["allowed"] is False and gate["level"] == "need_approval"


def test_budget_gate_ok():
    gate = svc.budget_gate(9.72, balance=100.0, batch_cap=50.0)
    assert gate["allowed"] is True and gate["level"] == "ok"


def test_budget_gate_unknown_balance_passes_with_note():
    """余额接口有波动，查不到不能挡死业务，但必须留「事后对账」提示。"""
    gate = svc.budget_gate(9.72, balance=None, batch_cap=50.0)
    assert gate["allowed"] is True and gate["note"]


# ─────────────────────────  3. 阶段派生  ─────────────────────────


def _stages(**kw):
    base = {k: "pending" for k in ("import", "prompt", "summary", "produce", "compose")}
    base.update(kw)
    return base


@pytest.mark.parametrize("stages,approved,expected", [
    (_stages(), False, "draft"),
    (_stages(**{"import": "running"}), False, "importing"),
    # A4-6：导入完成待反推 ≠ 智令在跑，两态必须分开（旧口径两处都给 analyzing）
    (_stages(**{"import": "success"}), False, "waiting_prompt"),
    (_stages(**{"import": "success", "prompt": "running"}), False, "analyzing"),
    (_stages(**{"import": "success", "prompt": "skipped"}), False, "waiting_prompt"),
    # 11-09：稿到了但出文案没提交＝waiting_summary，不能再报「出文案中」
    (_stages(**{"prompt": "success"}), False, "waiting_summary"),
    (_stages(**{"prompt": "success", "summary": "running"}), False, "summarizing"),
    (_stages(**{"prompt": "success", "summary": "success"}), False, "awaiting_review"),
    (_stages(**{"prompt": "success", "summary": "success"}), True, "ready_to_produce"),
    (_stages(**{"summary": "success", "produce": "running"}), True, "producing"),
    (_stages(**{"summary": "success", "produce": "success"}), True, "composing"),
    (_stages(**{"produce": "success", "compose": "skipped"}), True, "ready"),
    (_stages(**{"produce": "success", "compose": "success"}), True, "ready"),
])
def test_derive_status_rule_table(stages, approved, expected):
    assert svc.derive_status(stages, has_approved_copy=approved) == expected


def test_any_failed_wins():
    """任一环节 failed 一律盖成 failed：批量列表里「看不出现在卡在哪」是最贵的体验。"""
    assert svc.derive_status(_stages(prompt="success", summary="failed"), True) == "failed"
    assert svc.derive_status(_stages(produce="success", compose="failed"), True) == "failed"


def test_apply_stage_recomputes_and_validates():
    asset = types.SimpleNamespace(
        stage_import="success", stage_prompt="success", stage_summary="pending",
        stage_produce="pending", stage_compose="pending", status="draft",
        has_approved_copy=False,
    )
    status = svc.apply_stage(asset, "summary", "success")
    assert status == "awaiting_review" and asset.stage_summary == "success"
    with pytest.raises(ValueError):
        svc.apply_stage(asset, "nonsense", "success")
    with pytest.raises(ValueError):
        svc.apply_stage(asset, "summary", "half-done")


# ─────────────────────────  3b. 图片入库口径（11-05 批 G）  ─────────────────────────


def test_image_status_short_circuits_the_video_chain():
    """图片的派生态是 `image_ready`，不是 `waiting_prompt`。

    这一条是批 G 立 `media_kind` 分支的全部理由：图的四阶段入库即 skipped，按视频那张
    规则表会一路落到 `waiting_prompt`（"待反推"）—— 列表里每张角色卡都显示"卡着没人管"，
    而正确动作恰恰是**别提交**（提交一次白扣一次钱）。
    """
    img = _stages(**{"import": "success", "prompt": "skipped", "summary": "skipped",
                     "produce": "skipped", "compose": "skipped"})
    assert svc.derive_status(img, media_kind="image") == "image_ready"
    # 同一个 stage 字典不带 media_kind（＝视频口径）确实会落成"待反推"：证明分支真的在起作用
    assert svc.derive_status(img) == "waiting_prompt"
    # 唯一保留的判断是 failed：导入本身炸了（落盘漏字节、桶写挂）必须还看得见
    assert svc.derive_status(_stages(**{"import": "failed"}), media_kind="image") == "failed"


def test_apply_stage_passes_media_kind_through():
    """`apply_stage` 重算状态时必须带上 media_kind，否则一次阶段回写就把图打回"待反推"。"""
    asset = types.SimpleNamespace(
        stage_import="success", stage_prompt="skipped", stage_summary="skipped",
        stage_produce="skipped", stage_compose="skipped", status="image_ready",
        has_approved_copy=False, media_kind="image",
    )
    assert svc.apply_stage(asset, "prompt", "skipped") == "image_ready"
    # 老调用方（SimpleNamespace 没这列 / 视频行）不受影响
    legacy = types.SimpleNamespace(
        stage_import="success", stage_prompt="pending", stage_summary="pending",
        stage_produce="pending", stage_compose="pending", status="draft",
        has_approved_copy=False,
    )
    assert svc.apply_stage(legacy, "prompt", "success") == "waiting_summary"


def test_shared_video_whitelist_still_rejects_images():
    """图片白名单**绝不能并进** `wechat_download` 那个共用扩展名表（批 G 的硬约束）。

    `prompt_service.UPLOAD_ALLOWED_EXTS` 同时被采集侧（`wechat_download/api.py`）用着，
    它服务的是"喂进 doc/120 做视频反推"。往那儿加 `.jpg` 就等于让角色卡能被提交去反推 ——
    不会成功，但**提交按次计费**。所以素材库侧另立一套，本条钉住两边不串门。
    """
    from app.config import settings as _settings
    from wechat_download.prompt_service import UPLOAD_ALLOWED_EXTS, validate_upload_ext

    assert ".jpg" not in UPLOAD_ALLOWED_EXTS and ".png" not in UPLOAD_ALLOWED_EXTS
    # 第二道同源白名单：`validate_file_name` 用的全局设置里同样不能有图片扩展名，
    # 否则"图片走自己的消毒函数"这件事会变成一句没有依据的偏好
    assert ".png" not in _settings.ALLOWED_VIDEO_EXTENSIONS
    assert validate_upload_ext("角色卡.jpg") is not None, "视频口收到图片必须拒"
    # 反向也要成立：素材库的图片校验不认视频文件
    assert svc.validate_asset_image_ext("原片.mp4") is not None
    assert svc.validate_asset_image_ext("无扩展名") is not None
    for name in ("角色卡.jpg", "角色卡.JPEG", "参考图.png", "参考图.webp"):
        assert svc.validate_asset_image_ext(name) is None, name
        assert svc.is_image_file_name(name) is True
    assert svc.is_image_file_name("原片.mp4") is False
    assert svc.IMAGE_CONTENT_TYPES[".png"] == "image/png"


def test_image_size_limit_is_reminder_only_on_ingest():
    """上限按 MB 判（配置由调用方传，本层不 import config）。"""
    assert svc.validate_asset_image_size(3 * 1024 * 1024, max_mb=20) is None
    err = svc.validate_asset_image_size(21 * 1024 * 1024, max_mb=20)
    assert err and "20MB" in err


def test_image_file_name_sanitizer_keeps_the_path_guard():
    """图片侧的文件名消毒：留 `basename`（防路径穿越），去视频白名单（11-05 实测 `.png` 会被拒）。"""
    assert svc.sanitize_asset_file_name("角色卡.png") == "角色卡.png"
    assert svc.sanitize_asset_file_name("a/b/角色卡.png") == "角色卡.png"
    assert svc.sanitize_asset_file_name("/../../etc/passwd.jpg") == "passwd.jpg"
    with pytest.raises(ValueError):
        svc.sanitize_asset_file_name("   ")


def test_image_aspect_and_shape_notes():
    """画幅判读：竖版放行、横版**只提醒不拒收**（拍板③：别替人做决定，但要让他看见）。"""
    portrait = svc.image_aspect(720, 1280)
    assert portrait == {"ratio": "9:16", "orientation": "portrait", "ok": True}
    landscape = svc.image_aspect(1280, 720)
    assert landscape["orientation"] == "landscape" and landscape["ok"] is False

    assert svc.image_shape_notes(720, 1280, min_edge=360, max_edge=4096) == []
    notes = svc.image_shape_notes(1280, 720, min_edge=360, max_edge=4096)
    assert any("横版" in n and "横屏" in n for n in notes), notes
    # 短边太小 = 当角色卡放大后会糊；长边超限 = 白占桶空间。两条都只是提醒
    small = svc.image_shape_notes(200, 300, min_edge=360, max_edge=4096)
    assert any("短边" in n for n in small), small
    huge = svc.image_shape_notes(3000, 5000, min_edge=360, max_edge=4096)
    assert any("长边" in n for n in huge), huge
    # 探不到尺寸（文件坏了）也要说人话，而不是显示"这张 0×0"
    assert svc.image_shape_notes(None, None, min_edge=360, max_edge=4096)
    assert svc.image_aspect(0, 0) == {"ratio": None, "orientation": None, "ok": True}


# ─────────────────────────  4. 审核：状态机 + 文案校验  ─────────────────────────


def test_review_transition_allows_documented_paths():
    svc.assert_review_transition("pending", "approved")
    svc.assert_review_transition("pending", "passed_edited")
    svc.assert_review_transition("approved", "pending")     # 撤销
    svc.assert_review_transition("rejected", "passed_edited")
    svc.assert_review_transition("approved", "approved")    # 同态幂等，批量重放不炸


@pytest.mark.parametrize("frm,to", [
    ("pending", "passed_edited_x"),
    ("approved", "need_rewrite"),   # 未列出的迁移一律拒（防「改完再改」绕过留痕）
    ("success", "approved"),
])
def test_review_transition_rejects_unknown(frm, to):
    with pytest.raises(ValueError):
        svc.assert_review_transition(frm, to)


def test_char_count_counts_punctuation_but_not_spaces():
    assert svc.count_copy_chars("她 替姐 姐嫁人，第二天！") == 11
    assert svc.count_copy_chars("") == 0


def test_copy_shape_flags_over_length_and_dangling_end():
    ok = svc.check_copy_shape("婆婆把嫁妆全给了小姑子，十年后她躺在儿媳的病房里。")
    assert ok["ok"], ok["problems"]
    long = svc.check_copy_shape("字" * 81)
    assert not long["ok"] and any("超字数" in p for p in long["problems"])
    dangling = svc.check_copy_shape("她替姐姐嫁人以后，")
    assert not dangling["ok"] and any("悬空" in p for p in dangling["problems"])
    first_long = svc.check_copy_shape("开头" + "太" * 30 + "，后面短句。")
    assert not first_long["ok"] and any("首句" in p for p in first_long["problems"])


def test_risk_scan_is_levelled_and_exempted():
    """A2-3：风险词分 block/warn，且误杀大户有豁免正则。

    block 拦人、warn 只留痕——不分级就会把「她第一次心动」按硬伤驳回，
    一线学会有意绕开词表，闸门等于没有。
    """
    hits = svc.scan_risk("这是全网络第一的狠活，包治百病，还敢去赌博")
    by_word = {h["word"]: h["level"] for h in hits}
    assert by_word["包治"] == svc.RISK_LEVEL_BLOCK
    assert by_word["赌博"] == svc.RISK_LEVEL_BLOCK
    assert by_word["第一"] == svc.RISK_LEVEL_WARN
    assert {h["word"] for h in svc.risk_block_hits(hits)} == {"包治", "赌博"}

    assert svc.scan_risk("干净的文案") == []
    # 豁免：「第一次」不是绝对化用语，不该算命中
    assert svc.scan_risk("她第一次心动，就把嫁妆给了他。") == []
    assert svc.scan_risk("史上最全", exemptions={})[0]["word"] == "史上"


def test_risk_lexicon_override_and_fail_closed():
    """配置写错不能把闸门写成全放行：空表回退默认、未知级别并到 block。"""
    book, _ = svc.normalize_risk_lexicon({"block": ["自定义禁词"]}, {})
    assert book[svc.RISK_LEVEL_BLOCK] == ["自定义禁词"] and not book[svc.RISK_LEVEL_WARN]
    assert svc.scan_risk("带自定义禁词", lexicon={"block": ["自定义禁词"]}, exemptions={}) == [
        {"word": "自定义禁词", "level": "block"}
    ]
    # 空覆盖表 → 默认表（不是"全放行"）
    assert svc.scan_risk("包治百病", lexicon={})
    # 未知级别一律当 block（宁可多拦）
    assert svc.scan_risk("玄学说法", lexicon={"dangerous": ["玄学"]})[0]["level"] == "block"
    # 非法正则忽略，不炸整条链路
    _, ex = svc.normalize_risk_lexicon(None, {"第一": "第一(次"})
    assert "第一" not in ex


def test_risk_hit_column_roundtrip_keeps_level():
    """risk_hit 落库是 `词|级别`，读回要还能分级；旧裸词按 block 处理。"""
    hits = svc.scan_risk("全网第一，包治百病")
    raw = svc.format_risk_hits(hits)
    assert raw and "|" in raw
    assert svc.parse_risk_hits(raw) == hits
    assert svc.format_risk_hits(None) is None and svc.parse_risk_hits(None) == []
    assert svc.parse_risk_hits("砍死,第一")[0] == {"word": "砍死", "level": "block"}
    assert svc.parse_risk_hits("第一|nonsense")[0]["level"] == "block"


def test_prompt_skeleton_checks_presence_only():
    """骨架判据只判"有没有这一行"，别越界去判写得好不好。"""
    full = "、".join(svc.PROMPT_SKELETON_KEYS)
    assert svc.check_prompt_skeleton(full)["ok"]
    gap = svc.check_prompt_skeleton(full.replace("负面", ""))
    assert not gap["ok"] and gap["missing"] == ["负面"]
    assert not svc.check_prompt_skeleton(None)["ok"]


def test_recheck_copy_blocks_only_block_level():
    script = "张总在母亲抢救当天签下合同。"
    good = svc.recheck_copy("张总在母亲抢救的当天，签下了那份合同。", script)
    assert good["ok"], good["problems"]
    # block 风险词 → 拦
    hard = svc.recheck_copy("张总把母亲捅死了，当天签下合同。", script)
    assert not hard["ok"] and any(p["code"] == "risk" for p in hard["problems"])
    # warn 风险词 → 只留痕，不拦
    soft = svc.recheck_copy("张总第一次签字，就把合同给了全网最低价的对手。", script)
    assert soft["ok"], soft["problems"]
    assert soft["risk"]
    # 一致性对不上 → **预警不拦**（R-6：专名识别只当预警，硬闸会把一线训练成逢钩子必找 admin 豁免，
    # 而豁免一旦不分类型就把同条里的真违禁词一起放过）。要它拦必须显式传 consistency_blocks=True
    bad = svc.recheck_copy("李总在华尔街撕了合同。", script)
    assert bad["ok"] is True, bad["problems"]
    assert any(p["code"] == "consistency" for p in bad["warnings"]), bad["warnings"]
    assert bad["consistency"]["ok"] is False
    hard_consist = svc.recheck_copy("李总在华尔街撕了合同。", script, consistency_blocks=True)
    assert not hard_consist["ok"] and any(p["code"] == "consistency" for p in hard_consist["problems"])


def test_consistency_requires_entities_in_script():
    """防「反推其实失败了，但文案编得像模像样」——审核员看不出，投了豆包才炸。"""
    script = "张总在公司楼下的医院被医生拦住，他母亲正在抢救。"
    good = svc.check_consistency("张总在母亲抢救的当天，签下了那份合同。", script)
    assert good["ok"] and "张总" in good["entities"]
    bad = svc.check_consistency("李总在华尔街的庆功宴上，当场撕了合同。", script)
    assert not bad["ok"] and bad["missing"]
    # 纯情绪型钩子没有专名：放行但带说明，不硬拦
    noent = svc.check_consistency("有些婚姻，是从一场替嫁开始的。", script)
    assert noent["ok"] and noent["note"]


def test_consistency_without_script_is_not_green_light():
    bad = svc.check_consistency("张总要离婚。", None)
    assert not bad["ok"]


def test_entities_include_single_surname_forms():
    """「张总/李姐/王妈」这类单字姓+称呼是短剧文案最常见写法，必须被抽成实体。

    回归：_NAME_RE 曾写成 {2,4}，把单字姓整个漏掉 → 一致性校验形同虚设
    （编出来的文案查不出与详规对不上）。
    """
    ents = svc.extract_entities("张总当着李姐的面，把华康医院的合同撕了。")
    assert "张总" in ents and "李姐" in ents and "华康医院" in ents


def test_entities_do_not_emit_garbage():
    """抽实体最容易出事的两类假警报，都在这里钉住。

    - 「为了提高总产量」里的「高总」不是人名（靠字边界挡掉）；
    - 店名用字（和/中/山）不能当切分符，否则「仁和医院」会被切成「仁医院」。
      假实体会把一致性校验训成没人看的噪音栏，比漏报更有害。
    """
    assert svc.extract_entities("为了提高总产量，车间主任连夜加班。") == []
    assert svc.extract_entities("欧阳总去了仁和医院。") == ["欧阳总", "仁和医院"]
    assert svc.extract_entities("她在中山医院的走廊里等了三天。") == ["中山医院"]


# ─────────────────────────  5. 产能 / 入参清洗  ─────────────────────────


def test_capacity_is_quota_bound_not_wall_clock():
    """排产按豆包单号 3 条/日（实测 2~4），不是按 8 小时工时算。"""
    plan = svc.estimate_production_days(120, account_count=2)
    assert plan["capacity_per_day"] == 6
    assert plan["days"] == 20
    assert svc.estimate_production_days(0, 1)["days"] == 0
    assert svc.estimate_production_days(1, 0)["account_count"] == 1  # 号数兜底至少 1


def test_variant_basis_differs_within_first_six():
    """N 的语义 = 同一文案派生 N 条**差异化**提示词，差异来源必须互不相同。"""
    bases = [svc.variant_basis(i, 6) for i in range(1, 7)]
    assert len(set(bases)) == 6
    assert "轮" in svc.variant_basis(7, 8)


def test_normalize_source_list_dedupes_within_batch_and_keeps_overflow():
    """同批内去重照做，但**超单批上限不再报错**——一条都不许丢，剩下的交给拆批（A4-1）。"""
    kept, skipped = svc.normalize_source_list(
        ["https://a.com/1", "https://a.com/1", "  ", "https://a.com/2"]
    )
    assert kept == ["https://a.com/1", "https://a.com/2"]
    assert any("同批内重复" in s for s in skipped) and any("空链接" in s for s in skipped)
    over = [f"https://a.com/{i}" for i in range(101)]
    kept_over, _ = svc.normalize_source_list(over)
    assert len(kept_over) == 101, "旧行为在这里抛「请拆批提交」，把 300 条一把粘的一线打回人工数数"
    kept_single, _ = svc.normalize_source_list("https://a.com/only")
    assert kept_single == ["https://a.com/only"]


def test_chunk_by_limit_splits_into_shards_without_loss_or_reorder():
    """超量 → 按 limit 切片（每片各建一个批次），顺序不变、一条不丢（A4-1）。"""
    assert svc.chunk_by_limit([], 100) == []
    assert svc.chunk_by_limit(list("abc"), 0) == [["a", "b", "c"]], "limit<=0 即不拆"
    assert svc.chunk_by_limit(list(range(3)), 100) == [[0, 1, 2]], "没超量就一片，别硬凑批次"
    shards = svc.chunk_by_limit(list(range(7)), 3)
    assert [len(s) for s in shards] == [3, 3, 1]
    assert [s[0] for s in shards] == [0, 3, 6]
    flat = [x for s in shards for x in s]
    assert flat == list(range(7)), "拆批只改「分几个批次」，不改内容顺序"
    assert [len(s) for s in svc.chunk_by_limit(list(range(100)), 100)] == [100], "正好等于上限不拆"


# ─────────────────────────  6. 后台任务板（通道 wework_aivideo）  ─────────────────────────


def test_board_name_is_first_recommended_title_sanitized():
    """板上 name＝推荐视频标题第 1 条：剥文件名非法字符、按码点截 60、不动语义。"""
    assert svc.sanitize_board_name("她第一次心动：婆婆的存折") == "她第一次心动：婆婆的存折"
    assert svc.sanitize_board_name('救个总裁当老公/第1集:A*B?"C"<D>|E') == "救个总裁当老公 第1集 A B C D E"
    assert svc.sanitize_board_name("  带尾点.title  ") == "带尾点.title", "只剥首尾，正文里的点不动"
    assert svc.sanitize_board_name("结尾句点。") == "结尾句点"
    long = "闸" * 80
    assert len(svc.sanitize_board_name(long)) == svc.BOARD_NAME_MAX_CODEPOINTS
    assert svc.sanitize_board_name("") is None and svc.sanitize_board_name(None) is None
    assert svc.sanitize_board_name("///") is None, "全是非法字符时宁可不给 name，也不能投出空名任务"


def test_board_date_is_full_local_timestamp_to_the_second():
    """date 必须完整到秒且折算板面本地时区：只写日期＝成片永久取不回（1021 烧了 120 条）。"""
    from datetime import datetime

    base = datetime(2026, 11, 3, 17, 30, 12, 123456)
    assert svc.board_timestamp(base, tz_offset_hours=8) == datetime(2026, 11, 4, 1, 30, 12)
    assert svc.board_timestamp(base, tz_offset_hours=0) == datetime(2026, 11, 3, 17, 30, 12)
    assert svc.board_timestamp(base, tz_offset_hours=8).isoformat().endswith(":12")


def test_split_dispatch_note_moves_instruction_without_rewording():
    """执行要求是给人看的指令：整行搬出正文，一个字都不改（B-9）。"""
    text = (
        "【第 1 段 · 建议 10 秒 · 本钩共 3 条 · 编号 7C0B3】\n"
        "婆婆把存折摔在桌上，普通家庭客厅，没有其他餐桌。\n"
        "执行要求：重命名一字不差；跳过任何二次确认；一次性并行生成 2 个视频\n"
        "本批 3 条差异化提示词，别手抖改词。"
    )
    body, note = svc.split_dispatch_note(text)
    assert "执行要求" not in body and "重命名" not in body
    assert "婆婆把存折摔在桌上" in body
    assert note.startswith("执行要求") and "别手抖改词" in note
    assert svc.split_dispatch_note("纯正文，没有指令行")[1] is None
    assert svc.split_dispatch_note("纯正文，没有指令行")[0] == "纯正文，没有指令行"
    assert svc.split_dispatch_note("") == (None, None)


def test_hook_code_is_five_chars_and_never_invented():
    """编号=日期2+剧码2+当日序号1（五位 0-9A-Z）；后端不代编，格式必须卡死。"""
    assert svc.is_valid_hook_code("7C0B3")
    assert svc.is_valid_hook_code(" 7c0b3 "), "判据先归一（去空格/转大写），大小写不拦人——防撞码靠的是取号工具"
    assert svc.is_valid_hook_code("7C0B") is False
    assert svc.is_valid_hook_code("7C0B31") is False
    assert svc.is_valid_hook_code("7C0B-") is False
    assert svc.is_valid_hook_code(None) is False


def test_board_capacity_is_advisory_only():
    """软闸门（B-8）：超 120 条只提示分日，不拒绝——用户口径是「产能不限」。"""
    under = svc.board_capacity_hint(60, already_today=40, soft_cap=120)
    assert under["over_cap"] == 0 and under["advisory"] is None
    over = svc.board_capacity_hint(100, already_today=100, soft_cap=120)
    assert over["total_today"] == 200 and over["over_cap"] == 80
    assert "号池实测" in over["advisory"] and "分日" in over["advisory"]
    off = svc.board_capacity_hint(500, already_today=0, soft_cap=0)
    assert off["over_cap"] == 0 and off["advisory"] is None, "soft_cap<=0 即关闭提示"


# ─────────────────────────  7. 展开漂移判定 + 交付形态（A3-3 / A3-1）  ─────────────────────────

COPY = "王总在康华医院门口站了三小时"


def test_drift_catches_the_three_blind_spots_of_the_old_substring_check():
    """旧判据只做「去空格子串包含」，这三种改写全判成没漂移——现在必须都判漂移（A3-3）。"""
    assert svc.judge_drift(COPY, f"镜头缓慢推进，{COPY}")["drift"] is True, "前面被拼了半句"
    assert svc.judge_drift(COPY, f"{COPY}{COPY}")["drift"] is True, "整句复制两遍＝N 条差异失效"
    assert svc.judge_drift(COPY, f"（{COPY}）")["drift"] is True, "原句被括号包成画面说明"
    assert svc.judge_drift(COPY, "王总在楼下站了三小时")["drift"] is True, "模型重写了文案"
    assert svc.judge_drift(COPY, "")["drift"] is True
    assert svc.judge_drift(None, COPY)["drift"] is True, "没有过审文案可比 = 判漂移，别装绿灯"
    for bad in (f"镜头缓慢推进，{COPY}", f"（{COPY}）"):
        verdict = svc.judge_drift(COPY, bad)
        assert verdict["reasons"] and verdict["occurrences"] == (2 if bad == f"{COPY}{COPY}" else 1)


def test_drift_allows_legit_template_shapes():
    """模板正常引出钩子的写法不许误报：drift 提示一多，一线就不看了（这套闸门的命门在可信度）。"""
    assert svc.judge_drift(COPY, f"【7C0B3】\n旁白：{COPY}，神情疲惫")["drift"] is False, "冒号引出 + 后接描述"
    assert svc.judge_drift(COPY, f"字幕：“{COPY}”")["drift"] is False, "引号是合法引用，不是改写"
    assert svc.judge_drift(COPY, COPY)["drift"] is False, "整条提示词就是钩子本身"
    assert svc.judge_drift(COPY, f"  {COPY} \n")["drift"] is False, "空白差异归一，不算漂移"


def test_drift_does_not_confuse_missing_skeleton():
    """缺骨架行是「模板没写全」，不是「审的和产的不是同一条」——两件事分开判（A2-1 vs A3-3）。"""
    bare = COPY  # 只有钩子、十行骨架一行没有
    assert svc.check_prompt_skeleton(bare)["ok"] is False
    assert svc.judge_drift(COPY, bare)["drift"] is False


def test_export_block_carries_the_code_in_all_three_places():
    """11-02 权威：编号必须出现在段头、推荐标题尾、产出清单三处（A3-1）。"""
    block = svc.format_export_block(
        hook_code="7C0B3",
        prompt_text="【7C0B3】第一镜\n" + COPY + "，画面切远景",
        video_titles=["王总站了三小时", f"第2条（7C0B3）"],
        dispatch_note="【执行要求】跳过二次确认",
    )
    assert block.startswith("=== 7C0B3 ==="), "段头带编号"
    assert "1. 王总站了三小时（7C0B3）" in block, "编号缺失才补，补在尾部"
    assert "2. 第2条（7C0B3）" in block, "已带编号不重复补"
    assert "不要贴进豆包对话" in block and "跳过二次确认" in block.split("不要贴进豆包对话")[1], (
        "投放要求只进 txt，标在块尾（B-9）"
    )
    assert COPY in block
    # 无编号时明确标缺，不拿 None 去拼字符串
    assert "缺编号" in svc.format_export_block(hook_code=None, prompt_text="正文", video_titles=["标题"])
    assert "不许投" in svc.format_export_block(hook_code="7C0B3", prompt_text="正文", video_titles=[])


def test_output_manifest_is_the_third_place_for_the_code():
    rows = [
        {"hook_code": "7C0B3", "board_name": "JY11031·王总站了三小时", "asset_code": "AS-0001", "seq": 1},
        {"hook_code": None, "board_name": None, "asset_code": None, "seq": 2},
    ]
    text = svc.format_output_manifest(rows)
    assert text.startswith("产出清单")
    assert "7C0B3｜JY11031·王总站了三小时｜AS-0001｜第1条" in text
    assert "缺编号" in text and "第2条" in text
    assert svc.format_output_manifest([]) == ""


def test_board_payload_is_exactly_the_seven_board_keys():
    """payload 只认七键（pipeline.py:240-262 实测），reqID 钉在生产单 id 上（幂等 + 回收对账）。"""
    from datetime import datetime

    payload = svc.build_board_payload(
        production_id="6f1c-uuid", board_tag="ben", board_total=3,
        board_date=datetime(2026, 11, 3, 14, 5, 9), prompt_text="正文",
        board_name="JY11031·标题", card_b64_items=["QUJD"],
    )
    assert tuple(payload.keys()) == svc.BOARD_PAYLOAD_KEYS
    assert payload["reqID"] == "6f1c-uuid" and payload["total"] == 3
    assert payload["date"] == "2026-11-03 14:05:09", "完整时间戳：只写日期会 succ 但永久查不到"
    assert payload["picDatas"] == ["QUJD"], "纯 base64，不带 data: 前缀"
    assert svc.card_b64_from_bytes(b"ABC") == "QUJD"
    # total 越界按板侧口径夹到 1..20；无卡给空数组（不塞 None，板侧会当脏数据）
    edge = svc.build_board_payload(
        production_id="x", board_tag=None, board_total=99, board_date=None,
        prompt_text=None, board_name=None, card_b64_items=None,
    )
    assert edge["total"] == 20 and edge["picDatas"] == [] and edge["tag"] == ""
    assert svc.build_board_payload(production_id="x", board_tag="t", board_total=0,
                                   board_date=None, prompt_text="p", board_name="n")["total"] == 1


# ─────────────────────────  8. 推荐标题字数软校验（P1 #19：只 warning 不拦）  ─────────────────────────


def test_title_budget_over_limit_warns_and_never_raises():
    """超预算的标题**收进清单**而不是抛异常——抛了就等于把软校验做成闸门。

    11-02 §3.1 的示例正文（20~22 字）比它自己的预算（≤18）长，正好当超支样本。
    """
    over = "怀三胎·7G101·刚离婚就孕吐，他撕碎协议"  # 22 字
    assert svc.count_copy_chars(over) == 22
    warns = svc.check_video_title_budget([over, "疙瘩汤·7D0B2·替姐出嫁第二天"])
    assert warns == [{"title": over, "chars": 22, "limit": 18}], warns


def test_title_budget_exactly_at_limit_is_not_flagged():
    """正好 18 字＝贴线合规，不许误报（模板自查行写的就是「每条 ≤18 字」）。"""
    on_limit = "救总裁·7F2A9·婆婆跪在产房外哭"  # 3+1+5+1+8 = 18
    assert svc.count_copy_chars(on_limit) == svc.TITLE_BODY_BUDGET_CHARS
    assert svc.check_video_title_budget([on_limit]) == []
    assert svc.check_video_title_budget([on_limit + "呢"]) == [{"chars": 19, "limit": 18,
                                                                "title": on_limit + "呢"}]


def test_title_budget_drama_abbr_length_feeds_the_hook_quota():
    """剧缩越长、精简钩子越挤：上限＝11－剧缩字数，但判据落在正文 ≤18 上（18−「·」−5−「·」＝11）。

    4 字剧缩配 8 字钩子＝19 字正文：按配额钩子只能 7 字，这里必须报——
    与拆段判「8 > 11−4」结果一致，正文口径不需要知道哪段是剧缩。
    """
    tight = "一胎四宝·7D0B2·婆婆跪在产房外哭"  # 4+1+5+1+8 = 19
    assert svc.check_video_title_budget([tight])[0]["chars"] == 19
    ok = "一胎四宝·7D0B2·婆婆跪产房外哭"  # 4+1+5+1+7 = 18
    assert svc.check_video_title_budget([ok]) == []


def test_title_budget_empty_and_blank_titles_do_not_explode():
    """空清单 / None / 混进空串空白 None：一个都不报、一个都不炸（缺标题另有 missing_names 警告）。"""
    assert svc.check_video_title_budget(None) == []
    assert svc.check_video_title_budget([]) == []
    assert svc.check_video_title_budget(["", None, "   ", "·"]) == []


def test_title_budget_counts_with_the_same_ruler_as_copy_chars():
    """字数必须用 count_copy_chars（含标点、不含空白）——换一把尺两边数就对不上。"""
    spaced = "怀三胎 · 7G101 · 刚离婚就孕吐"  # 空格不算字：3+1+5+1+6=16 正文 → 不超
    assert svc.count_copy_chars(spaced) == 16
    assert svc.check_video_title_budget([spaced]) == []
    punctuated = "怀三胎·7G101·刚离婚就孕吐？？！"  # 19 个非空白（标点全算）
    assert svc.count_copy_chars(punctuated) == 19
    assert svc.check_video_title_budget([punctuated])[0]["chars"] == 19


# ─────────────────────────  7. 配置引用守卫  ─────────────────────────


def test_every_settings_attribute_used_by_the_code_actually_exists():
    """代码里写的 `settings.X` 必须真的在 config.py 里定义（11-04 第二轮审核 R-7）。

    为什么值得单独一条：素材库曾有 `settings.ASSET_PROMPT_MAX_DURATION_DEFAULT`，
    而 **config.py 里根本没有这个字段**——pydantic v2 的 BaseSettings 没有 `__getattr__`
    兜底，取它就是 AttributeError。它藏在 `batch.prompt_max_duration or settings.…` 的
    **短路右支**，正常数据永远走不到，于是 389 条测试全绿、代码照旧带病跑；真来一条
    档位为 NULL 的批次行（历史数据/手工建批），文件批量入库当场 500。

    这类"字段名拼错"不显式引用一遍永远看不见，而全仓 AST 扫一遍不到一秒，
    所以把它钉成守卫：以后加配置字段忘了写、或引用了别人删掉的字段，测试先红。
    """
    import ast

    from app.config import settings

    app_dir = Path(__file__).resolve().parents[2] / "app"
    bad: dict = {}
    for py in sorted(app_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "settings"
                and not hasattr(settings, node.attr)
            ):
                rel = py.relative_to(app_dir.parent)
                bad.setdefault(node.attr, []).append(f"{rel}:{node.lineno}")
    assert not bad, "代码引用了 config.py 里不存在的配置字段：" + "; ".join(
        f"settings.{k}（{', '.join(v)}）" for k, v in sorted(bad.items())
    )


def test_self_produce_flag_class_default_is_open():
    """`ASSET_SELF_PRODUCE_ALLOWED` 的**类默认值**必须是 true（2026-11-11 评审·测试席 P1）。

    为什么 conftest 那钉不算数：`tests/conftest.py` 的 autouse 夹具用
    `monkeypatch.setattr(settings, "ASSET_SELF_PRODUCE_ALLOWED", True)` 把**实例属性**钉成
    true——它保证 634 条存量用例跑在放开口径上，但它同时把类默认值**遮住了**：
    哪天有人把 config.py 改回 false（或反过来"以为默认是 true"却在 .env 里写了 false
    而没人发现），夹具照样把它盖成 true，全套测试仍然绿，现网行为却已经变了。
    11-09 用户拍板「一人多角是常态，默认放开」，这条拍板只有钉在类字段上才算数。

    读的是 `Settings.model_fields[...].default`（pydantic v2 的类字段默认值），
    不读 `settings.X`——后者已被夹具改过，读了就是自己骗自己。
    """
    from app.config import Settings

    default = Settings.model_fields["ASSET_SELF_PRODUCE_ALLOWED"].default
    assert default is True, (
        "自审自投默认值被人改回去了：11-09 用户口径是**默认放开**（一人多角常态），"
        "放开时逐条写豁免审计。要改请连带改 conftest 基线与专项用例，别只改一行。"
    )


# ─────────────────────────  8. 静态守卫：同步等模型不许带着开着的会话操作  ─────────────────────────


def test_no_model_wait_with_unended_session_activity():
    """G-1（11-11 评审留口，11-13 落地）：函数内 `await _call_autoclip(...)` 之前，若自
    最近一次 commit/rollback 之后还有过任何 `db.*`／`session.*` 会话操作、中间没收口——红。

    钉的是什么坑：现网 PG `idle_in_transaction_session_timeout=60s`（app/database.py 强制），
    接口从进来到调模型之间的 SELECT 一路开着事务趴到模型回来（pro/flash 实测每次 90~150s，
    扇出还要 ×N），60s 一到连接被掐：模型**成功返回**、回写报 `connection is closed`、
    整口 500——钱花了、结果丢了、缓存一行没落（11-11 现网 8-27 两批 500 实录）。

    为什么必须静态钉：11-03 出文案、11-05 预览展开、11-11 换皮补位三个入口**先后踩过同一坑**，
    修法早就写在进度总览（调模型前先 `await db.commit()` 收读事务），前两个口只有行为级用例、
    第三个口有源码级钉，但**全仓没有任何守卫能拦住第四个入口**——本机 648 条用例把模型
    全打了桩，测不到 60s 掐线，新入口照样能静默上线（§4 F41 判断，11-13 首跑即抓到
    create_productions 扇出口＝活体第四入口）。

    扫描口径（诚实说明边界）：
    · 事件流按**行号序**（近似控制流）：`db./session.` 的 execute/get/add/flush…＝开，
      commit/rollback＝收，`_call_autoclip(`＝模型等待——等待点前仍有"未收的开"即违规；
    · **例外姿势（必须登记）**：函数体内有 `SET LOCAL idle_in_transaction_session_timeout = 0`
      ＝"续命"而非"收口"（投产口 8143：整批原子性要求在调模型前**不能** commit，
      靠 SET LOCAL 让本事务不被 60s 掐线 + 等待期间不锁别人要动的行 + 页面路径 D-1 批收进
      async_mode 后台任务、HTTP 不趴连接池三层并立）。这种等待点不违规，但必须出现在
      `SET_LOCAL_TIMEOUT_EXEMPTS` 登记名单里——名单**双向钉死**：SET LOCAL 被摘掉 → 该口
      裸奔进违规红；新长出一个 SET LOCAL 防护口 → 名单不匹配红，逼人来复核三层防护；
    · helper 里的会话（`await _get_asset_or_404(db, …)`）不计入"开"：helper 若自带收口，
      等待点前必有本函数可见的 commit；若无收口又开事务，行为与直接调用等价，扫描会漏——
      这是**有意的简化**，新增 helper 包装的模型口请补行为级用例；
    · 循环回跳可能产生理论假红（行序看"最后一次开"在 commit 之后但控制流会回绕）——
      命中者逐个复核后登记，不静默放宽规则。
    """
    import ast

    MODEL_FUNCS = {"_call_autoclip"}
    SESSION_NAMES = {"db", "session"}
    OPEN_ATTRS = {"execute", "get", "get_all", "add", "add_all", "flush", "merge",
                  "delete", "refresh", "scalar", "scalars"}
    CLOSE_ATTRS = {"commit", "rollback"}
    # SET LOCAL 续命姿势的特征串（与 8144 现文对得上；写法变了本守卫当"没有防护"处理）
    TIMEOUT_OFF_MARK = "idle_in_transaction_session_timeout = 0"

    # SET LOCAL 豁免登记名单（函数身份 file::func）。改动任何一个都会红，新加口必须先来登记。
    SET_LOCAL_TIMEOUT_EXEMPTS = {"app/api/assets.py::create_productions"}

    app_dir = Path(__file__).resolve().parents[2] / "app"
    roots = [app_dir / "api", app_dir / "services"]

    def _walk_own_body(fn):
        """遍历函数体，不钻进嵌套的函数/类/生成器定义（那些另立事件流）。"""
        stack = list(ast.iter_child_nodes(fn))
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                                 ast.ClassDef)):
                continue
            yield node
            stack.extend(ast.iter_child_nodes(node))

    def _is_timeout_off_call(node, src_lines) -> bool:
        """识别 `await db.execute(text("SET LOCAL …idle…= 0"))`（只认 text 字面量）。"""
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "execute"
                and isinstance(f.value, ast.Name)
                and f.value.id in SESSION_NAMES):
            return False
        if not node.args:
            return False
        arg0 = node.args[0]
        if (isinstance(arg0, ast.Call) and isinstance(arg0.func, ast.Name)
                and arg0.func.id == "text" and arg0.args
                and isinstance(arg0.args[0], ast.Constant)
                and isinstance(arg0.args[0].value, str)):
            return TIMEOUT_OFF_MARK in arg0.args[0].value
        return False

    def _as_timeout_off(node, src_lines) -> bool:
        return _is_timeout_off_call(node, src_lines)

    # 显式登记表（行为级豁免，当前应为空——"裸奔等待点"一律不许登记）
    EXEMPT: dict = {}

    hits = []
    seen_timeout_exempts = set()
    for root_dir in roots:
        for py in sorted(root_dir.rglob("*.py")):
            try:
                src = py.read_text(encoding="utf-8")
                tree = ast.parse(src, filename=str(py))
            except SyntaxError:
                continue
            src_lines = src.splitlines()
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                events = []
                for node in _walk_own_body(fn):
                    if not isinstance(node, ast.Call):
                        continue
                    f = node.func
                    if isinstance(f, ast.Name) and f.id in MODEL_FUNCS:
                        events.append((node.lineno, "model"))
                    elif (isinstance(f, ast.Attribute)
                          and isinstance(f.value, ast.Name)
                          and f.value.id in SESSION_NAMES):
                        if f.attr in OPEN_ATTRS:
                            if _as_timeout_off(node, src_lines):
                                events.append((node.lineno, "timeout_off"))
                            else:
                                events.append((node.lineno, "open"))
                        elif f.attr in CLOSE_ATTRS:
                            events.append((node.lineno, "close"))
                if not events:
                    continue
                events.sort(key=lambda x: x[0])
                rel = py.relative_to(app_dir.parent)
                fn_key = f"{rel}::{fn.name}"
                open_since_close = False
                timeout_off_active = False
                for lineno, kind in events:
                    if kind == "open":
                        open_since_close = True
                    elif kind == "close":
                        open_since_close = False
                        timeout_off_active = False   # 事务一收 SET LOCAL 随之失效，等待点必须重新防护
                    elif kind == "timeout_off":
                        timeout_off_active = True
                    elif kind == "model":
                        if open_since_close and not timeout_off_active:
                            if fn_key in EXEMPT:
                                continue
                            hits.append(f"{fn_key}@{lineno}")
                        elif open_since_close and timeout_off_active:
                            seen_timeout_exempts.add(fn_key)
    assert not hits, (
        "这些『同步等待模型』之前既没收掉会话操作、也没有 SET LOCAL 续命防护（11-11 现网实录："
        "模型成功返回、回写被 60s 掐线炸 500、钱白花）——首选修法是等待点前补 "
        "`await db.commit()` 收读事务（与 6226/7073/13161 三口同法）；确需整批原子性的口"
        "照 create_productions 补 SET LOCAL 三层并立并在登记名单里写明：" + ", ".join(hits)
    )
    assert seen_timeout_exempts == SET_LOCAL_TIMEOUT_EXEMPTS, (
        "SET LOCAL 续命口名单漂移：新增了先复核三层防护（原子性理由＋不锁他人行＋async_mode）"
        "再登记；减少了说明防护被摘、等待点已经在裸奔。"
        f"实到 {sorted(seen_timeout_exempts)} ≠ 登记 {sorted(SET_LOCAL_TIMEOUT_EXEMPTS)}"
    )
