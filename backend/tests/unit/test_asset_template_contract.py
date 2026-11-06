"""文案模板 ↔ 判据代码的契约单测（素材库 P0 文案模板对版）。

为什么单独立一个文件：模板由人话写成，判据由代码写成，两边**各说一套时没有任何
编译期信号**——11-03 对版时就查出三处真断裂：
  ① 骨架关键词「音频 / 负面」只存在于行标签里，模板没要求把标签输出 → 模型按
     「内容意思到了」写，`check_prompt_skeleton` 判缺行；
  ② 模板写「首句＝到句号为止」，代码 `check_copy_shape` 还在 「，；」 上断句 →
     双段式钩子整批被判超长；
  ③ 段头缺号写法模板写「未取号」、导出侧写「缺编号」→ 一线对不上账。
本文件把「按模板字面拼出来的东西必须过得了代码」钉成回归闸门，改模板先过这里。

运行：cd backend && python -m pytest tests/unit/test_asset_template_contract.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/_unit_asset_contract.db")
os.environ.setdefault("JWT_SECRET", "u" * 64)
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")

from app.services import asset_service as svc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPAND_TEMPLATE = REPO_ROOT / "autoclip" / "app" / "prompt" / "hook_expand.txt"
COPY_TEMPLATE = REPO_ROOT / "autoclip" / "app" / "prompt" / "hook_copy.txt"

# 过审钩子文案（双段式：前3秒 / 后7秒，中间句号——模板第 3 条的写法）
COPY = "前3秒：她替姐姐嫁的第二天。后7秒：新郎出现在她姐的婚礼上，当着两家长辈问这婚到底算谁的"
HOOK_CODE = "7D0B2"


def _canonical_prompt() -> str:
    """**逐行照 `hook_expand.txt` 的骨架清单拼出来的样例**，不是模型输出。

    模板说「每行连行标签一起输出」，这里就一行一行写标签；模板说剧情行要保留
    【前3秒】【后7秒】标记、行末照抄那句「起因—冲突—收束」，这里也照做。
    它过不了判据，就等于模板在骗模型。
    """
    return "\n".join([
        f"【第 3 段 · 建议 10 秒 · 本钩共 6 条 · 编号 {HOOK_CODE}】",
        f"钩子原文：{COPY}",
        "生成【现言豪门】仿真人写实短剧，参考【《一碗疙瘩汤成少爷后妈》】剧情，输入素材为 AI 多视图角色设定卡，"
        "不要当做实拍真人照片，严格参考锁定男女主五官、脸型、发型、整体气质，禁止篡改人物样貌。"
        "本剧为完全虚构的原创故事，所有角色均为虚构原创人物，与任何真实人物、明星、在映影视作品无关。",
        "时长 10 秒，9:16 竖屏，模拟手机竖屏实拍短剧影视质感。",
        "剧情：【前3秒】普通民居客厅，旧沙发、塑料凳，没有其他餐桌；女主略带倦容起身拿外套，"
        "男主西装不打领带拦在门口。【后7秒】婚礼现场，男主被两家长辈围住问婚约算谁的，"
        "女主当众把彩礼红本拍在桌上。本条为「起因—冲突—收束」完整的微故事，结尾情绪收束，不在动作高潮中途截断。",
        "爆款基因：穿帮泄密开场——婚约红本在公开场合被拍出，关系悬念当场泄密。",
        "结构锁定：文案为「前3秒+后7秒」双段式，段界 3 秒±0.5 秒；前3秒只演剧情行【前3秒】内容，"
        "后7秒只演【后7秒】内容；禁止调整两段顺序、禁止新增过渡情节、禁止自由发挥新增台词与镜头、"
        "禁止把后段信息提前剧透到前3秒。",
        "冲突强化：全片至少 3 次镜头切换，单镜头停留不超过 3 秒，至少 2 个肢体冲突动作（拦门拽腕、拍桌指认），"
        "情绪按「爆发—升级—反转」三级递进。",
        "时间轴：0-3 秒强冲突钩子，3-7 秒推进矛盾，7-10 秒情绪定格收束留悬念（画面完整闭合）；"
        "单镜头停留≥1.5 秒，人物情绪特写镜头≥2 秒。",
        "自动匹配剧情对应场景，使用近景、面部特写、正反打镜头，人物表演富有戏剧张力。"
        "客厅拦门用侧四十五度中近景，不做正面唇部大特写。",
        "画面变化：同一项目多次生成时，每次生成前从「时段氛围（清晨/正午/黄昏/夜晚/雨夜）、"
        "景别主调（特写/近景/中景/全景）、运镜（固定/手持微晃/缓推/跟拍/环绕）、"
        "服装主色（在角色卡允许范围内调换主色或外套）、构图角度（平视/俯拍/仰拍/斜角/过肩）」"
        "五个维度各随机抽取一项，组成与已生成条目至少 3 项不同的新组合；"
        "并行生成的多条视频彼此也须采用不同组合，严禁输出与已有条目雷同的画面。",
        "音频字幕：中文情感 AI 配音，口型与人声画面尽量对齐；不配剧名/主角名口播；画面内不生成剧名字幕条；"
        "其余剧情字幕仅限单行短句、每行≤6 字，底部居中，加粗白字 + 黑色粗描边，单条字幕时长≥1.5 秒，"
        "禁止闪烁、多层堆叠。短信类内容改旁白代读、屏幕虚化，不渲染长文字。",
        "结尾处理：结尾按剧情正常演绎自然收束，不做静止/淡出定格，不加无意义空镜"
        "（剧名字幕条由后期烧录叠加，不占用正片时长）。",
        "画质 8K 超写实，皮肤纹理细腻自然，镜头稳定无抖动。",
        "负面约束：禁止五官崩坏变脸、肢体畸形、手指异常、发型服装错乱；禁止与同项目已生成条目画面雷同；"
        "禁止画面出现点赞、关注、评论等互动引导贴纸图标；禁止出现任何平台名称、平台水印样式、二维码、"
        "站外引导标识与疑似水印元素；与剧情无关的水印文字一律不得出现；禁止花哨快切转场、过度滤镜、"
        "画面剧烈晃动；禁止任何错别字、乱码、变形文字，画面文字元素最少化，无法确保文字正确时宁可无字；"
        "禁止全程单一机位长镜头、禁止镜头少于 3 个、禁止仅面部特写无肢体冲突。 9:16，10s",
    ])


@pytest.fixture(scope="module")
def expand_text() -> str:
    assert EXPAND_TEMPLATE.exists(), f"展开模板缺失：{EXPAND_TEMPLATE}"
    return EXPAND_TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def copy_text() -> str:
    assert COPY_TEMPLATE.exists(), f"文案模板缺失：{COPY_TEMPLATE}"
    return COPY_TEMPLATE.read_text(encoding="utf-8")


# ─────────────  1. 骨架：模板字面执行的产物必须过 check_prompt_skeleton  ─────────────

def test_canonical_prompt_passes_skeleton():
    sk = svc.check_prompt_skeleton(_canonical_prompt())
    assert sk["ok"] is True, f"按模板拼的提示词被判缺行：{sk['missing']}"


def test_expand_template_names_every_skeleton_keyword(expand_text):
    """八个骨架关键词必须在模板里被点名——不点名，模型就知道「标签可以省」。"""
    missing = [k for k in svc.PROMPT_SKELETON_KEYS if k not in expand_text]
    assert not missing, f"模板再也没要求输出这些骨架行：{missing}"


def test_skeleton_fails_without_line_labels():
    """反证：把「音频字幕：」「负面约束：」两个标签抹掉，判据必须立刻缺行。

    这条断言存在的意义就是 ① 号断裂——内容意思都在，标签没写，照样判废。
    """
    no_labels = (
        _canonical_prompt()
        .replace("音频字幕：中文情感 AI 配音", "中文情感 AI 配音")
        .replace("负面约束：禁止五官崩坏变脸", "禁止五官崩坏变脸")
    )
    sk = svc.check_prompt_skeleton(no_labels)
    assert sk["ok"] is False and set(sk["missing"]) == {"音频", "负面"}, sk


# ─────────────  2. 漂移：钩子原文行必须被 judge_drift 认下来  ─────────────

def test_canonical_prompt_has_no_drift():
    dr = svc.judge_drift(COPY, _canonical_prompt())
    assert dr["drift"] is False, f"「钩子原文：<文案>」这种写法被判漂移：{dr['reasons']}"


def test_copy_wrapped_in_brackets_is_drift():
    """模板明令不许用括号包住原句；判据也必须真的拦得住（防模板与代码口径漂移）。"""
    dr = svc.judge_drift(COPY, "【钩子原文：" + COPY + "】\n画质 8K")
    assert dr["drift"] is True, dr


def test_copy_written_twice_is_drift():
    dr = svc.judge_drift(COPY, f"钩子原文：{COPY}\n剧情：{COPY}")
    assert dr["drift"] is True and any("两次" in r or "2" in r for r in dr["reasons"]), dr


# ─────────────  3. 执行要求：不进 payload，只进 dispatch_note  ─────────────

def test_canonical_prompt_carries_no_dispatch_line():
    _body, moved = svc.split_dispatch_note(_canonical_prompt())
    assert not moved, f"骨架里混进了投放要求（会被当画面描述生成）：{moved}"


def test_expand_template_keeps_dispatch_note_out_of_prompt(expand_text):
    assert "dispatch_note" in expand_text, "模板不再输出 dispatch_note 字段"
    assert "不把投放要求写进 `prompt_text`" in expand_text


def test_dispatch_line_moved_out_of_body():
    body, moved = svc.split_dispatch_note("画质 8K\n执行要求：生成后重命名视频")
    assert body == "画质 8K" and "重命名" in moved


# ─────────────  4. 形态判据：模板说的「首句」＝代码切的那一刀  ─────────────

def test_copy_shape_of_the_sample_passes():
    sh = svc.check_copy_shape(COPY)
    assert sh["ok"] is True, sh
    assert sh["first_clause"] == "前3秒：她替姐姐嫁的第二天", sh["first_clause"]


def test_dunhao_does_not_end_the_first_clause():
    """② 号断裂的闸门：顿号**不算**断句，写「前3秒：甲、后7秒：乙」整行都是首句。"""
    sh = svc.check_copy_shape("前3秒：她替姐姐嫁的第二天、后7秒：新郎出现在她姐的婚礼上")
    assert sh["ok"] is False and "首句" in "；".join(sh["problems"]), sh


def test_copy_template_tells_the_model_dunhao_does_not_count(copy_text):
    assert "顿号" in copy_text and "不算断句" in copy_text, "模板没把顿号口径写给模型"
    assert "。！？；，" in copy_text, "模板里的首句定义与 check_copy_shape 的切分集不一致"


def test_copy_template_forbids_trailing_comma(copy_text):
    assert "不得以逗号、顿号结尾" in copy_text


# ─────────────  5. 编号：三处必带，缺号写法两边同一个词  ─────────────

def test_expand_template_uses_the_same_missing_code_word_as_export(expand_text):
    """导出侧写「缺编号」（format_export_block），模板不能再写「未取号」。"""
    assert "缺编号" in expand_text
    assert "未取号" not in expand_text, "模板与导出侧的缺号措辞又分家了"


def test_titles_get_code_appended_only_when_absent():
    with_code = svc.format_titles_with_code([f"疙瘩汤·{HOOK_CODE}·替姐出嫁第二天"], HOOK_CODE)
    without = svc.format_titles_with_code(["疙瘩汤·替姐出嫁第二天"], HOOK_CODE)
    assert with_code == [f"1. 疙瘩汤·{HOOK_CODE}·替姐出嫁第二天"], with_code
    assert without == [f"1. 疙瘩汤·替姐出嫁第二天（{HOOK_CODE}）"], without


# ─────────────  6. 推荐标题长度预算：不带【账号】前缀 ≤18 字  ─────────────

@pytest.mark.parametrize("title", [
    "疙瘩汤·7D0B2·替姐出嫁第二天",       # 剧缩3＋·＋编号5＋·＋精简钩子7 ＝ 17
    "怀三胎·7G101·刚离婚就孕吐",         # 剧缩3＋编号5＋爆点6 ＝ 16
])
def test_compliant_title_fits_the_22_char_report_column(title):
    n = svc.count_copy_chars(title)
    assert n <= 18, f"模板口径下这条 {n} 字已超预算：{title}"
    assert n + 4 <= 22, f"发布侧补 4 字【账号】前缀后超报表 22 字列：{title}"


@pytest.mark.parametrize("body", [
    "怀三胎·7G101·刚离婚就孕吐，他撕碎协议",   # 11-02 §3.1 示例正文 22 字
    "救总裁·7G0B6·会上干呕，全集团炸了",       # 同上，示例正文 20 字
])
def test_doc_example_bodies_stay_over_our_budget(body):
    """留档一条对版发现：11-02 §3.1 的**示例**比它自己的**预算**长。

    示例正文 20~22 字 → 补 4 字【账号】前缀是 24~26 字，超出「全标题 ≤22」；
    带 8 字前缀的【RIOOIR】那条实测 28 字，连 ≤27 档也越了。模板按**预算**收紧
    （正文 ≤18），所以这些示例必须被判超——哪天这条断言变绿，说明有人拿示例
    当长度依据把闸门放宽了。
    """
    assert svc.count_copy_chars(body) > 18, body


def test_expand_template_states_the_18_char_budget(expand_text):
    assert "正文 ≤18 字" in expand_text, "模板还写着带前缀的 22 字，模型会超"
    assert "算不到一起" in expand_text, "模板没记下 11-02 示例与预算打架"
    assert "精简钩子上限＝11－剧缩字数" in expand_text
    # 「6~12 字」只允许以**被推翻的旧口径**出现；哪天它回到操作行，等于把冲突写回来
    for line in expand_text.splitlines():
        if "6~12 字" in line:
            assert "算不到一起" in line, f"固定区间又被当成规则用了：{line}"


@pytest.mark.parametrize("abbr,clause,max_clause", [
    ("疙瘩汤", "替姐出嫁第二天", 8),    # 11－3
    ("一胎四宝", "婆婆跪在产房外", 7),   # 11－4
])
def test_title_formula_budget_is_self_consistent(abbr, clause, max_clause):
    """剧缩越长，留给精简钩子的字数越少——按公式拼出来的标题必须仍在 18 字内。"""
    title = f"{abbr}·{HOOK_CODE}·{clause}"
    assert len(clause) <= max_clause, (clause, max_clause)
    assert svc.count_copy_chars(title) <= 18, title
    assert svc.count_copy_chars(title) + 4 <= 22, title


def test_expand_template_no_longer_fixes_titles_at_five(expand_text):
    """11-02：K＝号数，不再固定 5 条（兜底 5 条必须同时写 deviation_note）。"""
    assert "推荐标题条数 K" in expand_text
    assert "K 缺失时出 5 条" not in expand_text


# ─────────────  7. 1020 起取消的两样东西不许回流  ─────────────

def test_no_project_title_line_and_no_publish_tags(expand_text):
    assert "不输出「项目标题」行" in expand_text
    assert "不写「📌 发布标签」" in expand_text, "模板没把「不输出发布标签」写明"
