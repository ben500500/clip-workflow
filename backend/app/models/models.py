"""ORM 模型门面（兼容导出层）。

Phase 1 上帝类拆分：原「上帝类」models.py（1156 行 / 42+ 模型）已按业务域拆分为多个独立模块：

- user.py       → 用户/认证域（UserRole / User / UserSession / UserPreference 及数据隔离辅助）
- material.py   → 素材/项目/切片域（Project / Episode / SliceTask / ClipCandidate / ...）
- publish.py    → 发布域（VideoAccount / MiniProgram / PublishTask / PublishBatch / ...）
- dashboard.py  → 看板/指标域（VideoMetric / AdMetric / DramaMetric / FunnelSnapshot / ...）
- audit.py      → 审计域（AuditLog / PublishAudit / LoginAudit / CookieAccessLog）
- monitor.py    → 监控/告警/风控域（WorkerNode / AlertRule / AlertEvent / RiskEvent）
- shortdrama.py → 短片制作域（ShortdramaPrompt / WatermarkTask / WatermarkVideo）

本文件作为**门面（facade）**，统一 re-export 全部模型与辅助函数，
保证所有既有 `from app.models.models import ...` 用法零改动、向后兼容。
同时确保所有模型模块被导入，SQLAlchemy 字符串关系与 Base.metadata 完整注册。

注意：
- 各域模块之间通过 SQLAlchemy 字符串关系名（如 "PublishTask"）跨模块关联，
  SQLAlchemy 基于全局 class registry 在 mapper 配置时解析，因此无需模块级循环 import。
- alembic/env.py 通过 `from app.models import models` 触发本文件，从而注册全部模型。
"""
from app.models.user import (
    UserRole,
    ROLE_DISPLAY_NAMES,
    DEFAULT_DATA_SCOPE,
    default_data_scope_for_role,
    user_can_access_all_materials,
    User,
    UserSession,
    UserPreference,
)
from app.models.material import (
    Project,
    Episode,
    AutoClipProject,
    AutoClipRun,
    ClipCandidate,
    DetectedInterval,
    SliceTask,
    SliceOutput,
    Publication,
    SystemConfig,
    PlatformProfile,
    ImportTemplate,
    ImportHistory,
    BatchSlice,
    BatchSliceItem,
)
from app.models.publish import (
    VideoAccount,
    MiniProgram,
    PublishBatch,
    PublishTask,
    PublishProfile,
    PublishMaterial,
    PublishTimeSlot,
)
from app.models.dashboard import (
    VideoMetric,
    MiniProgramMetric,
    AdMetric,
    DramaMetric,
    FunnelSnapshot,
    EcosystemMetric,
)
from app.models.audit import (
    AuditLog,
    PublishAudit,
    LoginAudit,
    CookieAccessLog,
)
from app.models.monitor import (
    WorkerNode,
    AlertRule,
    AlertEvent,
    RiskEvent,
)
from app.models.shortdrama import (
    ShortdramaPrompt,
    WatermarkTask,
    WatermarkVideo,
)
from app.models.channel import (
    ChannelAccount,
    ChannelOperator,
)

__all__ = [
    # 用户/认证
    "UserRole",
    "ROLE_DISPLAY_NAMES",
    "DEFAULT_DATA_SCOPE",
    "default_data_scope_for_role",
    "user_can_access_all_materials",
    "User",
    "UserSession",
    "UserPreference",
    # 素材/项目/切片
    "Project",
    "Episode",
    "AutoClipProject",
    "AutoClipRun",
    "ClipCandidate",
    "DetectedInterval",
    "SliceTask",
    "SliceOutput",
    "Publication",
    "SystemConfig",
    "PlatformProfile",
    "ImportTemplate",
    "ImportHistory",
    "BatchSlice",
    "BatchSliceItem",
    # 发布
    "VideoAccount",
    "MiniProgram",
    "PublishBatch",
    "PublishTask",
    "PublishProfile",
    "PublishMaterial",
    "PublishTimeSlot",
    # 看板/指标
    "VideoMetric",
    "MiniProgramMetric",
    "AdMetric",
    "DramaMetric",
    "FunnelSnapshot",
    "EcosystemMetric",
    # 审计
    "AuditLog",
    "PublishAudit",
    "LoginAudit",
    "CookieAccessLog",
    # 监控/告警/风控
    "WorkerNode",
    "AlertRule",
    "AlertEvent",
    "RiskEvent",
    # 短片制作
    "ShortdramaPrompt",
    "WatermarkTask",
    "WatermarkVideo",
    # 视频号台账
    "ChannelAccount",
    "ChannelOperator",
]
