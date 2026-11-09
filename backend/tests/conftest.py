"""全仓测试夹具。

11-06 起生产默认 ASSET_HOOK_CANDIDATE_COUNT=1（用户拍板：出文案只出 1 条浓缩一句话）。
但大量存量用例是按「三候选机制」写的断言（推荐条、逐条一致性/风险词各占一条、
prompt-web 按 seq 展开 1/2/3……）。为了不把十几处调用点挨个改成显式 count=3，
这里把**测试基线**统一钉回 3；个别要验「不传 count 默认就是 1」的用例
（test_summary_generate_default_count_is_one）在用例内自行把值改回 1。

注意：settings 不能在 conftest 顶层 import——测试模块在模块体里才补 sys.path 和
环境变量，顶层 import 会让 pydantic-settings 抢跑并报 Field required。
"""

import pytest


@pytest.fixture(autouse=True)
def _three_candidate_baseline(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ASSET_HOOK_CANDIDATE_COUNT", 3, raising=True)
    # A′ 自审自投闸门：11-08 定稿时默认拦（false），11-09 用户口径改为默认放开（true）。
    # 这里仍然**显式钉 true**，不是顺手写的漂亮话：存量用例的标准流程就是
    # 「运营过审→同一运营投产」，哪天有人把默认改回拦，这一钉能让它们照常绿，
    # 而不是让 300 多条用例一起红、把真回归埋在里面。闸门本身由专项用例
    # （隔离矩阵）把值改成 false 单独验证。
    monkeypatch.setattr(settings, "ASSET_SELF_PRODUCE_ALLOWED", True, raising=True)
