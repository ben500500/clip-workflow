#!/usr/bin/env python3
"""
seed_llm_config.py — 补齐模型热更所需的系统配置种子行（幂等）

背景（遗留问题⑤）：
  仓库 HEAD 已具备完整的模型热更链路：
    system_config 表行 -> _merge_default_autoclip_config -> autoclip_service payload
    -> autoclip main.py 运行时 env 覆盖 + set_runtime_model。
  但 40 生产库 system_config 表中 llm_config / frame_analysis_config 两行为空，
  界面上没有可编辑入口，热更能力形同缺失。

本脚本只做 insert-if-missing：
  - key 已存在 -> 跳过（绝不覆盖，用户可能在界面改过值）；
  - key 缺失   -> 插入 DEFAULT_CONFIGS 同源的默认值；
  - llm_api_key / vision_api_key 留空：沿用部署侧 .env 的 LLM_API_KEY，避免密钥明文入库；
  - 行为空不影响运行：_merge_default_autoclip_config 只读存在的行，缺失即回退 .env，
    因此本脚本零风险（种下去只是让界面出现可编辑入口）。

用法（backend 容器内运行，复用其 app 包与 DATABASE_URL）：
  docker compose cp scripts/seed_llm_config.py backend:/app/seed_llm_config.py
  docker compose exec backend python /app/seed_llm_config.py
"""
import asyncio
import json
import os

import asyncpg

# 直接从代码 DEFAULT_CONFIGS 导入（backend 容器内运行，永远与代码同源）：
# 覆盖 default_autoclip_config（含 duration_hard_limit 开关）/ llm_config /
# frame_analysis_config / dupload_config 等全部系统配置种子。
try:
    from app.api.config import DEFAULT_CONFIGS as SEEDS
except ImportError as e:  # 兜底：脱离 app 包运行时仅播两个核心 LLM key
    print(f"WARN: 无法导入 DEFAULT_CONFIGS（{e}），回退内置最小种子")
    SEEDS = [
        {
            "key": "llm_config",
            "value": {
                "llm_api_base": "https://apihub.agnes-ai.com/v1",
                "llm_model": "",
                "llm_api_key": "",
            },
            "description": "在线 LLM 网关配置（JSON）",
        },
        {
            "key": "frame_analysis_config",
            "value": {
                "provider": "ollama",
                "model": "agnes-2.0-flash",
                "vision_base": "https://apihub.agnes-ai.com/v1",
                "vision_api_key": "",
            },
            "description": "画面理解（Frame Analysis）配置（JSON）",
        },
    ]


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL 未设置")
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        exists = await conn.fetchval("SELECT to_regclass('system_config')")
        if not exists:
            raise SystemExit("system_config 表不存在（应由 alembic 迁移创建），终止")
        inserted, skipped = [], []
        for seed in SEEDS:
            row = await conn.fetchrow(
                "SELECT key FROM system_config WHERE key = $1", seed["key"]
            )
            if row:
                skipped.append(seed["key"])
                continue
            desc = (seed.get("description") or "")[:500]  # 列宽 varchar(500)，超长截断
            await conn.execute(
                "INSERT INTO system_config (key, value, description, updated_at) "
                "VALUES ($1, $2::jsonb, $3, now())",
                seed["key"],
                json.dumps(seed["value"], ensure_ascii=False),
                desc,
            )
            inserted.append(seed["key"])
        print(f"SEED_DONE inserted={inserted} skipped(已存在,不覆盖)={skipped}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
