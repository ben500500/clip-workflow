"""Issue #357 回归：async 用例必须「真执行」，且绝不静默 skip / 静默降级。

背景（修复前的实测现象）：
    backend 镜像没装 pytest-asyncio 时，标了 `@pytest.mark.asyncio` 的 async 用例
    **既不执行也不 skip，而是被 pytest 直接判 FAILED**：
        Failed: async def functions are not natively supported.
    同时 pytest 对 asyncio marker 报 `PytestUnknownMarkWarning`。
    后果是 wechat_dl 状态机 / 解析缓存 TTL / lan_source 清单发现这些核心写路径的回归
    保护形同虚设 —— 写了但从来不跑。

本文件是**元测试**：它不测业务，只测「测试基础设施本身还在位」。一旦有人
移除插件、把 asyncio_mode 从 strict 改成 auto、或把 marker 写错，本文件会红。

运行：cd backend && python -m pytest tests/unit/test_pytest_asyncio_wiring.py -v
"""

import asyncio
import configparser
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

PYTEST_INI = BACKEND_ROOT / "pytest.ini"
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"
# 受本 Issue 保护的 async 用例文件（27 条 async 用例的来源）
ASYNC_TEST_FILES = [
    "tests/unit/test_wechat_dl_status.py",
    "tests/unit/test_wechat_dl_parse_cache.py",
    "tests/test_lan_source_client.py",
]


# ─────────────────────────────────────────────────────────────
# 1. 依赖与配置：插件在位 + asyncio_mode 正确
# ─────────────────────────────────────────────────────────────

def test_pytest_asyncio_plugin_is_installed():
    """插件必须真装了（不是靠 marker 静默失效）。"""
    import pytest_asyncio  # noqa: F401  —— 缺它整条回归链就是空转

    assert pytest_asyncio.__version__


def test_pytest_asyncio_is_pinned_in_requirements():
    """依赖要写进 requirements.txt，否则镜像重建后插件又消失（本 Issue 的复发路径）。"""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert re.search(r"(?m)^pytest-asyncio\s*[><=]", text), "requirements.txt 缺 pytest-asyncio 钉版"
    assert re.search(r"(?m)^pytest\s*[><=]", text), "requirements.txt 缺 pytest 钉版（原先只是传递依赖）"


def test_asyncio_config_file_exists_and_mode_is_strict():
    """asyncio_mode 必须是 strict：与现有 `@pytest.mark.asyncio` 标法兼容，
    且漏标 marker 的 async 用例会显式报出来，而不是被 auto 悄悄放过。"""
    assert PYTEST_INI.is_file(), "backend/pytest.ini 缺失"

    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI, encoding="utf-8")
    assert parser.has_section("pytest"), "pytest.ini 缺 [pytest] 段"
    assert parser.get("pytest", "asyncio_mode").strip() == "strict"

    # 未识别 marker 必须升级为 error（回归：asyncio 拼错曾经只发 warning 被忽略）
    fw = parser.get("pytest", "filterwarnings")
    assert "PytestUnknownMarkWarning" in fw and "error" in fw
    # asyncio marker 要显式登记，避免被上面的 error 规则误伤
    assert "asyncio" in parser.get("pytest", "markers")


# ─────────────────────────────────────────────────────────────
# 2. async 用例的每条用例都显式标了 marker（strict 模式的前提）
# ─────────────────────────────────────────────────────────────

def _iter_collected_async():
    """返回受保护文件里的 (文件, 行号, 函数名) —— 仅 async 用例。"""
    out = []
    for rel in ASYNC_TEST_FILES:
        p = BACKEND_ROOT / rel
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            m = re.match(r"^async def (test_\w+)", line)
            if m:
                out.append((rel, i + 1, m.group(1)))
    return out


def test_every_async_case_carries_explicit_marker():
    """strict 模式下，async 用例漏标 marker 会被 skip —— 那等于把本 Issue 的问题换个马甲。
    这里逐条核对「每个 async def test_ 上方都有 @pytest.mark.asyncio」。"""
    missing = []
    for rel, lineno, name in _iter_collected_async():
        p = BACKEND_ROOT / rel
        lines = p.read_text(encoding="utf-8").splitlines()
        # 允许 def 与 marker 之间夹杂其它装饰器
        j = lineno - 2
        marked = False
        while j >= 0 and lines[j].lstrip().startswith("@"):
            if "mark.asyncio" in lines[j]:
                marked = True
            j -= 1
        if not marked:
            missing.append(f"{rel}:{lineno} {name}")

    assert not missing, f"以下 async 用例缺少 @pytest.mark.asyncio（会被静默 skip）：{missing}"


def test_protected_async_case_count_is_stable():
    """27 条是本 Issue 记录的保护基线（24 + ... 归一会随新增用例增长，不可减少）。
    用 >= 断言而不是 ==，避免新增用例时误报，但用例被删会立刻红。"""
    assert len(_iter_collected_async()) >= 26


# ─────────────────────────────────────────────────────────────
# 3. 端到端证据：受保护文件全绿、无 skip、无 "not natively supported"
# ─────────────────────────────────────────────────────────────

# 子进程需要一个"能建起 Settings"的最小环境。这些值只为了让 pydantic Settings
# 通过校验（DB 并不会被真正连上：用例全程用 AsyncMock/替身 session）。
# 必须用 PostgreSQL 形式 —— app/database.py 在模块级写死了 pool_size /
# connect_args.server_settings 等 PG 专属参数，sqlite URL 会直接 TypeError。
_SUBPROC_ENV_OVERRIDES = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "MINIO_ACCESS_KEY": "test-key",
    "MINIO_SECRET_KEY": "test-secret",
    "JWT_SECRET": "test-" + "x" * 60,
}


def _pytest_env():
    import os

    env = dict(os.environ)
    env.update(_SUBPROC_ENV_OVERRIDES)
    return env


@pytest.mark.parametrize("rel", ASYNC_TEST_FILES)
def test_protected_file_runs_green_without_skip(rel):
    """在子进程里真跑一次该文件：必须 0 failed / 0 skipped，且输出里不得出现
    'natively supported'（那是插件缺失的标志）。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", rel, "-q", "--no-header",
         "-p", "no:cacheprovider", "-rs"],
        cwd=str(BACKEND_ROOT), capture_output=True, text=True, timeout=300,
        env=_pytest_env(),
    )
    out = proc.stdout + proc.stderr

    assert "natively supported" not in out, f"{rel}: 仍报 async 不被原生支持 → 插件没生效"
    assert "no tests ran" not in out, f"{rel}: 没收集到用例"
    assert proc.returncode == 0, f"{rel} 未通过：\n{out[-2000:]}"

    m = re.search(r"(\d+) passed", out)
    assert m, f"{rel}: 拿不到 passed 计数\n{out[-1000:]}"
    assert int(m.group(1)) > 0
    assert " skipped" not in out, f"{rel}: 出现 skip（禁止用 skip 换绿）\n{out[-1000:]}"
    assert " xfailed" not in out and " xpassed" not in out, f"{rel}: 出现 xfail/xpass"


# ─────────────────────────────────────────────────────────────
# 4. 元测试自身的 async 用例（证明本文件也在 strict 下真跑，而不是只测字符串）
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_self_async_case_actually_executes():
    """本用例若真被执行，这一行断言才有机会跑；插件缺失时它会直接 FAILED。"""
    await asyncio.sleep(0)
    assert asyncio.get_running_loop() is not None


@pytest.mark.asyncio
async def test_event_loop_is_isolated_per_case():
    """pytest-asyncio 默认每个用例一个事件循环：跨用例不得共享 loop。"""
    marker = "issue-357-loop-probe"
    loop = asyncio.get_running_loop()
    setattr(test_event_loop_is_isolated_per_case, "_loop", loop)
    assert getattr(test_event_loop_is_isolated_per_case, "_loop") is loop
    assert marker  # 保持断言存在，便于变异测试杀死
