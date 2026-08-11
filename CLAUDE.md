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

## 认证（重要改动 — 2026-08-11）
- ⚠️ **cnb / origin 的 remote URL 均不再内联 token**。认证改走 macOS 钥匙串（`osxkeychain`）。
- cnb 凭证已存入钥匙串；remote URL 保持 `https://cnb@cnb.cool/...` 形式（不带 token）。
- **不要再把 token 写回 remote URL**——会随 `git remote -v`、日志、配置导出包泄露。
- 如需重配 cnb 凭证：把 token 通过 `git credential approve`（或首次推送时输入）存入钥匙串即可，URL 维持无 token 形式。

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

## 关键文件速查
- AutoClip 高光选择：`autoclip/app/pipeline/step2_timeline.py`（时间点）、`step3_scoring.py`（评分）
- 契约换算与 clips 过滤：`autoclip/app/main.py`（L141 `*100` / L155 写 score / L604 过滤）
- 后端客户端：`backend/app/services/autoclip_service.py`
- 评测集说明：`eval/README.md`
