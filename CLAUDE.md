# CLAUDE.md — clip-workflow 仓库 Agent 上下文

> 本文件供 Claude Code / Codex / Trae / CodeBuddy 等 AI agent 打开本仓库时读取，了解关键约定与近期改动。
> 由主 Agent（WorkBuddy）于 2026-08-11 写入，随 **CNB 主仓 + GitHub 备仓** 同步到所有端。

## 双仓拓扑（重要）
- **cnb（CNB）** = 主仓：`cnb.cool/ben500500/clip-workflow`
- **origin（GitHub）** = 备份仓：`github.com/ben500500/clip-workflow`
- 推送顺序：**先 `cnb` 后 `origin`**。GitHub 仅作备份，不要往 GitHub 提 PR 当主流程。

## 双仓同步方式
- 脚本：`scripts/sync_remotes.sh`（先推 cnb，成功才推 origin；任一步失败即中止，保证备份不超前主仓）
- 自动化：WorkBuddy 定时任务 `automation-1786413346300` 每小时执行上述逻辑
- 手动：`git push cnb main && git push origin main`

## 认证（重要 — 2026-08-11）
- ⚠️ **cnb remote URL 必须内联 access token**（形如 `https://cnb:<token>@cnb.cool/...`）。实测剥离 token 后 CNB 返回「仓库不存在」——**CNB 平台要求 token 在 URL**（无 GUI 终端下 `git credential approve` 静默失败，且 CNB 不接受 basic-auth 钥匙串方式）。**不要尝试把 cnb token 剥离到钥匙串或 SSH**，否则无法推送。
- **origin（GitHub）** 走 `osxkeychain` 钥匙串，URL 不含 token，可正常推送。
- 安全建议：cnb token 一旦暴露（如本会话曾明文出现 / 出现在日志·导出包），去 CNB 后台**轮换/吊销**；或更彻底改 SSH（需 cnb.cool 注册公钥，且须先验证可用性）。在 CNB 支持 SSH/Personal Access Token 之前，token 内联 URL 是唯一可用方案。

## 环境变量安全
- `.env` / `.env.local` / `.env.production` / `.env.development` 已被 `.gitignore` 忽略，**切勿提交**。
- 部署配置来源：用户导出包 `配置导出-20260810.tar.gz`（含 clip-workflow 与 autoclip-hot 的 docker-compose / .env / nginx / init.sql），仅本地使用，不进库。

## 评测集（eval/）
- 用途：验证 AutoClip 高光选择 LLM（qwen-plus / qwen3.7）的时间点精度与评分质量。
- 运行（在 `eval/` 内）：
  - `python3 grade_highlight_llm.py --dry-run` —— 验证逻辑，无需 API key
  - `DASHSCOPE_API_KEY=sk-xxx python3 grade_highlight_llm.py --model qwen-plus` —— 真实跑模型
- 评分契约（已核实，无需改代码）：
  - LLM 输出 `final_score ∈ [0,1]`
  - `autoclip/app/main.py:141` 换算 `score = round(final_score * 100, 2)`（0–100）
  - `main.py:155` 写入契约字段 `score`；`/clips` 端点按 `c["score"] >= min_score(60)` 过滤（`main.py:604`）
  - 后端 `celery/tasks.py:193` 取契约 clips 存 `ClipCandidate.score`，`autoclip.py:362` 按同一阈值过滤 —— 两条路径尺度一致
- 时长约束由配置驱动：`step2_timeline.py` 用正则剥离 prompt 硬编码的「≥90s」，改由 `AUTOCLIP_CONFIG`（30/180）或前端 `duration_config` 注入。

## 安全审查参考（docs/reviews/）
- `docs/reviews/CODE_REVIEW_REPORT.md` + `docs/reviews/FIX_PLAN.md`：2026-08-10 多代理只读静态审查，列 **12 个高危项**（安全 6 / 性能 5 / 架构 1），均带 `file:line` 证据，尚未修复。
- 关键高危（改动前先读这两份）：**100+ API 端点零鉴权**、**CDP 9222 公网暴露**、**一行 SQL 错误致全库 0 索引**、**单 Celery worker 串行吞 4 队列**。

## 关键文件速查
- AutoClip 高光选择：`autoclip/app/pipeline/step2_timeline.py`（时间点）、`step3_scoring.py`（评分）
- 契约换算与 clips 过滤：`autoclip/app/main.py`（L141 `*100` / L155 写 score / L604 过滤）
- 后端客户端：`backend/app/services/autoclip_service.py`
- 评测集说明：`eval/README.md`
