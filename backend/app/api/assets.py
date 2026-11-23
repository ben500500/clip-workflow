"""⚠️ 已停用（2026-11-23 S0'）：素材库 API 已迁到同名的 ``assets/`` 包，本文件是历史壳。

为什么留着而不是直接删：拆包刀①（2026-11-18）把这份 14,436 行原样搬进
``backend/app/api/assets/misc.py``，本文件从此**不再被任何 import 命中**——Python 在
同名「模块文件 vs 包目录」之间优先选**包**，所以 ``import app.api.assets`` 解析到
``assets/__init__.py``（反射聚合壳），本文件只是躺在盘上的旧副本。

它带来的实际风险（本轮实测）：
1. **两份并存只会越差越大**——11-23 本地已差 15 行（misc.py 14,461 vs 本文件 14,436），
   任何"从 git 全新 checkout"的读者都会以为改这里有效，实际改了不生效且不报错；
2. 静态守卫（``tests/unit/test_asset_library.py::test_no_model_wait_with_unended_session_activity``
   G-1）会把它和 misc.py 当成两个文件各扫一遍，同一段代码被点名两次（豁免名单漂移红）；
3. 它是最容易被误 patch / 误 grep 的目标（``grep -n`` 命中它，人会去改死代码）。

按 M 级设计 §1.4 的口径「先改成告警壳、刀②再删」，本文件保留为壳：
**若有一天有人用 importlib 按文件路径强行加载它**（绕过包优先规则），会立刻看到警告；
正常 import 永远不会走到这里。真正的实现只有一处：
``backend/app/api/assets/misc.py``（刀②~刀④ 会再按域拆成 summaries.py / prompt_elements.py 等）。

迁移对应关系（旧 → 新）：本文件全部 14,436 行 → ``assets/misc.py`` 的**同源代码**，
增量为 11-23 之前的 15 行（原片素材入库归一化 720P@30，commit ``1f906cb``）。
"""

import warnings

warnings.warn(
    "app.api.assets 模块文件已停用：实现已迁到 app.api.assets 包（assets/misc.py）。"
    "本文件只是历史壳，改它不会生效——请改 backend/app/api/assets/misc.py。",
    DeprecationWarning,
    stacklevel=2,
)

# 兜底转发：万一被按文件路径加载（正常 import 走不到），至少还能拿到包里的符号。
# 不写 `import *`：包是反射聚合壳，`*` 会拖进 300+ 个名字且不利于静态分析。
try:
    from app.api.assets import router  # noqa: F401  对外契约唯一必需的名字
except Exception:  # noqa: BLE001 —— 壳文件的存在意义不包含"保证可加载"
    pass
