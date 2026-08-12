#!/bin/bash
# ============================================================
# clip-workflow 部署自检脚本
# 用法：在服务器上 bash scripts/healthcheck.sh
# 输出：每项 ✅/❌ + 末尾 PASS/FAIL 汇总
# 依赖：docker（compose 服务已启动）
# ============================================================
PASS=0
FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✅${NC} $1"; PASS=$((PASS+1)); }
bad()  { echo -e "  ${RED}❌${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "  ${YELLOW}⚠️${NC} $1"; }

# Redis 密码（从容器环境读取，避免硬编码）
REDIS_PASS=$(docker exec clip-backend printenv REDIS_PASSWORD 2>/dev/null || echo "")

echo "════════════ clip-workflow 自检 ════════════"

echo ""
echo "── [1] 容器健康 ──"
TOTAL=$(docker compose -f /home/cc12703/clip-workflow/docker-compose.yml ps --format '{{.Name}}' 2>/dev/null | wc -l)
HEALTHY=$(docker ps --filter 'name=clip-' --format '{{.Status}}' | grep -c healthy 2>/dev/null)
echo "  运行中容器: $HEALTHY / $TOTAL"
if [ "$HEALTHY" -ge 10 ]; then ok "核心容器 healthy（$HEALTHY 个）"; else bad "容器健康数不足（$HEALTHY/$TOTAL）"; fi

echo ""
echo "── [2] 服务端点 ──"
API=$(curl -sf http://localhost:80/api/health 2>/dev/null | grep -o '"status":"ok"' | head -1)
if [ "$API" = '"status":"ok"' ]; then ok "backend API /api/health"; else bad "backend API 不可用"; fi
FE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:80/ 2>/dev/null)
if [ "$FE" = "200" ]; then ok "前端页面 200"; else bad "前端返回 $FE"; fi

echo ""
echo "── [3] 源视频目录与权限 ──"
VIDEO_HOST=""
for c in clip-worker-fast clip-backend; do
  M=$(docker inspect $c --format '{{range .Mounts}}{{if eq .Destination "/home/cc12703/videos"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)
  if [ -n "$M" ]; then VIDEO_HOST="$M"; break; fi
done
if [ -n "$VIDEO_HOST" ] && [ -d "$VIDEO_HOST" ]; then
  PERM=$(stat -c '%a' "$VIDEO_HOST" 2>/dev/null)
  if [ "$PERM" = "777" ]; then ok "videos 目录已挂载且 777（$VIDEO_HOST）"; else warn "videos 目录挂载但权限 $PERM（应为 777，否则 batch 删源会失败）"; fi
else
  bad "videos 目录未挂载或不存在（检查 compose bind mount /home/cc12703/videos）"
fi
docker exec clip-worker-fast ls /home/cc12703/videos/ >/dev/null 2>&1 && ok "worker 容器内可见 videos 目录" || bad "worker 容器内看不到 videos 目录"

echo ""
echo "── [4] 字体环境（固定文字字形） ──"
FT=$(docker exec clip-slice-worker python3 -c "import fontTools; print(fontTools.version)" 2>/dev/null)
if [ -n "$FT" ]; then ok "slice-worker fontTools $FT"; else bad "slice-worker 缺 fontTools（检查 Dockerfile py3-fonttools）"; fi
FONT=$(docker exec clip-slice-worker python3 -c "import sys; sys.path.insert(0,'/app/engines'); import slice; print(slice._resolve_drawtext_font())" 2>/dev/null)
if echo "$FONT" | grep -q "NotoSansCJKsc-Regular"; then ok "引擎字体解析为 SC 单字体（$FONT）"; else warn "引擎字体解析：$FONT（非 SC 提取，可能字形异常）"; fi

echo ""
echo "── [5] 数据库迁移列 ──"
COL=$(docker exec clip-postgres psql -U clipworkflow -d clipworkflow -t -c "SELECT count(*) FROM information_schema.columns WHERE table_name='batch_slice_items' AND column_name='detect_task_id';" 2>/dev/null | tr -d ' ')
if [ "$COL" = "1" ]; then ok "batch_slice_items.detect_task_id 存在"; else warn "detect_task_id 列缺失（alembic 未生效，需手动 ALTER）"; fi

echo ""
echo "── [6] 队列与 Redis 分库 ──"
if [ -n "$REDIS_PASS" ]; then
  CELERY_Q=$(docker exec clip-redis redis-cli -a "$REDIS_PASS" -n 1 LLEN celery 2>/dev/null)
  SLICE_Q=$(docker exec clip-redis redis-cli -a "$REDIS_PASS" -n 0 LLEN slice:tasks:normal 2>/dev/null)
  echo "  celery 队列(db1): ${CELERY_Q:-?} 条 / slice 队列(db0): ${SLICE_Q:-?} 条"
  if [ -n "$CELERY_Q" ] && [ "$CELERY_Q" -lt 50 ]; then ok "celery 队列无堆积（${CELERY_Q} 条）"; else warn "celery 队列 ${CELERY_Q} 条（>50 需检查 worker 消费）"; fi
else
  warn "无法读取 Redis 密码（跳过队列检查）"
fi

echo ""
echo "── [7] Ollama / 画面理解 ──"
OA=$(docker ps --filter 'name=clip-ollama' --format '{{.Status}}' 2>/dev/null | grep -c healthy)
if [ "$OA" = "1" ]; then ok "ollama healthy"; else warn "ollama 未运行（画面理解不可用，AI 选点会降级）"; fi
MODEL=$(docker exec clip-ollama ollama list 2>/dev/null | grep -c minicpm)
if [ "$MODEL" -ge 1 ]; then ok "MiniCPM-V 模型已加载"; else warn "MiniCPM-V 模型未加载"; fi

echo ""
echo "── [8] 残留检查 ──"
MEDIA_CNT=$(docker exec clip-autoclip ls /app/media/*.mp4 2>/dev/null | wc -l)
echo "  media 源副本: $MEDIA_CNT 个"
if [ "$MEDIA_CNT" -le 20 ]; then ok "media 卷无大量残留"; else warn "media 卷文件较多（$MEDIA_CNT，建议清理）"; fi

echo ""
echo "════════════ 自检结果 ════════════"
echo -e "  ${GREEN}通过 $PASS${NC} / ${RED}失败 $FAIL${NC} / 警告项见 ⚠️"
if [ "$FAIL" = "0" ]; then
  echo -e "  ${GREEN}部署健康，可投入使用${NC}"
  exit 0
else
  echo -e "  ${RED}存在 $FAIL 项失败，按上方提示修复后重跑${NC}"
  exit 1
fi
