"""lan_source 独立包：SQLAlchemy 声明式 Base。

设计要点（与 wechat_download 一致「并入 + 可剥离」）：
- 本包自持独立 Base（不继承 app.database.Base），保证未来剥离成独立系统时
  lan_source 完全自包含（自有 models/Base/迁移），不依赖主系统 ORM。
- 并入形态下，表结构与主系统共用同一个 PostgreSQL 实例，由本包迁移脚本
  （alembic 0031）负责建表；运行期通过主系统注入的 AsyncSession 读写。
"""

from sqlalchemy.orm import DeclarativeBase


class LanSourceBase(DeclarativeBase):
    """lan_source 独立 ORM Base."""

    pass
