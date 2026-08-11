# clip-workflow 高光选择 LLM 轻量评测集

针对短剧切片系统 **clip-workflow / AutoClip** 的「高光选择 LLM」做端到端评测。
不依赖 Docker，本地 Python 3 直接跑；黄金答案已预先填好（填空式），可直接对照模型输出打分。

## 它测的是什么

AutoClip 高光选择是 4 步流水线，**本评测集覆盖最核心的两步**：

| 步骤 | 真实代码 | 输入 | 输出 | 本集用例 |
|------|----------|------|------|----------|
| Step2 时间点 | `autoclip/app/pipeline/step2_timeline.py` + `prompts/时间点.txt` | outline + SRT | 带 `start_time/end_time` 的片段 JSON | T01–T06 |
| Step3 评分 | `autoclip/app/pipeline/step3_scoring.py` + `prompts/推荐理由.txt` | 片段 | `final_score` + `recommend_reason` | S01–S03 |

评测时**复用仓库里同一套 prompt**（`prompts/` 已复制），所以测的是生产环境的真实行为，不是另写一套。

## 文件

```
clip-workflow/eval/            # 本目录（已并入 clip-workflow 仓库）
├── eval_cases.json        # 9 个用例 + 黄金答案（已填好）
├── grade_highlight_llm.py # 评分器（零外部依赖，标准库 urllib 调 DashScope）
├── prompts/
│   ├── 时间点.txt          # 复制自仓库，保证与线上一致
│   └── 推荐理由.txt
└── eval_report.json       # 运行后生成
```

## 用法

```bash
# 1) 干跑：用黄金答案当预测，验证评分逻辑本身（无需联网/密钥）
python3 grade_highlight_llm.py --dry-run

# 2) 实跑：需要 DASHSCOPE_API_KEY
export DASHSCOPE_API_KEY=sk-xxxx
python3 grade_highlight_llm.py --model qwen-plus        # 也可换 qwen3.7-flash-2026-07-15
python3 grade_highlight_llm.py --model qwen-max --cases eval_cases.json --report eval_report.json
```

评分参考：`≥0.80 优秀 / 0.60–0.79 可用 / <0.60 需调优`。

## 评测维度

**时间点（T 系列）**
- `timestamp_accuracy`：预测 `[start,end]` 与黄金答案的时间容差（默认 ±10s）
- `endpoint_not_block_end`：话题在块中结束的，模型**不能把 end 无脑设为 SRT 块尾**（T01）
- `endpoint_at_block_end_allowed`：话题延伸到块尾的，end 允许等于块尾（T04 对照）
- `duration_constraints`：每段时长 ∈ `[min,max]`（默认 30–180s）
- `merge_short_adjacent`：相邻短话题应合并（T02）
- `split_overlong`：超长内容应拆分（T05）
- `format_valid` / JSON 健壮性：含中文引号/特殊字符仍输出可解析 JSON（T06）

**评分（S 系列）**
- `monotonicity`：强钩子/反转片段的 `final_score` 应高于弱铺垫（S01）
- `score_scale`：分数必须用 **0–1** 尺度，误用 0–100 判 `scale_error`（S02）
- `reason_length`：推荐语 15–30 字、戳中亮点（S03）

## ⚠️ 顺带发现的两个项目风险（已核实）

1. **分数尺度不一致（高危）→ 已核实：不成立 ✅**
   链路：`step3` 产出 `final_score`(0–1) → `_to_contract_clips()` 在 `autoclip/app/main.py:141` 做 `score = round(final_score * 100, 2)` → 写入契约字段 `score`(0–100)（main.py:155）→ `proj["clips"]` 存储契约格式（main.py:377-378）→ `/api/v1/clips` 端点按 `c["score"] >= min_score` 过滤（main.py:604）。后端 `autoclip_service.get_clips` 转发 `min_score=60.0`。
   **结论**：0–1→0–100 的换算在契约转换层已正确完成，阈值 60 比较的是换算后的 `score`，不会被清空。前提：AutoClip 服务以「内存态」`proj["clips"]` 返回（当前实现如此）。若后续接入数据库持久化且只存 `final_score`(0–1) 而未转 `score`，该风险会重新出现——接入 DB 时需注意。

2. **时长默认值不一致（中危）→ 已核实：已缓解 ✅**
   `step2_timeline.py` 在 line 88-90 用正则**剥离** `时间点.txt` 里硬编码的「≥90s」校验，并在 line 105-106 按注入的 `min_dur/max_dur`（来自 `AUTOCLIP_CONFIG` 的 30/180，或前端 `duration_config` 覆盖）重新写入时长约束。只要 `min_dur>0` 被注入，实际生效的就是配置值（30/180），prompt 默认值被覆盖。
   **结论**：配置驱动优先，风险已基本消解；仅在「完全不注入 duration_config（min_dur=0）」时回到无约束状态。本评测集按 30/180 对齐，无需改动。

> 评测集默认模型 `qwen-plus`，与 `shared_config.MODEL_NAME` 一致；你实际配置的 `qwen3.7-plus / qwen3.7-flash-2026-07-15` 也可直接传入 `--model`。
