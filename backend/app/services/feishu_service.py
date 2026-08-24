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

访问方式（Open API，需配置 FEISHU_APP_ID / FEISHU_APP_SECRET）：
1. 普通电子表格：`/sheets/{token}` 链接，走 `sheets/v2` 读首表 A1 区域。
2. 多维表格（Bitable）：`/base/{app_token}` 直链，或 `/wiki/{wiki_token}` 知识库链接
   （内部为多维表格，带 `?sheet={table_id}`），走 `bitable/v1` 列数据表并分页读记录。

说明：飞书官方对「匿名读表」无稳定公开接口，故本实现以 Open API 为主；
公共链接用于自动解析出 token。凭证在 .env 配置。
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
    """从飞书表格分享链接解析出 spreadsheet_token（普通电子表格）。

    支持形如：
      https://xxx.feishu.cn/sheets/SPREADSHEET_TOKEN?sheet=xxx
      https://xxx.feishu.cn/sheets/SPREADSHEET_TOKEN
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
        for key in ("spreadsheet_token", "spreadsheetId"):
            if q.get(key):
                return q[key][0]
    except Exception:
        pass
    return None


def parse_feishu_url(url: str) -> Optional[dict]:
    """解析飞书链接，返回统一的来源描述。

    支持三类：
      - spreadsheet：普通电子表格，`/sheets/{token}?sheet=xxx`
      - bitable：多维表格直链，`/base/{app_token}?table={table_id}`
      - wiki：知识库 wiki 节点（内部为多维表格），`/wiki/{wiki_token}?sheet={table_id}`

    返回形如：
      {"type": "spreadsheet", "token": "xxx", "sheet_id": "9dbac7"}
      {"type": "bitable", "token": "xxx", "sheet_id": "9dbac7"}
      {"type": "wiki", "token": "xxx", "sheet_id": "9dbac7"}
    无法识别时返回 None。
    """
    if not url or not url.strip():
        return None
    url = url.strip()
    # query 里的 sheet / table 参数（多维表格里常用来定位具体数据表）
    sheet_id = None
    try:
        q = parse_qs(urlparse(url).query)
        sheet_id = (q.get("sheet") or q.get("table") or [None])[0]
        if sheet_id == "":
            sheet_id = None
    except Exception:
        sheet_id = None

    # 普通电子表格
    m = re.search(r"/sheets/([A-Za-z0-9_-]{8,})", url)
    if m:
        return {"type": "spreadsheet", "token": m.group(1), "sheet_id": sheet_id}
    # 多维表格直链
    m = re.search(r"/base/([A-Za-z0-9_-]{8,})", url)
    if m:
        return {"type": "bitable", "token": m.group(1), "sheet_id": sheet_id}
    # 知识库 wiki 节点
    m = re.search(r"/wiki/([A-Za-z0-9_-]{8,})", url)
    if m:
        return {"type": "wiki", "token": m.group(1), "sheet_id": sheet_id}
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


def _bitable_value_to_str(value) -> str:
    """把 Bitable 单元格值转成可分割的字符串。

    Bitable 字段值形态多样：纯文本(str/int/float)、多选文本数组、
    对象(dict，如人员/引用字段)。统一摊平成字符串，方便 _split_theater_names 分割。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "是" if value else ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        # 多选文本/数组：逐项摊平后逗号连接（逗号会被 _split_theater_names 再切回）
        parts = [
            _bitable_value_to_str(v)
            for v in value
            if _bitable_value_to_str(v)
        ]
        return "、".join(parts)
    if isinstance(value, dict):
        # 对象字段：优先取 name / text / value / id 等常见展示键
        for key in ("text", "name", "value", "title"):
            if key in value:
                return _bitable_value_to_str(value[key])
        return str(value)
    return str(value)


async def _wiki_node_to_obj(client: httpx.AsyncClient, headers: dict, wiki_token: str) -> Optional[dict]:
    """解析 wiki 节点，返回 {obj_token, obj_type}。"""
    try:
        resp = await client.get(
            f"{FEISHU_API_BASE}/wiki/v2/spaces/get_node?token={wiki_token}",
            headers=headers,
            timeout=TIMEOUT,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.warning("飞书 wiki get_node 解析失败: %s", data.get("msg"))
            return None
        node = data.get("data", {}).get("node") or {}
        return {"obj_token": node.get("obj_token"), "obj_type": node.get("obj_type")}
    except Exception as e:
        logger.warning("飞书 wiki get_node 请求异常: %s", e)
        return None


async def _fetch_bitable_records(client: httpx.AsyncClient, headers: dict, app_token: str, table_id: Optional[str]) -> List[dict]:
    """读取多维表格（Bitable）数据，返回统一的「列名→值」字典列表。

    Args:
        app_token: 多维表格 app_token
        table_id: 数据表 table_id；为空或无效时自动回退到第一个数据表

    返回每个 record 的 fields 摊平成 {列名: 字符串值} 的字典列表。
    """
    # 1. 列出数据表（拿到全部表，用于校验/回退）
    tabs = await client.get(
        f"{FEISHU_API_BASE}/bitable/v1/apps/{app_token}/tables?page_size=100",
        headers=headers,
        timeout=TIMEOUT,
    )
    tdata = tabs.json()
    if tdata.get("code") != 0:
        logger.warning("飞书 bitable tables 获取失败: %s", tdata.get("msg"))
        return []
    items = (tdata.get("data", {}).get("items") or [])
    if not items:
        logger.warning("飞书多维表格无数据表")
        return []
    table_ids = [it.get("table_id") for it in items if it.get("table_id")]
    # 若调用方给的表 id 不在列表里（可能是 view_id 或已失效），回退到第一个表
    if not table_id or table_id not in table_ids:
        if table_id:
            logger.warning("飞书表 id=%s 不在数据表列表中，回退到第一个表", table_id)
        table_id = table_ids[0]

    # 2. 分页读取记录
    rows = []
    page_token = None
    for _ in range(20):  # 上限保护
        url = f"{FEISHU_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        rdata = (await client.get(url, headers=headers, timeout=TIMEOUT)).json()
        if rdata.get("code") != 0:
            logger.warning("飞书 bitable records 获取失败: %s", rdata.get("msg"))
            break
        data = rdata.get("data", {}) or {}
        items = data.get("items") or []
        for item in items:
            fields = (item.get("fields") or {})
            row = {k: _bitable_value_to_str(v) for k, v in fields.items()}
            rows.append(row)
        if not data.get("has_more") or not data.get("page_token"):
            break
        page_token = data.get("page_token")
    return rows


async def fetch_feishu_rows(url: Optional[str] = None) -> (List[dict], Optional[str]):
    """统一入口：按链接类型读取飞书表格/多维表格，返回 (行列表, 错误信息)。

    返回的行统一为「列名→值」字典列表（与 fetch_sheet_rows 输出一致），
    便于后续按列名匹配剧目/剧场。无法读取时返回 ([], 错误说明)。
    """
    parsed = parse_feishu_url(url) if url else None
    if not parsed:
        return [], f"无法从链接解析出飞书表格标识: {url}"

    async with httpx.AsyncClient() as client:
        token = await _get_tenant_access_token(client)
        if not token:
            return [], "未配置 FEISHU_APP_ID/FEISHU_APP_SECRET，无法访问飞书表格（公共分享链接也需 app 凭证走 Open API）"
        headers = {"Authorization": f"Bearer {token}"}

        if parsed["type"] == "spreadsheet":
            rows = await fetch_sheet_rows(parsed["token"], url)
            return (rows, None) if rows else ([], "未能读取飞书电子表格数据（检查表格权限）")

        # bitable / wiki → 解析出多维表格 app_token
        app_token = parsed["token"]
        if parsed["type"] == "wiki":
            node = await _wiki_node_to_obj(client, headers, parsed["token"])
            if not node or not node.get("obj_token"):
                return [], "无法从飞书 wiki 链接解析出多维表格（检查节点权限）"
            app_token = node.get("obj_token")
            if node.get("obj_type") not in ("bitable", "sheet", None):
                logger.warning("飞书 wiki 节点类型非表格: %s", node.get("obj_type"))

        rows = await _fetch_bitable_records(client, headers, app_token, parsed.get("sheet_id"))
        return (rows, None) if rows else ([], "未能读取飞书多维表格数据（检查 app 凭证及表格权限）")


# ─────────────────────────── 同步逻辑 ───────────────────────────

async def sync_from_feishu(url: Optional[str] = None) -> dict:
    """手动触发的入口：拉取飞书表格并更新现有剧目的剧场关联。

    返回同步结果统计。此函数独立创建数据库会话（供 Celery/独立调用），
    不依赖 FastAPI 的 get_db 依赖。
    """
    sheet_url = url or settings.FEISHU_SPREADSHEET_URL
    if not sheet_url or not sheet_url.strip():
        return {"success": False, "error": "未配置飞书表格链接（FEISHU_SPREADSHEET_URL 或请求参数 url）"}

    rows, err = await fetch_feishu_rows(sheet_url)
    if err:
        return {"success": False, "error": err}
    if not rows:
        return {"success": False, "error": "飞书表格无数据"}

    # 定位列：普通表格用首行表头，多维表格直接扫所有行汇总所有列名
    header_row = {}
    for r in rows:
        for k in r:
            header_row[k] = None
    if not header_row and rows:
        header_row = rows[0]
    drama_col = _find_col(header_row, settings.FEISHU_DRAMA_COL)
    theater_col = _find_col(header_row, settings.FEISHU_THEATER_COL)
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
