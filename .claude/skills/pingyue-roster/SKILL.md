---
name: pingyue-roster
description: Access and operate the Feishu Pingyue drama roster system. Invoke when user asks to sync/import drama data from Feishu, check sync status, troubleshoot roster issues, or query drama lists from the online spreadsheet.
---

# 平阅剧单 (Pingyue Roster)

系统从飞书在线表格「平阅剧单」读取剧目数据，同步到本地数据库。本文档描述完整访问方式，供 AI agent 独立完成相关操作。

---

## 1. 核心信息

| 项目 | 值 |
|------|-----|
| 文档类型 | 飞书知识库 wiki 节点 |
| 文档链接 | `https://my.feishu.cn/wiki/PTW7wRpY9iFJ8TkGILfciu1rnrh` |
| Wiki Token | `PTW7wRpY9iFJ8TkGILfciu1rnrh` |
| Sheet 数量 | 6 个固定 Sheet |
| 解析服务 | `backend/app/services/feishu_service.py` |
| API 路由 | `backend/app/api/dramas.py`（第 1209、1238 行） |

### 6 个 Sheet

| Sheet 名称 | sheet_id | range | 说明 |
|-----------|----------|-------|------|
| 综合剧单 | `9dbac7` | `A1:AJ650` | 主剧单，优先级最高 |
| 老剧场-剧单 | `HbqYes` | `A1:AU200` | 历史剧场 |
| 新剧场-剧单1 | `rEysGs` | `A1:BD207` | 含晚柠漫剧等新增剧场 |
| 新剧场-剧单2 | `qaCvR8` | `A1:BE300` | — |
| 新剧场-剧单3 | `8MyIUq` | `A1:BE250` | — |
| 新剧场-剧单4 | `bTRn76` | `A1:BE250` | — |

Sheet 名和 range 硬编码在 `PINGYUE_SHEETS` 常量中（`feishu_service.py:71-77`）。

---

## 2. 环境变量配置

项目 `.env` 文件需包含以下变量：

```bash
# 飞书应用凭证（Open API 直连用）
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

# 剧单文档链接（可选，默认已内置）
FEISHU_SPREADSHEET_URL=https://my.feishu.cn/wiki/PTW7wRpY9iFJ8TkGILfciu1rnrh

# 本地快照目录（回退用）
FEISHU_ROSTER_CACHE_DIR=/data/pingyue_cache
```

配置后重启服务生效：
```bash
docker compose restart backend
```

---

## 3. API 接口

### 3.1 手动触发同步

```bash
curl -X POST http://localhost:8000/api/dramas/import/feishu-roster \
  -H "Content-Type: application/json" \
  -d '{"url": "https://my.feishu.cn/wiki/PTW7wRpY9iFJ8TkGILfciu1rnrh"}'
```

- `url` 为可选参数，省略则使用 `.env` 中的 `FEISHU_SPREADSHEET_URL`
- 响应返回解析后的剧目列表（JSON），前端收到后触发导入流程

**响应示例**：
```json
{
  "rows": [...],
  "total": 291,
  "file_name": "平阅剧单(飞书同步)",
  "message": "从飞书拉取到 291 条剧目"
}
```

### 3.2 查询同步状态

```bash
curl http://localhost:8000/api/dramas/feishu-roster/status
```

**响应**：
```json
{
  "configured": true,
  "wiki_url": "https://my.feishu.cn/wiki/PTW7wRpY9iFJ8TkGILfciu1rnrh",
  "last_fetch": {
    "source": "api",
    "success": true,
    "count": 291,
    "err": null,
    "note": "",
    "fetched_at": "2026-09-07T10:00:00"
  },
  "snapshots": [...]
}
```

`source` 字段说明数据来源：
- `api` — Open API 直连（正常路径）
- `快照JSON` — 本地 JSON 快照回退
- `快照CSV` — 本地 CSV 快照回退

---

## 4. 内部数据流

```
POST /dramas/import/feishu-roster
  └─ fetch_pingyue_roster(url)
       ├─ _get_tenant_access_token() → tenant_access_token
       ├─ _wiki_node_to_obj(wiki_token) → spreadsheet token
       └─ [sheets/v2/spreadsheets/{token}/ranges/get] × 6 并行
            └─ _parse_pingyue_grid(grid, sheet_name)
                 └─ 返回 list[DramaImportRow]

_merge_pingyue_rows(parsed_list)
  └─ 按剧名合并，theaters 字典取并集，同剧场取最高状态
       └─ 返回 (all_data, sheets_ok)
```

---

## 5. 解析规则

### 5.1 单元格值归一化

- 文本/链接对象：优先取 `text` / `name` / `value` / `title`
- 数字：`float` 且为整数时转为字符串
- **Excel 日期序列号**：匹配 `^\d{5}(\.\d+)?$` 按 1899-12-30 为基准转换
  - `46272.416666` → `2026/09/07 10:00`
  - `46272.666666` → `2026/09/07 16:00`
- 无年份日期：补当前年（如 `9/5 10:00` → `2026/9/5 10:00`）

### 5.2 剧场列匹配

每次同步从 `theaters` 表动态读取配置的剧场名，回退到内置列表：

```python
PINGYUE_THEATERS = ["海漫剧场", "云烬剧场", "晚柠漫剧",
                    "信远漫剧社", "信远漫影", "信远漫享", "信远漫时光"]
```

单元格内容包含任意配置剧场名即匹配。

### 5.3 合法状态值

```python
PINGYUE_STATUSES = {"已上线", "待上线", "审核中"}
```

其他值（如「暂无法上线」「审核失败」）不视为有效状态，对应行不会出现在结果中。

### 5.4 状态映射

| 飞书状态 | 入库 `listing_status` |
|---------|---------------------|
| 已上线 | 已上架 |
| 待上线 | 待上线 |
| 审核中 | 审核中 |

### 5.5 跨 Sheet 合并规则

- 剧名是唯一键
- 同剧名跨 Sheet 出现时：合并 `theaters` 字典（取并集）
- 同剧场多状态：取最高 rank（已上线=3 > 待上线=2 > 审核中=1）
- 最终 `listing_status`：该剧所有剧场中的最高状态映射

---

## 6. 本地快照（回退路径）

当 Open API 失败或凭证未配置时，系统读取本地快照：

```bash
# 快照目录由 FEISHU_ROSTER_CACHE_DIR 指定，默认 /data/pingyue_cache
# 快照文件格式：
#   {sheet_id}.json      — 单个 Sheet 原始网格
#   平阅剧单.csv          — 已解析的 CSV 汇总
```

刷新快照（需 `lark-cli` 工具）：
```bash
bash scripts/refresh_pingyue_roster.sh
```

---

## 7. 常见故障排查

### 今天待上线剧目为空

**根因**：飞书 API 返回 Excel 日期序列号，旧版解析器无法处理导致 `listed_at` 为 NULL。
**修复**：运行补数脚本：
```bash
python scripts/fix_dates.py
```

### 某剧场剧目数量不符

**根因**：`theaters` 表已删除某些剧场，但代码内置兜底列表仍包含。
**排查**：
```bash
curl http://localhost:8000/api/theaters          # 查看系统配置的剧场
curl http://localhost:8000/api/dramas/feishu-roster/status  # 查看 last_fetch.note
```

### theater_name 顺序变化触发误更新

**根因**：原比较区分顺序。
**修复**：已改为 `sorted()` 集合比较（commit 64abf96），无需操作。

### Open API 失败，走快照回退

**排查**：
1. 检查 `.env` 中 `FEISHU_APP_ID/SECRET` 是否正确
2. 确认飞书应用有表格读取权限
3. 重新配置后重启：`docker compose restart backend`
4. 若无凭证，运行快照脚本：`bash scripts/refresh_pingyue_roster.sh`

---

## 8. 关键代码位置

| 文件 | 行号 | 内容 |
|------|------|------|
| `backend/app/services/feishu_service.py` | 71-77 | `PINGYUE_SHEETS` 常量 |
| `backend/app/services/feishu_service.py` | 79-83 | `PINGYUE_STATUSES` 常量 |
| `backend/app/services/feishu_service.py` | 463-560 | `fetch_pingyue_roster()` 入口 |
| `backend/app/services/feishu_service.py` | 644-684 | `_merge_pingyue_rows()` 合并逻辑 |
| `backend/app/services/feishu_service.py` | 806-861 | `_parse_pingyue_grid()` 单元格解析 |
| `backend/app/services/feishu_service.py` | 266-304 | `_norm_pingyue_date()` 日期归一化 |
| `backend/app/services/feishu_service.py` | 131-185 | `_get_tenant_access_token()` |
| `backend/app/services/feishu_service.py` | 187-228 | `_wiki_node_to_obj()` |
| `backend/app/api/dramas.py` | 1209-1236 | `POST /dramas/import/feishu-roster` |
| `backend/app/api/dramas.py` | 1238-1250 | `GET /dramas/feishu-roster/status` |
