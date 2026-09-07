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
import csv
import io
import json
import logging
import os
import re
from datetime import datetime
from typing import List, Optional, Tuple
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


# ─────────────────────────── 平阅剧单同步（6 Sheet 合并导入）───────────────────────────

# 平阅剧单 wiki 链接（电子表格，6 个固定 Sheet）
PINGYUE_WIKI_URL = "https://my.feishu.cn/wiki/PTW7wRpY9iFJ8TkGILfciu1rnrh"

# 6 个 Sheet 的固定 ID 与数据范围（除非表格结构被修改，否则不变）
PINGYUE_SHEETS = [
    {"name": "综合剧单", "sheet_id": "9dbac7", "range": "A1:AJ650"},
    {"name": "老剧场-剧单", "sheet_id": "HbqYes", "range": "A1:AU200"},
    {"name": "新剧场-剧单1", "sheet_id": "rEysGs", "range": "A1:BD207"},
    {"name": "新剧场-剧单2", "sheet_id": "qaCvR8", "range": "A1:BE300"},
    {"name": "新剧场-剧单3", "sheet_id": "8MyIUq", "range": "A1:BE250"},
    {"name": "新剧场-剧单4", "sheet_id": "bTRn76", "range": "A1:BE250"},
]

# 平阅剧单支持的 7 个剧场
PINGYUE_THEATERS = ["海漫剧场", "云烬剧场", "晚柠漫剧", "信远漫剧社", "信远漫影", "信远漫享", "信远漫时光"]

# 剧场单元格合法状态
PINGYUE_STATUSES = {"已上线", "待上线", "审核中"}
# 状态优先级（已上线 > 待上线 > 审核中）
_PINGYUE_STATUS_RANK = {"已上线": 3, "待上线": 2, "审核中": 1}
# 飞书状态 → 剧目库 listing_status（库里合法值见前端 LISTING_STATUSES，无「已上线」）
_PINGYUE_STATUS_MAP = {"已上线": "已上架", "待上线": "待上线", "审核中": "审核中"}


def _norm_cell(v) -> str:
    """单元格值 → 去空白字符串。兼容飞书返回的文本/数字/链接对象形态。"""
    if v is None:
        return ""
    if isinstance(v, dict):
        # 超链接等富文本对象：优先取 text / name / value
        for key in ("text", "name", "value", "title"):
            if key in v:
                return _norm_cell(v[key])
        return ""
    if isinstance(v, list):
        return "".join(_norm_cell(x) for x in v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).replace("\u00a0", " ").strip()


def _norm_header(v) -> str:
    """表头归一化：去掉所有空格（含全角），如「剧  名」→「剧名」。"""
    return _norm_cell(v).replace(" ", "").replace("\u3000", "")


def _norm_pingyue_date(raw) -> str:
    """上线时间归一化：
    - 文本无年份时补当前年（如 9/5 10:00 → 2026/9/5 10:00）；
    - 飞书 Open API 对日期单元格返回 Excel 序列号数值（1900 系统，如 46272.4166 → 2026/09/07 10:00）。
    """
    if raw is None:
        return ""
    s = raw.strip() if isinstance(raw, str) else str(raw).strip()
    if not s:
        return ""
    # Excel 日期序列号（飞书 API 数值型日期：自 1899-12-30 起的天数，含小数时间部分）
    if re.match(r"^\d{5}(\.\d+)?$", s):
        try:
            from datetime import datetime as _dt, timedelta as _td
            dt = _dt(1899, 12, 30) + _td(days=float(s))
            return dt.strftime("%Y/%m/%d %H:%M")
        except (ValueError, OverflowError):
            return s
    if re.match(r"^\d{1,2}/\d{1,2}", s):
        from datetime import datetime as _dt
        return f"{_dt.now().year}/{s}"
    return s


async def _fetch_sheet_range(
    client: httpx.AsyncClient, headers: dict, spreadsheet_token: str, sheet_id: str, cell_range: str
) -> List[List]:
    """读取电子表格指定 sheet 的指定区域，返回二维网格。失败返回 []。"""
    try:
        resp = await client.get(
            f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values/{sheet_id}!{cell_range}",
            headers=headers,
            timeout=TIMEOUT,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.warning("平阅剧单 sheet=%s 读取失败: %s", sheet_id, data.get("msg"))
            return []
        return data.get("data", {}).get("valueRange", {}).get("values") or []
    except Exception as e:
        logger.warning("平阅剧单 sheet=%s 请求异常: %s", sheet_id, e)
        return []


def _parse_pingyue_grid(grid: List[List], sheet_name: str) -> List[dict]:
    """解析单个平阅 Sheet 网格 → 中间行数据列表。

    - 前 5 行内定位表头（含「剧名」列），自适应各 Sheet 列结构差异
    - 动态识别 7 个目标剧场列，提取每个剧场的状态（已上线/待上线/审核中）
    - 过滤无效行（剧名为空、无任何有效剧场状态）
    """
    if not grid:
        return []
    header_idx = None
    for i, row in enumerate(grid[:5]):
        cells = [_norm_header(c) for c in (row or [])]
        if "剧名" in cells:
            header_idx = i
            break
    if header_idx is None:
        logger.warning("平阅剧单 sheet=%s 未找到「剧名」表头，跳过", sheet_name)
        return []
    hdr = [_norm_header(c) for c in (grid[header_idx] or [])]

    name_idx = date_idx = gender_idx = rating_idx = link_idx = None
    theater_cols: dict = {}
    for i, h in enumerate(hdr):
        if not h:
            continue
        if h == "剧名" and name_idx is None:
            name_idx = i
        elif h == "上线时间" and date_idx is None:
            date_idx = i
        elif h in ("男/女频", "男女频") and gender_idx is None:
            gender_idx = i
        elif h == "评级" and rating_idx is None:
            rating_idx = i
        elif h == "网盘链接" and link_idx is None:
            link_idx = i
        else:
            for t in PINGYUE_THEATERS:
                if t in h:
                    theater_cols[i] = t
                    break
    if name_idx is None:
        return []

    def _cell(raw: List, idx) -> str:
        if idx is None or idx >= len(raw):
            return ""
        return _norm_cell(raw[idx])

    rows = []
    for raw in grid[header_idx + 1:]:
        if not raw:
            continue
        name = _cell(raw, name_idx)
        if not name or name == "剧名":
            continue
        theaters: dict = {}
        for idx, tname in theater_cols.items():
            status = _cell(raw, idx)
            if status in PINGYUE_STATUSES:
                theaters[tname] = status
        if not theaters:
            continue  # 无任何有效剧场状态的行（说明行/空行）过滤
        rows.append({
            "name": name,
            "date": _cell(raw, date_idx),
            "theaters": theaters,
            "gender": _cell(raw, gender_idx),
            "rating": _cell(raw, rating_idx),
            "url": _cell(raw, link_idx),
        })
    return rows


def _merge_pingyue_rows(parsed: List[Tuple[str, List[dict]]]) -> Tuple[dict, int]:
    """合并各 Sheet 的解析结果（剧名唯一键、先出现优先），返回 (all_data, 解析成功的 sheet 数)。"""
    all_data: dict = {}
    sheets_ok = 0
    for sheet_name, rows in parsed:
        if rows:
            sheets_ok += 1
        for row in rows:
            all_data.setdefault(row["name"], row)
    return all_data, sheets_ok


def _rows_to_import_rows(all_data: dict) -> List[dict]:
    """中间行数据 → DramaImportRow 字典列表（listing_status 取最高剧场状态映射）。"""
    rows = []
    for name, d in all_data.items():
        theaters = d["theaters"]
        top = max(theaters.values(), key=lambda s: _PINGYUE_STATUS_RANK.get(s, 0))
        rows.append({
            "name": name,
            "frequency": d["gender"] or None,
            "type": None,
            "tags": None,
            "rating": d["rating"] or None,
            "synopsis": None,
            "listing_status": _PINGYUE_STATUS_MAP.get(top, "已上架"),
            "updated_date": None,
            "listed_at": _norm_pingyue_date(d["date"]) or None,
            "material_link": d["url"] or None,
            "material_link_pwd": None,
            "account_name": None,
            "theater_name": ",".join(theaters.keys()) or None,
        })
    return rows


async def _fetch_pingyue_via_api(wiki_url: str) -> tuple:
    """Open API 直连拉取（需 FEISHU_APP_ID/SECRET）。

    返回 (rows, err, note)：rows 为空列表且 err 非空表示失败，调用方可回退本地快照。
    """
    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        return None, "未配置 FEISHU_APP_ID/FEISHU_APP_SECRET，无法访问飞书表格", ""

    parsed = parse_feishu_url(wiki_url)
    if not parsed:
        return None, f"无法解析飞书链接: {wiki_url}", ""

    async with httpx.AsyncClient() as client:
        token = await _get_tenant_access_token(client)
        if not token:
            return None, "飞书凭证无效（FEISHU_APP_ID/SECRET 被拒绝），无法获取 tenant_access_token", ""
        headers = {"Authorization": f"Bearer {token}"}

        # wiki 链接 → 解析出电子表格 obj_token；直链电子表格直接用 token
        spreadsheet_token = parsed["token"]
        if parsed["type"] == "wiki":
            node = await _wiki_node_to_obj(client, headers, parsed["token"])
            if not node or not node.get("obj_token"):
                return None, "无法从飞书 wiki 链接解析出电子表格（检查节点权限）", ""
            spreadsheet_token = node["obj_token"]
        elif parsed["type"] == "bitable":
            return None, "平阅剧单为电子表格（/wiki/ 链接），不支持多维表格直链", ""

        # 6 个 Sheet 并行拉取
        async def _one(s: dict):
            grid = await _fetch_sheet_range(client, headers, spreadsheet_token, s["sheet_id"], s["range"])
            return s["name"], grid

        results = await asyncio.gather(*[_one(s) for s in PINGYUE_SHEETS], return_exceptions=True)

    # 合并解析（剧名唯一键，先出现优先）
    parsed_rows: List[Tuple[str, List[dict]]] = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("平阅剧单拉取异常: %s", r)
            continue
        sheet_name, grid = r
        parsed_rows.append((sheet_name, _parse_pingyue_grid(grid, sheet_name)))

    all_data, sheets_ok = _merge_pingyue_rows(parsed_rows)
    if not all_data:
        return None, "平阅剧单解析结果为空（检查表格权限/Sheet 结构是否变更）", ""

    rows = _rows_to_import_rows(all_data)
    logger.info("平阅剧单拉取完成(Open API): %d 个 sheet 解析成功, %d 条剧目", sheets_ok, len(rows))
    return rows, None, ""


# ── 本地快照回退（无 FEISHU_APP_ID/SECRET 时，由 scripts/refresh_pingyue_roster.sh 供数）──

def _annotated_csv_to_grid(text: str) -> List[List]:
    """lark-cli `sheets +csv-get` 输出的 annotated_csv（[row=N] 前缀行）→ 二维网格。

    非 [row=] 开头的物理行是上一条记录被引号单元格内换行拆出的续行，回接后统一交给
    csv 模块解析，避免单元格内容被截断。
    """
    records: List[str] = []
    for line in (text or "").split("\n"):
        s = line.rstrip("\r")
        if s.startswith("[row="):
            idx = s.find("] ")
            records.append(s[idx + 2:] if idx >= 0 else "")
        elif records:
            records[-1] += "\n" + s
    grid: List[List] = []
    for rec in records:
        try:
            grid.extend(csv.reader(io.StringIO(rec)))
        except Exception:
            grid.append([rec])
    return grid


def _pingyue_cache_note(cache_dir: str) -> str:
    """快照新鲜度标注：优先读刷新脚本写入的 _meta.json，否则取目录内最新修改时间。"""
    meta_path = os.path.join(cache_dir, "_meta.json")
    try:
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                pulled_at = (json.load(f) or {}).get("pulled_at") or ""
            if pulled_at:
                return f"（本地快照 {pulled_at}，可运行 scripts/refresh_pingyue_roster.sh 更新）"
    except Exception:
        pass
    try:
        latest = max(
            os.path.getmtime(os.path.join(cache_dir, fn))
            for fn in os.listdir(cache_dir)
            if fn != "_meta.json"
        )
        return f"（本地快照 {datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M')}，可运行 scripts/refresh_pingyue_roster.sh 更新）"
    except Exception:
        return "（本地快照）"


def _load_pingyue_sheet_cache(cache_dir: str) -> List[Tuple[str, List[dict]]]:
    """回退一：读取 6 个 Sheet 的 lark-cli 原始拉取结果 {sheet_id}.json → 各自解析。"""
    parsed: List[Tuple[str, List[dict]]] = []
    found = 0
    for s in PINGYUE_SHEETS:
        path = os.path.join(cache_dir, f"{s['sheet_id']}.json")
        if not os.path.exists(path):
            continue
        found += 1
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            logger.warning("平阅剧单快照 %s 读取失败: %s", path, e)
            continue
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        text = (data or {}).get("annotated_csv") or ""
        rows = _parse_pingyue_grid(_annotated_csv_to_grid(text), s["name"])
        parsed.append((s["name"], rows))
        if (data or {}).get("has_more"):
            logger.warning(
                "平阅剧单快照 sheet=%s 未拉全（has_more=true，被 max-chars 截断），建议重跑刷新脚本",
                s["sheet_id"],
            )
    if not found:
        logger.warning("平阅剧单快照目录 %s 中未找到任何 {{sheet_id}}.json", cache_dir)
    return parsed


def _load_pingyue_csv_cache(cache_dir: str) -> List[Tuple[str, List[dict]]]:
    """回退二：读取能力文档管线的合并产出 平阅剧单.csv（剧名,上线时间,剧场,状态,男/女频,评级,网盘链接）。

    注意：CSV 的「剧场」列已合并、状态为全剧场最高状态，按列回填（粒度低于回退一，仅兜底）。
    """
    path = os.path.join(cache_dir, "平阅剧单.csv")
    if not os.path.exists(path):
        return []
    rows: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for rec in csv.DictReader(f):
                name = (rec.get("剧名") or "").strip()
                if not name:
                    continue
                status = (rec.get("状态") or "").strip()
                if status not in PINGYUE_STATUSES:
                    status = "审核中"  # 保守兜底，避免误置为已上架
                theaters: dict = {}
                for part in re.split(r"[,，、;；]", (rec.get("剧场") or "").strip()):
                    t = part.strip()
                    if t:
                        theaters[t] = status
                if not theaters:
                    continue
                rows.append({
                    "name": name,
                    "date": (rec.get("上线时间") or "").strip(),
                    "theaters": theaters,
                    "gender": (rec.get("男/女频") or "").strip(),
                    "rating": (rec.get("评级") or "").strip(),
                    "url": (rec.get("网盘链接") or "").strip(),
                })
    except Exception as e:
        logger.warning("平阅剧单快照 CSV %s 读取失败: %s", path, e)
        return []
    return [("平阅剧单.csv", rows)] if rows else []


def _fetch_pingyue_from_cache(cache_dir: str) -> tuple:
    """从本地快照目录构建导入行。返回 (rows, err, note, source)，source ∈ {快照JSON, 快照CSV}。"""
    parsed = _load_pingyue_sheet_cache(cache_dir)
    source = "快照JSON"
    if not parsed or not any(rows for _, rows in parsed):
        parsed = _load_pingyue_csv_cache(cache_dir)
        source = "快照CSV"
    if not parsed:
        return [], f"本地快照目录 {cache_dir} 无可用数据（先运行 scripts/refresh_pingyue_roster.sh）", "", source

    all_data, sheets_ok = _merge_pingyue_rows(parsed)
    rows = _rows_to_import_rows(all_data)
    note = _pingyue_cache_note(cache_dir)
    logger.info("平阅剧单拉取完成(%s): %d 个数据源解析成功, %d 条剧目", source, sheets_ok, len(rows))
    return rows, None, note, source


# ─────────────────────── 拉取状态记录（供 /dramas/feishu-roster/status 展示实时状态）───────────────────────

_LAST_PINGYUE_FETCH: Optional[dict] = None


def _record_pingyue_fetch(source: str, ok: bool, rows_count: int, err: Optional[str], note: str) -> None:
    """记录最近一次平阅剧单拉取的数据源与结果（进程内内存态，供状态端点查询）。"""
    global _LAST_PINGYUE_FETCH
    _LAST_PINGYUE_FETCH = {
        "source": source,
        "ok": ok,
        "rows": rows_count,
        "err": (err or "").strip(),
        "note": (note or "").strip(),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_pingyue_fetch_status() -> dict:
    """飞书剧单同步实时状态：凭证配置、本地快照文件与时间、最近一次拉取的数据源/结果。"""
    cache_dir = (settings.FEISHU_ROSTER_CACHE_DIR or "").strip()
    snapshots: List[dict] = []
    if cache_dir and os.path.isdir(cache_dir):
        for fn in sorted(os.listdir(cache_dir)):
            if not fn.endswith(".json"):
                continue
            try:
                pulled_at = datetime.fromtimestamp(os.path.getmtime(os.path.join(cache_dir, fn)))
            except OSError:
                continue
            snapshots.append({"name": fn, "pulled_at": pulled_at.strftime("%Y-%m-%d %H:%M:%S")})
        csv_path = os.path.join(cache_dir, "平阅剧单.csv")
        if os.path.exists(csv_path):
            try:
                pulled_at = datetime.fromtimestamp(os.path.getmtime(csv_path))
                snapshots.append({"name": "平阅剧单.csv", "pulled_at": pulled_at.strftime("%Y-%m-%d %H:%M:%S")})
            except OSError:
                pass
    configured = bool((settings.FEISHU_APP_ID or "").strip() and (settings.FEISHU_APP_SECRET or "").strip())
    return {
        "configured": configured,
        "cache_dir": cache_dir,
        "cache_dir_exists": bool(cache_dir and os.path.isdir(cache_dir)),
        "snapshots": snapshots,
        "wiki_url": settings.FEISHU_SPREADSHEET_URL or PINGYUE_WIKI_URL,
        "last_fetch": _LAST_PINGYUE_FETCH,
    }


async def fetch_pingyue_roster(url: Optional[str] = None) -> tuple:
    """拉取并解析平阅剧单（6 个 Sheet 并行），返回 (DramaImportRow 字典列表, 错误信息, 附加说明)。

    数据源优先级：
      1. 飞书 Open API 直连（需 FEISHU_APP_ID/FEISHU_APP_SECRET）
      2. 本地快照 {FEISHU_ROSTER_CACHE_DIR}/{sheet_id}.json（lark-cli 拉取）
      3. 本地快照 {FEISHU_ROSTER_CACHE_DIR}/平阅剧单.csv（能力文档管线产出）

    - 跨 Sheet 以剧名为唯一键去重（先出现的优先，综合剧单排最前）
    - 每行输出与 /dramas/import/parse 相同的结构化字段，前端可直接复用导入预览/确认流程
    - listing_status 取该剧所有剧场中的最高状态（已上线→已上架 > 待上线 > 审核中）
    """
    wiki_url = (url or "").strip() or settings.FEISHU_SPREADSHEET_URL or PINGYUE_WIKI_URL

    # 显式传入的自定义链接解析失败时直接报错（不静默回退快照）
    explicit_url = bool((url or "").strip())
    parsed_url = parse_feishu_url(wiki_url)
    if explicit_url and not parsed_url:
        parse_err = f"无法解析飞书链接: {wiki_url}"
        _record_pingyue_fetch("url_parse", False, 0, parse_err, "")
        return [], parse_err, ""

    # 1) Open API 直连
    rows, err, note = await _fetch_pingyue_via_api(wiki_url)
    if rows:
        _record_pingyue_fetch("api", True, len(rows), err, note)
        return rows, err, note

    # 2)/3) 本地快照回退
    cache_dir = (settings.FEISHU_ROSTER_CACHE_DIR or "").strip()
    if cache_dir and os.path.isdir(cache_dir):
        if err:
            logger.warning("平阅剧单 Open API 拉取失败（%s），回退本地快照 %s", err, cache_dir)
        cache_rows, cache_err, cache_note, cache_source = _fetch_pingyue_from_cache(cache_dir)
        # 即使快照成功也保留 API 失败原因，便于状态端点解释为何走了快照
        _record_pingyue_fetch(cache_source, bool(cache_rows), len(cache_rows), err or cache_err, cache_note)
        return cache_rows, cache_err, cache_note

    final_err = err or (
        "未配置 FEISHU_APP_ID/FEISHU_APP_SECRET，且本地快照目录不存在"
        "（运行 scripts/refresh_pingyue_roster.sh 生成快照，或在 .env 配置飞书应用凭证）"
    )
    _record_pingyue_fetch("none", False, 0, final_err, "")
    return [], final_err, ""
