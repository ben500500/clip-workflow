"""
飞书（Lark）表格自动爬取服务（ISSUE #142）。

需求：从飞书表格链接自动爬取「剧目 ↔ 剧场」对应关系，手动触发，爬取后自动更新
现有剧目的剧场关联（一剧多剧场）。

数据流：
  POST /dramas/import/feishu （手动触发）→ feishu_service.sync_from_feishu(db)
    → 获取飞书表格数据（公共链接 / Open API 两种方式）
    → 按「剧目名称」匹配现有 dramas
    → 按「剧场」列（可多个，顿号/逗号分隔）查找/创建 theaters
    → 更新 drama_theaters 关联表

访问方式：
1. Open API（推荐、最稳定）：配置 FEISHU_APP_ID / FEISHU_APP_SECRET，
   通过 tenant_access_token 调 `sheets/v2/spreadsheets/{token}/values/{range}` 读表。
2. 公共分享链接：解析出 spreadsheet token；若未配置 app 凭证，仅当表格设为
   「互联网上获得链接的任何人可查看」时可用（走 Open API 但需 app 凭证）。

说明：飞书官方对「匿名读表」无稳定公开接口，故本实现以 Open API 为主；
公共链接用于自动解析出 spreadsheet_token。凭证在 .env 配置。
"""

import asyncio
import logging
import re
from typing import List, Optional
from urllib.parse import urlparse, parse_qs

import httpx
from sqlalchemy import select, delete

from app.config import settings
from app.database import get_db, async_session_factory
from app.models.drama import Drama, DramaTheater, gen_drama_code
from app.models.theater import Theater

logger = logging.getLogger(__name__)

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
TIMEOUT = 30


# ─────────────────────────── 工具 ───────────────────────────

def extract_spreadsheet_token(url: str) -> Optional[str]:
    """从飞书表格分享链接解析出 spreadsheet_token。

    支持形如：
      https://xxx.feishu.cn/sheets/SPREADSHEET_TOKEN?sheet=xxx
      https://xxx.feishu.cn/sheets/SPREADSHEET_TOKEN
      https://xxx.feishu.cn/base/...（多维表格，非本文档表）
    返回 None 表示无法解析。
    """
    if not url or not url.strip():
        return None
    url = url.strip()
    # 形如 .../sheets/{token}?...
    m = re.search(r"/sheets/([A-Za-z0-9_-]{8,})", url)
    if m:
        return m.group(1)
    # 形如 ...?spreadsheet_token=xxx 或 ...?token=xxx
    try:
        q = parse_qs(urlparse(url).query)
        for key in ("spreadsheet_token", "token", "spreadsheetId"):
            if q.get(key):
                return q[key][0]
    except Exception:
        pass
    return None


def _split_theater_names(value) -> List[str]:
    """拆分一个单元格里的多个剧场名（顿号/逗号/斜杠/分号）。"""
    if value is None:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    parts = re.split(r"[、,，/;；\\|]+", raw)
    return [p.strip() for p in parts if p.strip()]


# ─────────────────────────── 飞书数据获取 ───────────────────────────

async def _get_tenant_access_token(client: httpx.AsyncClient) -> Optional[str]:
    """获取飞书 tenant_access_token（需配置 FEISHU_APP_ID / FEISHU_APP_SECRET）。"""
    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        return None
    try:
        resp = await client.post(
            f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": settings.FEISHU_APP_ID,
                "app_secret": settings.FEISHU_APP_SECRET,
            },
            timeout=TIMEOUT,
        )
        data = resp.json()
        if data.get("code") == 0:
            return data.get("tenant_access_token")
        logger.warning("飞书 tenant_access_token 获取失败: %s", data.get("msg"))
    except Exception as e:
        logger.warning("飞书 token 请求异常: %s", e)
    return None


async def fetch_sheet_rows(spreadsheet_token: str, url: Optional[str] = None) -> List[dict]:
    """拉取飞书表格数据，返回「表头→行值」的字典列表。

    通过飞书 Open API 读取首张 sheet 的完整 A1 区域。
    返回 [] 表示未能读取（凭证缺失 / 网络失败 / 表格不可达）。
    """
    if not spreadsheet_token:
        logger.warning("无法从链接解析出飞书 spreadsheet_token")
        return []

    async with httpx.AsyncClient() as client:
        token = await _get_tenant_access_token(client)
        if not token:
            logger.error("未配置 FEISHU_APP_ID/FEISHU_APP_SECRET，无法访问飞书表格（公共分享链接也需 app 凭证走 Open API）")
            return []
        headers = {"Authorization": f"Bearer {token}"}

        # 读取表信息拿到首个 sheetId 与标题
        meta_resp = await client.get(
            f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/metainfo",
            headers=headers,
            timeout=TIMEOUT,
        )
        meta = meta_resp.json()
        if meta.get("code") != 0:
            logger.warning("飞书 metainfo 获取失败: %s", meta.get("msg"))
            return []
        sheets = (meta.get("data", {}).get("sheets") or [])
        if not sheets:
            logger.warning("飞书表格无 sheet")
            return []
        sheet_id = sheets[0].get("sheet_id")

        # 读取数据（A1 区域，最多 5000 行）
        values_resp = await client.get(
            f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values/{sheet_id}!A1:Z5000",
            headers=headers,
            timeout=TIMEOUT,
        )
        vdata = values_resp.json()
        if vdata.get("code") != 0:
            logger.warning("飞书 values 获取失败: %s", vdata.get("msg"))
            return []
        value_range = vdata.get("data", {}).get("valueRange", {})
        grid = value_range.get("values") or []
        if not grid:
            return []

        # 第一行为表头
        header = [str(c).strip() if c is not None else "" for c in grid[0]]
        rows = []
        for raw in grid[1:]:
            if not raw:
                continue
            row = {}
            for i, col in enumerate(header):
                val = raw[i] if i < len(raw) else None
                row[col] = val
            rows.append(row)
        return rows


# ─────────────────────────── 同步逻辑 ───────────────────────────

async def sync_from_feishu(url: Optional[str] = None) -> dict:
    """手动触发的入口：拉取飞书表格并更新现有剧目的剧场关联。

    返回同步结果统计。此函数独立创建数据库会话（供 Celery/独立调用），
    不依赖 FastAPI 的 get_db 依赖。
    """
    sheet_url = url or settings.FEISHU_SPREADSHEET_URL
    if not sheet_url or not sheet_url.strip():
        return {"success": False, "error": "未配置飞书表格链接（FEISHU_SPREADSHEET_URL 或请求参数 url）"}

    spreadsheet_token = extract_spreadsheet_token(sheet_url)
    if not spreadsheet_token:
        return {"success": False, "error": f"无法从链接解析出 spreadsheet_token: {sheet_url}"}

    rows = await fetch_sheet_rows(spreadsheet_token, sheet_url)
    if not rows:
        return {"success": False, "error": "未能读取飞书表格数据（检查 FEISHU_APP_ID/SECRET 及表格权限）"}

    # 定位列
    drama_col = _find_col(rows[0], settings.FEISHU_DRAMA_COL)
    theater_col = _find_col(rows[0], settings.FEISHU_THEATER_COL)
    if not drama_col or not theater_col:
        return {"success": False, "error": f"飞书表缺少必需列（剧目名称列={drama_col}，剧场列={theater_col}），请检查表头"}

    updated = 0
    matched = 0
    errors = []

    async with async_session_factory() as db:
        try:
            for row in rows:
                drama_name = str(row.get(drama_col) or "").strip()
                if not drama_name:
                    continue
                theater_value = row.get(theater_col)
                # 通过唯一 name 匹配现有剧目（仅更新存量，不新建）
                result = await db.execute(select(Drama).where(Drama.name == drama_name))
                d = result.scalar_one_or_none()
                if not d:
                    continue  # 飞书表里的剧目不在库中，跳过（不自动新建）
                matched += 1
                theater_names = _split_theater_names(theater_value)
                # 查找/创建 theaters
                theater_ids = []
                for tname in theater_names:
                    tres = await db.execute(select(Theater).where(Theater.name == tname))
                    t = tres.scalar_one_or_none()
                    if t:
                        theater_ids.append(t.id)
                    else:
                        t = Theater(name=tname)
                        db.add(t)
                        await db.flush()
                        theater_ids.append(t.id)
                await _sync_theaters(db, d, theater_ids)
                updated += 1
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error("飞书同步失败: %s", e, exc_info=True)
            errors.append(str(e))

    return {
        "success": not errors,
        "matched": matched,
        "updated": updated,
        "errors": errors,
        "message": f"飞书同步完成：匹配 {matched} 条存量剧目，更新 {updated} 条剧场关联",
    }


def _find_col(header_row: dict, target: str) -> Optional[str]:
    """在表头行中按目标列名（含模糊匹配）定位实际列名。"""
    target = (target or "").strip()
    if not target:
        return None
    for col in header_row:
        if target in str(col):
            return col
    # 兜底：常见别名
    aliases = {
        "剧目名称": ["剧目", "剧名", "名称"],
        "剧场": ["所属剧场", "剧场名"],
    }
    for alias in aliases.get(target, []):
        for col in header_row:
            if alias in str(col):
                return col
    return None


async def _sync_theaters(db, drama: Drama, theater_ids: List):
    """同步单个剧目的剧场关联（清旧写新，幂等）。"""
    await db.execute(delete(DramaTheater).where(DramaTheater.drama_id == drama.id))
    if theater_ids:
        # 去重保序
        seen = set()
        for tid in theater_ids:
            if tid in seen:
                continue
            seen.add(tid)
            db.add(DramaTheater(drama_id=drama.id, theater_id=tid))
        drama.theater_id = theater_ids[0]
    else:
        drama.theater_id = None
