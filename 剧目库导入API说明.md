# 剧目库导入 API 说明（给其他 Agent 用）

## 一、鉴权

所有接口（除登录外）都走 `Authorization: Bearer <token>`。

### 1. 登录获取 Token

```
POST http://<host>/api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}
```

返回：
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": { ... }
}
```

取 `access_token` 作为后续请求的 Bearer。

> 默认地址：`http://192.168.1.163:3000/api`（前端走 nginx 反向代理）或 `http://192.168.1.163:8001/api`（直连后端）。
> Token 有效期约 30 分钟，过期后用 refresh_token 调用 `POST /api/auth/refresh` 刷新。

---

## 二、导入三步流程

### Step 1：解析文件（Parse）

上传 Excel / CSV 文件，后端解析为结构化行。

```
POST http://<host>/api/dramas/import/parse
Authorization: Bearer <token>
Content-Type: multipart/form-data

file=@your_file.xlsx
```

返回：
```json
{
  "rows": [
    {
      "name": "剧名A",
      "frequency": "女频",
      "type": null,
      "tags": ["古装", "甜宠"],
      "rating": "S+",
      "listing_status": "已上架",
      "listed_at": "2026-09-06 16:00",
      "material_link": "https://...",
      "theater_name": null
    }
  ],
  "total": 50,
  "file_name": "剧目表.xlsx",
  "message": "解析到 50 条剧目"
}
```

将 `rows` 整体传给 Step 2。

### Step 2：预览（Preview）

后端用 `name` 做去重键，将行分为三组：`new`（新增）、`update`（更新已有）、`unchanged`（无变化）。

```
POST http://<host>/api/dramas/import/preview
Authorization: Bearer <token>
Content-Type: application/json

{
  "rows": [ /* Step1 返回的 rows */ ],
  "file_name": "剧目表.xlsx"
}
```

返回：
```json
{
  "new": [...],
  "update": [
    {
      "id": "xxx-uuid",
      "name": "剧名A",
      "old": { "rating": "A", ... },
      "new": { "rating": "S+", ... }
    }
  ],
  "unchanged": [...],
  "summary": { "new_count": 3, "update_count": 10, "unchanged_count": 37 }
}
```

Agent 根据业务规则决定哪些行需要勾选（通常 new 全部勾选，update 视 diff 决定是否覆盖）。

### Step 3：确认导入（Confirm）

将 Step 2 中用户（或 Agent）勾选项原样带回来，执行真实写入。

```
POST http://<host>/api/dramas/import/confirm
Authorization: Bearer <token>
Content-Type: application/json

{
  "accept_new": [
    { "name": "新剧A", "frequency": "男频", "rating": "A", ... }
  ],
  "accept_update": [
    { "id": "uuid-xx", "name": "老剧B", "rating": "S+", ... }
  ],
  "file_name": "剧目表.xlsx"
}
```

确认导入后返回：
```json
{
  "imported": 3,
  "updated": 10,
  "skipped": 0,
  "errors": []
}
```

- `imported`：新增成功数（同名已存在则跳过，计入 skipped）
- `updated`：更新成功数
- `skipped`：跳过数（name 为空、同名已存在、rating 校验失败等）
- `errors`：异常列表，每条含 `{"name": "...", "error": "..."}`

---

## 三、字段含义

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 去重键，同名视为同一剧目 |
| `frequency` | string \| null | ❌ | 男频 / 女频 |
| `type` | string \| null | ❌ | AI真人剧 / 真人剧 / 动漫 等 |
| `tags` | string[] \| null | ❌ | 题材标签数组，如 `["古装","甜宠"]` |
| `rating` | string \| null | ❌ | 评级 S+ / S / A+ / A |
| `synopsis` | string \| null | ❌ | 剧情简介 |
| `listing_status` | string | ❌ 默认"已上架" | 草稿 / 待上架 / 审核中 / 已上架 / 已下架 / 归档 / 待上线 |
| `listed_at` | string \| null | ❌ | 上线时间，支持 `YYYY-MM-DD HH:mm` 或 `YYYY/MM/DD HH:mm` |
| `material_link` | string \| null | ❌ | 素材网盘链接 |
| `material_link_pwd` | string \| null | ❌ | 网盘提取码/密码 |
| `account_name` | string \| null | ❌ | 上架视频号账号名 |
| `theater_name` | string \| null | ❌ | 所属剧场名 |
| `updated_date` | string \| null | ❌ | 更新日期 |

---

## 四、Agent 一键导入示例（curl）

```bash
#!/bin/bash
set -e

TOKEN=$(curl -s -X POST http://192.168.1.163:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

HEADERS="Authorization: Bearer $TOKEN"

# Step 1: Parse
PARSE_RESULT=$(curl -s -X POST http://192.168.1.163:8001/api/dramas/import/parse \
  -H "$HEADERS" \
  -F "file=@/path/to/dramas.xlsx")

ROWS=$(echo "$PARSE_RESULT" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['rows']))")
FILE_NAME=$(echo "$PARSE_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['file_name'])")

echo "解析到 $(echo $ROWS | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))') 条"

# Step 2: Preview
PREVIEW=$(curl -s -X POST http://192.168.1.163:8001/api/dramas/import/preview \
  -H "$HEADERS" \
  -H "Content-Type: application/json" \
  -d "{\"rows\": $ROWS, \"file_name\": \"$FILE_NAME\"}")

NEW_COUNT=$(echo "$PREVIEW" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('new',[])))")
UPDATE_COUNT=$(echo "$PREVIEW" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('update',[])))")
echo "预览：新增=$NEW_COUNT 更新=$UPDATE_COUNT"

# Step 3: Confirm（Agent 自动勾选所有 new + update）
ACCEPT_NEW=$(echo "$PREVIEW" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('new',[])))")
ACCEPT_UPDATE=$(echo "$PREVIEW" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('update',[])))")

RESULT=$(curl -s -X POST http://192.168.1.163:8001/api/dramas/import/confirm \
  -H "$HEADERS" \
  -H "Content-Type: application/json" \
  -d "{
    \"accept_new\": $ACCEPT_NEW,
    \"accept_update\": $ACCEPT_UPDATE,
    \"file_name\": \"$FILE_NAME\"
  }")

echo "导入结果: $RESULT"
```

---

## 五、列名别名映射（CSV/Excel 列头兼容）

后端 `_find()` 函数用「子串匹配」识别列头，以下写法均有效：

| 目标字段 | 支持的列头（任意一个） |
|---------|---------------------|
| 剧名/name | `漫剧名称` / `名称` / `剧名` |
| 频/frequency | `男/女频` / `男女频` / `频` |
| 类型/type | `漫剧类型` / `剧类型` |
| 题材/tags | `题材`（兼容别名：若列头是「剧名」且与名称列不冲突，也映射到 tags） |
| 状态/listing_status | `上架状态` / `上线状态` / `状态` |
| 上线时间/listed_at | `上架日期` / `上线时间` / `上线日期` |
| 评级/rating | `评级` |
| 简介/synopsis | `简介` / `剧情简介` / `内容简介` |
| 素材链接/material_link | `素材链接` / `网盘链接` / `网盘地址` / `百度网盘` / `夸克网盘` / `分享链接` |
| 提取码/pwd | `网盘密码` / `提取码` / `网盘提取码` / `密码` |
| 上架账号/account_name | `上架账号` |
| 剧场/theater_name | `剧场` |

---

## 六、注意事项

1. **`name` 是唯一去重键**——同名行走 update 逻辑，不会重复创建。
2. **`listed_at` 格式容错**：支持 `YYYY-MM-DD HH:mm`、`YYYY/MM/DD HH:mm`、`YYYY.MM.DD HH:mm`，也支持纯日期 `YYYY-MM-DD`。
3. **导入历史**：每次 confirm 会生成一条历史记录，含 `import_history_id`，可用于追溯和回滚。
4. **文件类型**：支持 `.xlsx`、`.xls`、`.csv`，服务端用 pandas 解析。
5. **错误隔离**：单行异常（如 rating 超长）只跳过该行，不影响其他行。
