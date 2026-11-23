"""assets API 域包（M 级拆包·刀①壳，2026-11-18）。

设计依据：``docs/M级设计-assets拆包与投板恢复巡检-20261114.md`` §1.1/§1.2。

刀①口径：**行为零变，先验聚合机制**。
- 原 ``backend/app/api/assets.py`` 的 14436 行原样挪进本包的 ``misc.py``
  （md5 逐位相同，见刀① commit）；
- 本 ``__init__.py`` 只做聚合，把 ``misc`` 的全部符号（含下划线开头的
  ``_call_autoclip`` 等被测试 ``patch("app.api.assets._call_autoclip")``
  直接点名的符号）透传进包命名空间——保证 ``main.py`` 的
  ``from app.api.assets import router`` 一字不改，测试的 patch 目标路径
  ``app.api.assets.<sym>`` 也一字不改；
- ``sweep_interrupted_asset_jobs`` 被 ``main.py:120`` 延迟 import，单独显式
  转发，避免反射转发遗漏。

后续刀②~刀④会把 ``misc.py`` 里的域路由逐刀搬到同包下的
``prompt_elements.py`` / ``summaries.py`` 等，每刀一个 commit、独立过三道门，
任何一刀红即可 revert 该刀，本聚合壳不受影响（§1.4 回滚口径）。
"""

# 1) 先载入 misc 模块本体，拿到全部符号
from app.api.assets import misc as _misc

# 2) 反射式转发 misc 的全部模块级符号（含下划线开头）到包命名空间。
#    这是刀①「对外零破坏」的关键：测试的 ``patch("app.api.assets._xxx")``
#    与 ``from app.api.assets import _xxx`` 都依赖包级能直接命中这些符号。
#    不设 ``__all__``：包对外可见性以「本模块命名空间实际存在的名字」为准，
#    与原单文件 assets.py 的可见性完全一致。
for _name in dir(_misc):
    if _name.startswith("__"):
        continue
    # 反射转发：把 misc 的每个公开/半公开符号绑定到本包命名空间
    globals()[_name] = getattr(_misc, _name)
del _name

# 3) 显式别名：对外契约最关键的两个符号，冗余钉一次，防止反射层万一调整
from app.api.assets.misc import router  # noqa: F401
from app.api.assets.misc import sweep_interrupted_asset_jobs  # noqa: F401
